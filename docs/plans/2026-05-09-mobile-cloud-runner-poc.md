# Plan: Mobile Cloud Runner POC (ace-web side)

**Date:** 2026-05-09
**Status:** Draft for review
**Owner:** Jon
**Spec:** `../specs/` → cross-repo at
`/Users/jjackson/emdash/worktrees/ace/emdash/explore-remote-mobile-c6tj3/docs/superpowers/specs/2026-05-09-mobile-cloud-runner-poc.md`

This plan covers ace-web's side only. The MCP `CLOUD` backend
(`mcp/mobile/backends/cloud.ts`) lands in the ACE repo afterwards.

## Translation of spec to ace-web stack

The spec was drafted with an Express-shaped backend and SSH transport.
ace-web is Django + DRF + Channels and we're using SSM Session Manager
instead of inbound SSH. The contract (8 routes, JSON bodies, bearer auth,
return shapes) is unchanged — only the runtime is different.

| Spec says | ace-web reality |
|---|---|
| Express routes | DRF function-views in `apps/mobile/views.py`, wired via `apps/mobile/urls.py` and included in `config/urls.py` at `/api/mobile/` |
| `Authorization: Bearer <ACE_WEB_PAT_TOKEN>` | Existing `apps.auth.token_backend.BearerTokenAuthentication` (PersonalToken model). PAT minted via `/ace:ace-web-pat-mint` |
| `ssh2` lib over SSH | boto3 `ssm.send_command` for shell exec on the instance; no inbound SSH, no SG rule, no key management |
| Express `try/finally` | Python `try/finally` in `EmulatorController.run_recipe` |
| `{error: {code, message}}` | Existing `apps.common.envelope.error_response` (the `{data, error}` envelope) — same shape |

## App layout

```
apps/mobile/
├── __init__.py
├── apps.py
├── controller.py         # EmulatorController: AWS SDK + SSM exec + S3 presign
├── singleton.py          # Redis-backed cross-task lock
├── ssm.py                # Thin boto3 wrapper: send_command + poll
├── serializers.py        # DRF request/response serializers (validation only)
├── views.py              # 8 endpoints
├── urls.py
├── exceptions.py
└── tests/
    ├── __init__.py
    ├── conftest.py        # boto3 stubs (botocore.stub.Stubber)
    ├── test_views.py      # endpoint contract tests
    ├── test_controller.py # controller orchestration tests
    └── test_singleton.py  # Redis lock semantics
```

No ORM models in v1 — instance state lives in EC2 (single instance,
described via `ec2.describe_instances`) and Redis (lock + idle markers).
This matches `apps/opps/` (no ORM tables, Drive is source of truth).

## Endpoints (8, matching spec contract)

All under `/api/mobile/`, all DRF function-views, all with
`@authentication_classes([BearerTokenAuthentication])` +
`@permission_classes([IsAuthenticated])`. All return the `{data, error}`
envelope.

| Method | Path | Body | Returns | Idempotent |
|---|---|---|---|---|
| POST | `/ensure-running` | `{}` | `{instance_id, state, public_dns, started_at}` | yes |
| POST | `/install-apk` | `{apk_url}` | `{package_name, version}` | no |
| POST | `/run-recipe` | `{recipe_yaml, env, screenshot_prefix?}` | `{exit_code, stdout, stderr, artifacts: [{name, presigned_url, content_type}]}` | no |
| POST | `/save-snapshot` | `{name}` | `{name, saved_at}` | no |
| POST | `/load-snapshot` | `{name}` | `{name, loaded_at}` | no |
| POST | `/capture-ui-dump` | `{}` | `{xml: string}` | no |
| POST | `/stop` | `{}` | `{instance_id, state, stopped_at}` | yes |
| GET | `/status` | — | `{instance_id, state, last_run_at, idle_for_seconds, ami_version}` | yes |

`run-recipe` always wraps the inner work in `try/finally` and bumps the
in-VM idle marker so layer 2 can't fire mid-run. The `finally` does NOT
auto-stop — auto-stop is the in-VM idle layer's job (5 min) so back-to-back
calls don't waste a 90 s cold start. The CloudWatch alarm + 5 min idle
window handle the dead-process case.

## EmulatorController (`apps/mobile/controller.py`)

Sync class. boto3 clients lazy-built and cached on the instance.

```python
class EmulatorController:
    def __init__(self, *, instance_id: str, region: str, s3_bucket: str): ...

    # Lifecycle
    def ensure_running(self) -> RunningState: ...
    def stop(self) -> StoppedState: ...
    def status(self) -> Status: ...

    # Operations (all assert running first, all bump idle marker)
    def install_apk(self, apk_url: str) -> InstallResult: ...
    def run_recipe(
        self,
        recipe_yaml: str,
        env: dict[str, str],
        screenshot_prefix: str | None,
    ) -> RunResult: ...
    def save_snapshot(self, name: str) -> SnapshotResult: ...
    def load_snapshot(self, name: str) -> SnapshotResult: ...
    def capture_ui_dump(self) -> str: ...
```

### `ensure_running`
1. `ec2.describe_instances` to read state.
2. If `stopped` → `start_instances`, then poll `describe_instance_status`
   until `Status.Status == 'ok'` (waits for SSM agent ready). Hard timeout
   180 s; on timeout, raise `EmulatorBootTimeout`.
3. Verify the in-VM emulator is up by sending a probe SSM command:
   `adb wait-for-device && adb shell getprop sys.boot_completed`. Retry
   every 5 s for up to 120 s.
4. Return `{instance_id, state: "running", public_dns, started_at}`.

### `run_recipe`
1. Acquire singleton lock (see below).
2. Bump in-VM idle marker via SSM (`touch /var/run/ace-mobile/last-activity`).
3. Write `recipe_yaml` to a temp file on the instance via SSM
   (`echo "<base64>" | base64 -d > /tmp/recipe-<uuid>.yaml`). The yaml is
   passed inside the SSM command document; we base64 it to avoid shell
   quoting hell. SSM document size limit is 100 KB — well above any
   plausible recipe.
4. Compute artifact prefix: `screenshots/<prefix or run-uuid>/`.
5. Run `maestro test --format junit --output /tmp/run-<uuid>/ /tmp/recipe-<uuid>.yaml`
   via SSM, with `env` passed as `--env KEY=VALUE` flags. Capture
   stdout/stderr/exit_code.
6. Run `aws s3 cp /tmp/run-<uuid>/ s3://<bucket>/<prefix>/ --recursive`
   on the instance (its instance role has PutObject scoped to that
   bucket).
7. List S3 objects under the prefix from ace-web; for each, generate a
   1-hour presigned URL.
8. Return artifacts list. **`finally` block always bumps the idle marker
   one more time** (so a long upload doesn't trip the 5 min idle
   shutdown mid-finalization) and releases the singleton lock.

### Singleton lock (`apps/mobile/singleton.py`)
- Redis key: `mobile:emulator:lock`, value: `{ace-task-id}:{request-uuid}`,
  TTL: 30 min.
- `try_acquire()` uses `SET NX EX 1800`. Returns `(acquired, owner)`.
- `release()` uses Lua CAS so we only release a key we own.
- 503 on contention; the response includes the current owner string for
  debugging. (No queue; spec is explicit on this.)
- Pattern lifted from `apps/common/nova_auth_flow.py`'s `nova:refresh-lock`.
- Sync wrapper because DRF views are sync; uses the sync `redis` package
  rather than `redis.asyncio`. (`redis` is a transitive dependency of
  channels-redis already.)

### SSM transport (`apps/mobile/ssm.py`)
- `run_command(instance_id, *, commands: list[str], timeout_seconds: int) -> CommandResult`
- Uses `AWS-RunShellScript` document.
- Polls `get_command_invocation` every 1 s until `Status` is terminal.
- Returns `{stdout, stderr, exit_code, status}`.
- Raises `SSMTimeout` if the command exceeds `timeout_seconds`.
- One retry on `ThrottlingException` with 2 s backoff. Otherwise no
  retry — SSM failures should surface to the caller.

## Settings (`config/settings/base.py`)

Add a small block:

```python
ACE_MOBILE_AWS_REGION = env("ACE_MOBILE_AWS_REGION", default="us-east-1")
ACE_MOBILE_INSTANCE_ID = env("ACE_MOBILE_INSTANCE_ID", default="")
ACE_MOBILE_S3_BUCKET = env("ACE_MOBILE_S3_BUCKET", default="")
ACE_MOBILE_AMI_VERSION = env("ACE_MOBILE_AMI_VERSION", default="")  # surfaced in /status
```

The endpoints check `ACE_MOBILE_INSTANCE_ID` is non-empty and 503 with a
clear error otherwise (so a deploy without the env vars set fails loudly,
not mysteriously). Values land in `deploy/aws/task-definition.json` after
Terraform apply emits them.

## Terraform (`infra/mobile/`)

```
infra/mobile/
├── README.md                # one-time apply runbook
├── main.tf                  # provider + locals
├── variables.tf             # region, ami_id, key_name (none — SSM), tags
├── ec2.tf                   # launch template + lone instance
├── iam.tf                   # 2 roles: instance role, ace-web task add-on
├── s3.tf                    # artifacts bucket + lifecycle (delete > 7d)
├── cloudwatch.tf            # idle alarm + stop action
├── outputs.tf               # instance_id, bucket, ami_version
└── .terraform-version
```

Resources:

1. **EC2 launch template + instance**
   - `instance_type = "m8i.xlarge"`
   - `instance_initiated_shutdown_behavior = "stop"` (so in-VM `shutdown -h`
     stops, doesn't terminate)
   - `cpu_options.amd_sev_snp = "disabled"`; nested virt is on by default
     for m8i bare-metal-style hypervisor — confirm in apply
   - `ebs_block_device { volume_size = 30, volume_type = "gp3" }`
   - `iam_instance_profile = aws_iam_instance_profile.mobile.name`
   - No SSH key pair, no inbound SG rules — SSM only.
   - Outbound 443 only (so SSM agent can reach `ssm.<region>.amazonaws.com`
     and S3).
   - Tags: `auto-stop = "true"`, `owner = "ace-web-mobile-poc"`,
     `Name = "ace-mobile-emulator"`.
   - Initial state: `stopped` (we set `desired_state = "stopped"` via a
     `null_resource` + AWS CLI lifecycle hook, since Terraform doesn't
     have a native "create-then-stop" idiom for ec2_instance).

2. **S3 bucket** `ace-mobile-artifacts-${var.env_suffix}`
   - Versioning off
   - SSE-S3 default encryption
   - Lifecycle: delete objects > 7 days
   - Block public access
   - Policy: read by `ace-web-task-role`, write by `mobile-instance-role`

3. **IAM**
   - `mobile-instance-role` (attached to EC2): `AmazonSSMManagedInstanceCore`
     + inline `s3:PutObject` scoped to the artifacts bucket
   - Add-on policy attached to the existing ace-web ECS task role:
     - `ec2:Start*`, `ec2:Stop*`, `ec2:DescribeInstances`,
       `ec2:DescribeInstanceStatus` scoped to instances tagged
       `owner=ace-web-mobile-poc`
     - `ssm:SendCommand`, `ssm:GetCommandInvocation` scoped to the same
     - `s3:ListBucket`, `s3:GetObject` on the artifacts bucket
   - The add-on policy is referenced by ARN in `deploy/aws/task-definition.json`
     (a manual edit, captured in the README runbook).

4. **CloudWatch alarm**
   - `CPUUtilization < 5%` for 5 min (`Statistic=Maximum`,
     `EvaluationPeriods=5`, `Period=60`). Tightened from 30 min on
     2026-05-09 — the safety net should be aggressive so a bug in
     layers 1/2 can't quietly leak EC2 charges.
   - Action: `arn:aws:automate:${region}:ec2:stop`.
   - Dimension: `InstanceId = aws_instance.mobile.id`.

The README documents the `terraform apply` runbook and notes that the
ace-web task definition needs the add-on policy ARN appended (one-line
edit in `deploy/aws/task-definition.json`, then `aws ecs
update-service`). I'll write the README; you run apply.

## Packer (`infra/mobile-ami/`)

```
infra/mobile-ami/
├── README.md                    # bake runbook (single `packer build`)
├── ace-mobile.pkr.hcl           # Packer template
├── scripts/
│   ├── 00-base.sh               # apt update, kvm packages
│   ├── 10-android-sdk.sh        # OpenJDK 17, cmdline-tools, system-image
│   ├── 20-avd.sh                # create ACE_Pixel_API_34, patch hw.camera.front=emulated
│   ├── 30-maestro.sh            # install Maestro 2.5.x → /opt/maestro
│   ├── 40-commcare-apk.sh       # download CommCare 2.62.0 APK → /opt/ace/apks/
│   ├── 50-bake-snapshot.sh      # boot AVD, run register-to-otp + register-from-otp via +7426 demo, save snapshot
│   └── 60-systemd.sh            # ace-mobile-runner.service + idle watchdog
└── files/
    ├── ace-mobile-runner.service
    ├── idle-shutdown.sh         # /usr/local/bin/ace-idle-shutdown
    └── recipes/
        ├── connect-register-to-otp.yaml      # copied from ../ace/mcp/mobile/recipes/static/
        └── connect-register-from-otp.yaml    # copied from ../ace/mcp/mobile/recipes/static/
```

Packer builder: `amazon-ebs`, source AMI `ami-*-ubuntu-noble-24.04-amd64-server-*`,
instance type `m8i.xlarge` (KVM packages only install if /dev/kvm is present
during bake), output AMI tagged `ace-mobile-emulator-vN`.

### Snapshot bake is fully automated (no human-in-the-loop)

ACE registers a `+7426`-prefixed demo phone in CommCare. Connect-id's
`TEST_NUMBER_PREFIX = "+7426"` short-circuits SMS delivery — the app shows
the snackbar "I see you're a demo user, so we'll skip the OTP" and advances
straight to App Lock. So the `registered-test-user` snapshot bakes inside
Packer as a normal provisioner step:

`50-bake-snapshot.sh`:
1. Disable GMS (`adb shell pm disable-user --user 0 com.google.android.gms`)
   so face-capture lands in `ManualMode`. Re-enable post-bake if the runtime
   needs it; the `client.ts` toggle pattern documents this.
2. Grant CAMERA permission to `org.commcare.dalvik`.
3. Boot the AVD headless: `emulator -avd ACE_Pixel_API_34 -no-window -gpu swiftshader_indirect -no-snapshot-save &` and wait for `sys.boot_completed`.
4. `adb install -r /opt/ace/apks/commcare.apk`.
5. `maestro test connect-register-to-otp.yaml --env COUNTRY_CODE=... --env PHONE_LOCAL=...` — phone is a `+7426*` Packer var.
6. `maestro test connect-register-from-otp.yaml --env NAME=... --env BACKUP_CODE=... --env PIN=...`.
7. `adb emu avd snapshot save registered-test-user`.
8. `adb emu kill`.

Packer vars (`var.test_phone_local`, `var.test_backup_code`, `var.test_pin`,
`var.test_country_code`, `var.test_name`) are populated from the `packer build`
operator's environment; the README pulls them from 1Password (`op://ACE/mobile-ami-bake/...`).
Nothing about the bake requires SSM-into-the-baking-instance or interactive
input.

**Pre-flight:** the demo phone must be pre-invited to a Connect opportunity
(otherwise `start_configuration` crashes — Sentry CI-643). The bake script
checks for this by hitting Connect's invite-status endpoint before touching
the emulator and aborts with a clear error if missing. README documents the
"invite the demo phone to opp `ACE-mobile-poc`" one-time setup step.

`60-systemd.sh` installs a systemd unit `ace-mobile-runner.service` that
launches the emulator with
`-no-window -gpu swiftshader_indirect -no-snapshot-save -snapshot registered-test-user`,
plus a separate `ace-idle-shutdown.timer` that fires every minute and
runs `ace-idle-shutdown.sh`:

```sh
#!/bin/bash
set -euo pipefail
last=$(stat -c %Y /var/run/ace-mobile/last-activity 2>/dev/null || echo 0)
now=$(date +%s)
if (( now - last >= 600 )); then
  /usr/bin/sudo /sbin/shutdown -h now
fi
```

AMI rebuild cadence: "when CommCare APK rev'd, test phone rotated, or
ConnectID session expires server-side." Single `packer build`, ~20 min
end-to-end.

## Auto-stop verification (success bar #4)

Built into the test plan, not just the runtime:
- Layer 1: `tests/test_controller.py::test_run_recipe_finally_releases_lock`
  uses an injected exception in the SSM stub.
- Layer 2: covered in the AMI README — bake-time test that
  `ace-idle-shutdown.timer` fires (manual, since systemd timers don't
  run in Packer build).
- Layer 3: Terraform `cloudwatch.tf` declarative; `infra/mobile/README.md`
  includes the post-apply `aws cloudwatch describe-alarms` check.

For the spec's "kill ace-web mid-run, verify stop within 10 min" bar:
documented as a manual smoke step in `infra/mobile/README.md § Smoke
test`.

## Test surface

`apps/mobile/tests/`:
- `test_views.py` — auth (no token → 401, bad token → 401, valid token →
  envelope), serializer validation (recipe_yaml empty → 400), happy paths
  with controller mocked.
- `test_controller.py` — boto3 calls verified via `botocore.stub.Stubber`.
  Lifecycle: stopped → ensure_running starts; running → ensure_running
  no-ops; run_recipe finally always releases lock; SSM timeout → `503`
  not `500`.
- `test_singleton.py` — fakeredis. Lock acquisition; CAS release;
  contention returns owner string; TTL set correctly.

Target: ~25 tests, all sync, fast (< 5 s suite).

## Out of scope (from spec, restated)

- MCP `CLOUD` backend in the ACE repo.
- Concurrency / queue / N-instance pool.
- ARM64 / Graviton.
- iOS.
- Multi-tenant scoping of `/api/mobile/*` (it's global, behind PAT).
- Drive upload from ace-web.

## Order of execution

Three independent landings, parallelizable after step 1:

1. **App skeleton + auth** (~30 min): `apps/mobile/` boilerplate, settings,
   urls, one no-op endpoint passing auth tests. Gates everything else.
2. **EmulatorController + endpoints** (~3 h): controller class, 8 views,
   tests with stubbed boto3. No real AWS dependency.
3. **Terraform + Packer + README runbooks** (~2 h): infra code only;
   you run `terraform apply` and `packer build` separately.

Steps 2 and 3 can be parallelized via subagents.

## Success criteria (re-stated for ace-web side)

1. `pytest apps/mobile/` green.
2. `ruff check apps/mobile/ infra/` clean.
3. `terraform validate` and `packer validate` pass.
4. README runbooks let you go zero → instance booted → curl
   `/api/mobile/ensure-running` → see EC2 start, without re-reading the
   plan.
5. Killing ace-web mid-run leaves the instance, but layer 2 or 3 stops
   it within 10 min (manual smoke documented).
