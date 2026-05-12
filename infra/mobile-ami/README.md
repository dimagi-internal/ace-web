# `infra/mobile-ami/` — AMI bake for the ACE mobile cloud runner

A single `packer build` produces an Ubuntu-24.04 AMI with:

- KVM + the Android SDK + emulator + API 34 google_apis x86_64 system image.
- An `ACE_Pixel_API_34` AVD pre-patched for emulated camera (so face
  capture lands in `ManualMode` once GMS is disabled at runtime).
- Maestro CLI under `/opt/maestro`.
- CommCare 2.62.0 APK at `/opt/ace/apks/commcare.apk` with an md5 sidecar.
- A baked-in `registered-test-user` AVD snapshot — the demo phone is
  already registered with ConnectID, App Lock is configured with the
  bake-time PIN, and the home screen is the next thing you see when the
  emulator boots from this snapshot.
- A `ace-mobile-runner.service` systemd unit that auto-starts the
  emulator from the snapshot on instance boot.
- A `ace-idle-shutdown.timer` that halts the instance after 5 minutes
  of inactivity (layer 2 in the three-layer auto-stop story).

The AMI is consumed by the `ace-mobile-emulator-labs` launch template in
AWS. Use `./rebake.sh` (in this directory) to bake + roll the new AMI
into the running EC2 instance in one step — see the Rebake runbook below.

> **Note on the `infra/mobile/` Terraform stack:** the .tf files in
> the sibling directory created the original resources (launch template,
> EC2 instance, IAM, S3 bucket, CloudWatch) but the state file has never
> been on a shared backend and is functionally lost. Day-to-day rolls
> are AWS-CLI-direct via `rebake.sh`. If you ever need to recreate the
> stack, `terraform import` the existing resources first; don't apply
> from an empty state.

---

## Prerequisites

- Packer `>= 1.10` with the `amazon` plugin (`packer plugins install
  github.com/hashicorp/amazon` once).
- AWS credentials with permission to launch an EC2 instance, build
  images, and create AMIs in the target region. The bake instance is
  the same `m8i.xlarge` shape the runtime uses.
- 1Password CLI (`op`) signed in. The bake-time test creds (demo phone,
  PIN, backup code, display name) live at `op://ACE/mobile-ami-bake/`.
- **Pre-flight: invite the demo phone to a Connect opportunity.** This is
  a one-time manual step. The first registration will hard-fail without
  it (Connect-id's `start_configuration` crashes — Sentry CI-643).
  In the Connect web UI, add the bake-time `+7426...` phone number to a
  test opportunity (suggestion: `ACE-mobile-poc`). The bake script does
  NOT probe for this — if it's missing, you'll see the registration
  recipe stall on a CommCare crash dialog and the bake will fail at the
  `extendedWaitUntil` for the App Lock screen.

---

## Rebake + roll runbook

One command — bake the AMI, update the launch template, terminate the
old EC2 instance, launch a new one, update task-def, open + merge the
PR, and trigger the ace-web deploy:

```bash
AWS_PROFILE=labs ./rebake.sh
```

That's the supported path. The script lives at `infra/mobile-ami/rebake.sh`
and is the single source of truth for how a roll happens. See the
header docstring for flags (`--skip-bake AMI` to retry a partial run,
`--dry-run` to preview).

### What if I just want to bake without rolling?

Useful for testing the bake itself before committing to the roll. The
script can't be partially-stopped, but a raw `packer build` works:

```bash
cd infra/mobile-ami
packer init .
packer validate .
packer build .
```

(The test-user credentials the older runbook referenced were removed
when bake moved to cold-boot-register-on-launch in May 2026; 1Password
is no longer required for the bake. Runtime creds live in AWS Secrets
Manager as `ace-mobile-test-user-creds`.)

The bake takes ~35 minutes end-to-end on `c5n.metal`. The slow steps are:

1. `apt-get install` (~3 min for KVM + JDK).
2. `sdkmanager` system-image download (~6 min — ~1.2 GB image).
3. Snapshot bake (~6 min — emulator cold boot, APK install, two recipes,
   snapshot save).

When it's done, Packer prints the new AMI ID:

```
==> Builds finished. The artifacts of successful builds are:
--> ace-mobile.amazon-ebs.ace_mobile: AMIs were created:
us-east-1: ami-0abcdef1234567890
```

If you ran `./rebake.sh` (the recommended path), it's already parsed
the AMI ID + name and updated `deploy/aws/task-definition.json` for you.
If you ran `packer build .` directly, you'll need to feed the AMI ID
into `rebake.sh --skip-bake ami-0abcdef1234567890` to handle the rest
of the roll.

---

## What the bake actually does

1. **`scripts/00-base.sh`** — `apt-get install` for `qemu-kvm`,
   `libvirt-daemon-system`, `openjdk-17-jdk-headless`, and basic utils.
   Verifies `kvm-ok` succeeds.
2. **`scripts/10-android-sdk.sh`** — downloads cmdline-tools, accepts
   licenses, installs `platform-tools`, `emulator`, `platforms;android-34`,
   and the `system-images;android-34;google_apis;x86_64` system image.
3. **`scripts/20-avd.sh`** — creates `ACE_Pixel_API_34` from the Pixel 7
   profile, then patches `config.ini` to set `hw.camera.front=emulated`,
   `hw.ramSize=4096`, `disk.dataPartition.size=6G`,
   `hw.gpu.mode=swiftshader_indirect`.
4. **`scripts/30-maestro.sh`** — installs Maestro CLI 1.39.0 to
   `/opt/maestro` and symlinks `/usr/local/bin/maestro`.
5. **`scripts/40-commcare-apk.sh`** — downloads CommCare 2.62.0,
   records the md5 sidecar, writes `/opt/ace/MANIFEST.txt`.
6. **`scripts/50-bake-snapshot.sh`** — boots the AVD headless, disables
   GMS (`pm disable-user --user 0 com.google.android.gms`), grants
   CAMERA, installs the APK, runs the two registration recipes via the
   `+7426` demo-bypass flow (no human OTP entry — Connect-id
   short-circuits SMS for that prefix), saves
   `registered-test-user` snapshot, kills the emulator.
7. **`scripts/60-systemd.sh`** — installs `ace-mobile-runner.service`
   + the `ace-idle-shutdown.{service,timer}` pair, enables them.

---

## Maestro recipes (vendored)

`files/recipes/connect-register-1-phone-entry.yaml` and
`files/recipes/connect-register-2-app-lock.yaml` are **verbatim copies**
from the canonical source in the ACE plugin:

```
../ace/mcp/mobile/recipes/static/connect-register-1-phone-entry.yaml
../ace/mcp/mobile/recipes/static/connect-register-2-app-lock.yaml
```

Don't edit the local copies. When CommCare's UI changes (typical pattern:
selectors stop matching after a CommCare release), update the recipes in
the ACE plugin first, verify on a laptop AVD via
`mobile_register_test_user`, then refresh the copies here:

```bash
cp ../../../ace/mcp/mobile/recipes/static/connect-register-1-phone-entry.yaml   files/recipes/
cp ../../../ace/mcp/mobile/recipes/static/connect-register-2-app-lock.yaml files/recipes/
```

(Adjust the relative path to wherever the `ace` repo lives in your worktree.)

---

## When to re-bake

| Trigger | Re-bake? |
|---|---|
| CommCare APK rev (e.g., 2.62.0 → 2.63.0) | yes — selectors may drift |
| Maestro CLI rev | optional — pin version in `30-maestro.sh` to lock |
| Demo phone rotated | yes — snapshot has the old phone's account |
| Demo phone's ConnectID server-side session expires | yes |
| Android system image security patch | quarterly cadence is fine |
| Recipe changes in the ACE plugin (selector fixes etc.) | yes |

Run `AWS_PROFILE=labs ./rebake.sh` to bake and roll. The script:

1. Bakes the new AMI (~35 min).
2. Adds it as a new launch-template version and marks that the default.
3. Terminates the current EC2 instance and launches a fresh one from
   the LT — EC2 AMIs are pinned at launch time, so a stop/start
   wouldn't pick up the new image. (An earlier version of this README
   said stop/start did the job — that was incorrect; it's `terminate
   + run-instances` or nothing.)
4. Stops the new instance (ace-web starts it on demand).
5. Updates `deploy/aws/task-definition.json` with the new instance ID
   + AMI version, opens + merges the PR, triggers the deploy workflow.

---

## Troubleshooting

**`kvm-ok` fails on the bake instance.** The current instance type doesn't
expose nested virt. Try `c8i.xlarge` (cheaper) or `m7i.metal-24xl` (bare
metal, ~10× cost). Update `instance_type` in `variables.pkr.hcl`'s
default and re-run.

**Recipe stalls on the App Lock screen during step 50.** Demo phone
isn't pre-invited to a Connect opportunity (see Pre-flight above). Look
at `/var/log/ace-mobile/bake-emulator.log` on the bake instance via SSM
or attach a debugger by stopping the bake before snapshot and SSM-ing
in.

**Snapshot save reports "no snapshot to save" despite earlier success.**
Usually means `adb` lost the device mid-recipe. Check that
`adb wait-for-device` returned at the start of the bake (script logs go
to the Packer stdout). If KVM regressed, snapshot save can take
minutes — extend the per-step timeout if needed.

**Validate without running the build.** Stub the test creds. Pass `.`
(not the .hcl file) so Packer pulls in `variables.pkr.hcl` automatically:
```bash
packer validate \
  -var test_phone_local=12340000 \
  -var test_country_code=+74260 \
  -var test_pin=1234 \
  -var test_backup_code=000000 \
  -var test_name=test \
  .
```
