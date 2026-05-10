# Phase 5 ↔ Cloud Mobile Runner: Integration Design

**Date:** 2026-05-10
**Status:** Draft (to be confirmed against the e2e test results)
**Owners:** Jon (ACE plugin); ace-web (this repo) for the runner
**Related:**
  - ace-web spec — `docs/specs/2026-05-04-opp-summary-page-design.md` for opp-side artifact paths
  - ACE plugin — `agents/qa-and-training.md`, `skills/app-screenshot-capture/SKILL.md`, `skills/connect-baseline-screenshots/SKILL.md`
  - Cross-repo cloud-runner spec — written 2026-05-09 in `ace/docs/superpowers/specs/2026-05-09-mobile-cloud-runner-poc.md`
  - Operator runbook — `infra/mobile/README.md`, `infra/mobile-ami/README.md`
  - Bake learning — `docs/learnings/cloud-emulator-snapshot-persistence.md`

This is the load-bearing integration spec for Phase 5 of an ACE opportunity
(`qa-and-training`) using ace-web's cloud Android emulator. It replaces
the implicit assumption that `mobile_*` atoms drive the operator's
laptop AVD; on cloud, those atoms talk to ace-web's HTTP API which
drives a singleton EC2 emulator behind it.

The cloud runner doesn't change *what* Phase 5 produces — it only
changes *where* the AVD lives and how state is selected. The
artifact tree under `ACE/<opp>/runs/<run-id>/5-qa-and-training/` is
identical whether the AVD ran on a laptop or in EC2.

## Why Phase 5 wants this

Three problems the local AVD has that the cloud runner solves:

1. **Multi-operator collisions.** Two engineers running Phase 5 on the
   same Mac fight over `adb` ports + AVD config. The cloud runner has
   one canonical AVD per ace-web tenant; ace-web's singleton lock
   serializes recipe runs cleanly with a 503 contention error.
2. **Linux/Windows ACE users have untested host paths.** The local-AVD
   stack assumes macOS conventions (`~/.android/avd`, `JAVA_HOME` resolution
   via `/usr/libexec/java_home`, etc.). Cloud routes those paths to
   the AMI which is Ubuntu-only.
3. **ace-web background jobs have no AVD at all.** Scheduled deep QA
   reruns, scheduled training-prep refreshes, evaluation harnesses —
   none of these can drive a mobile flow today. With the cloud runner,
   any ECS task that holds an `ACE_WEB_PAT_TOKEN` can.

## What the cloud runner provides

`/api/mobile/*` endpoints (Bearer auth via `ACE_WEB_PAT_TOKEN`,
sub-second response except for `ensure-running` and `run-recipe`):

| Path | Purpose | When Phase 5 hits it |
|---|---|---|
| `GET /api/mobile/status` | Configured / instance state / AMI version | Pre-flight (Step 0 of any Phase 5 dispatch) |
| `GET /api/mobile/states` | Catalog of named CommCare states baked into the AMI | Pre-flight, to pick the matching state for the opp's `commcare_app_version` |
| `POST /api/mobile/ensure-running` | Start the EC2 instance, load the requested state's snapshot, wait for `sys.boot_completed` | Once at the start of each phase-5 run; subsequent atoms are no-ops on this |
| `POST /api/mobile/install-apk` | Override the snapshot's CommCare with a different APK at runtime (typically only for opp-specific CommCare builds) | Optional — see "Per-opp APK installs" below |
| `POST /api/mobile/run-recipe` | Maestro `test` against the running AVD; returns presigned URLs to artifacts | Once per smoke recipe (per app — Learn, Deliver) |
| `POST /api/mobile/capture-ui-dump` | `adb shell uiautomator dump` | Selector discovery during recipe authoring; not Phase-5 hot path |
| `POST /api/mobile/save-snapshot` / `/load-snapshot` | Runtime checkpoint / restore | Reserved for future "save my registered state mid-flow" workflows |
| `POST /api/mobile/select-state` | Switch the loaded snapshot without going through ensure-running | When an upstream phase pinned a different CommCare version than the runner's default |
| `POST /api/mobile/stop` | Force-stop the EC2 instance | End of phase 5; idle watchdog covers the unhappy path |

ace-web doesn't know about Drive. Recipe YAML is POSTed inline,
artifacts come back as 1-hour-TTL S3 presigned URLs which the *caller*
downloads + uploads to Drive. This keeps Drive auth in the plugin and
preserves the same "ace-web is identity-light" property as the rest of
its surfaces.

Three independent auto-stop layers, all 5-min thresholds. Worst-case
overnight leak ~$0.04 if all three fire late.

## Routing knob: `ACE_MOBILE_BACKEND`

The plugin's `mcp/mobile/capability-map.ts` already routes by backend
type. The CLOUD backend lands in PR #197 (`mcp/mobile/backends/cloud.ts`).
At dispatch time:

- `ACE_MOBILE_BACKEND=cloud` → CloudBackend (talks to ace-web HTTP)
- unset / anything else → AvdBackend + MaestroBackend (existing local
  emulator path)

Skills don't see this knob. The Phase 5 agent can pass it down via the
spawn env if Phase 5 should use cloud; otherwise individual skills
inherit it from `/ace:run`'s shell env. Default in the field for now:
`AVD` (local) is the baseline; `CLOUD` is opt-in until we have
confidence at scale.

`ace-web` for its own background jobs always uses CLOUD (the only
backend it can — no local AVD available).

## Per-opp content layering, restated for cloud

Phase 5 produces two artifact families, both end up under
`ACE/<opp>/runs/<run-id>/5-qa-and-training/`. Cloud runner doesn't
change the per-opp Drive layout; it changes where the screenshots are
captured.

### Per-opp screenshots

`app-screenshot-capture` skill drives this. Reads
`2-commcare/app-test-cases.yaml` (Phase 2 output) for the smoke
recipe set, then for each `is_smoke: true` journey:

1. `mobile_ensure_avd_running({ avd: "cc-<commcare_version>" })` —
   the avd-name parameter on cloud is the requested baked state.
2. `mobile_run_recipe({ recipe_path, env: { OPP_NAME, HQ_DOMAIN, ACE_E2E_PHONE_LOCAL, ACE_E2E_COUNTRY_CODE, ... }, screenshot_dir })`.
3. CloudBackend reads the recipe from `recipe_path`, POSTs the YAML
   string + env to `/api/mobile/run-recipe`, downloads presigned
   screenshots into `screenshot_dir`.
4. Skill uploads `screenshot_dir/*.png` to Drive at
   `5-qa-and-training/screenshots/<journey-id>/<step-name>.png` with
   anyone-with-link permission for Slides ingest.

### Common Connect baseline screenshots

`connect-baseline-screenshots` (NOT a Phase 5 dispatch — manual when
the Connect APK ships an update). Same flow but writes to
`ACE/_common/connect-screenshots/<connect-version>/`.

The cloud runner makes this skill cheap: it can run completely
unattended by ace-web on a schedule whenever a new Connect APK
release is detected.

## State selection

The AMI bakes one snapshot per CommCare APK version listed in
`infra/mobile-ami/variables.pkr.hcl::commcare_versions`. Each snapshot
is `cc-<version>-registered` and pre-loads the +7426 demo phone in the
"registered, App-Lock-screen-pending" state.

Phase 5's `app-screenshot-capture` matches the opp's
`commcare_app_version` (read from Phase 2's `app-deploy_summary.md`)
to a baked state:

- Exact match (e.g., `2.62.0` → `cc-2.62.0`): use `ensure_running` with
  that state name. ~30 s cold start.
- No match: install via `install-apk` from S3 (skill uploads the APK
  first via the `/api/mobile/upload-url` presign helper). The runner
  AMI's snapshot still loads (so demo user state is preserved), then
  `adb install -r` overlays the requested APK.
- The `cc-` state is recorded in the screenshot manifest so consumers
  (training-deck-outline, app-ux-eval) can re-render against the same
  state if needed.

When a CommCare release ships, the AMI rebake adds the new version to
the catalog. Today: `commcare_versions = ["2.62.0"]`. Bumping is a
one-line edit + `packer build` (~25 min).

## Phase 5 dispatch flow on cloud

```
qa-and-training agent
│
├─ Step 0  Pre-flight checks
│  ├─ GET /api/mobile/status  → { configured: true, ami_version, ... }
│  ├─ GET /api/mobile/states  → pick state matching commcare_app_version
│  └─ Read app-test-cases.yaml from Drive; filter is_smoke: true
│
├─ Step 1  Boot
│  └─ POST /api/mobile/ensure-running { state: "cc-2.62.0" }
│       returns { instance_id, state, public_dns, started_at }
│       Wait time: ~30 s warm (snapshot loaded), ~90 s cold (instance off)
│
├─ Step 2  app-screenshot-capture (for app=learn smoke)
│  └─ POST /api/mobile/run-recipe { recipe_yaml, env, screenshot_prefix: "learn-smoke" }
│       returns { exit_code, stdout, stderr, artifacts: [{name, presigned_url}] }
│       Skill downloads each artifact, uploads to Drive at
│       5-qa-and-training/screenshots/learn-smoke/<step>.png
│       Wall clock: ~2-4 min per recipe
│
├─ Step 3  app-screenshot-capture (for app=deliver smoke)
│  └─ Repeats step 2 for the deliver app's smoke recipe
│
├─ Step 4  training-* skills
│  └─ Read screenshots from Drive (no mobile dispatch)
│
└─ Step 5  Stop (best-effort)
   └─ POST /api/mobile/stop  → { stopped_at }
        If skill crashes between Steps 2-4: in-VM idle watchdog stops
        the instance after 5 min idle. CloudWatch alarm is the third
        backstop after 5 min CPU<5%.
```

## Failure modes & retries

The skill layer (Phase 5's `app-screenshot-capture`) handles three
classes:

1. **Configuration errors** (`code: not-configured` from /status): halt
   with a clear error pointing at `infra/mobile/` Terraform state and
   the deploy task-def's `ACE_MOBILE_*` env vars.
2. **Singleton contention** (`code: singleton-busy`, 503): another
   caller holds the lock. Retry once after 30 s. If still busy, halt
   and report `current_owner` so the operator can investigate.
3. **Recipe failures** (`exit_code != 0` from /run-recipe): the
   skill's existing UX-judge logic already handles per-step screenshots
   captured at point-of-failure. No new retry needed; the skill's
   existing "halt with structured PLATFORM auto-surfaced verdict" path
   covers it.

Boot timeouts (`code: boot-timeout`) are mapped to `AvdBootError` by
CloudBackend so existing skill error handling for the local AVD
applies. The skill doesn't care which backend produced it.

## Concurrency

Singleton EC2 + singleton lock means **one Phase 5 run at a time per
ace-web tenant**. For the POC this is right (we'd rather know we're
queued than have unpredictable contention). When demand exceeds it:

- v2: small instance pool with a queue. The lock key becomes
  `mobile:emulator:lock:{instance_id}`. Phase 5 doesn't change.
- v3: per-opp dedicated instances. Phase 5 gains a `tenant` parameter
  on `/api/mobile/ensure-running`. Skills don't change beyond that.

## Cost model (Phase 5)

Per Phase 5 run on cloud, with the current AMI/instance shape:

| Component | Time | Cost |
|---|---|---|
| `ensure_running` cold start | ~90 s | $0.005 |
| `ensure_running` warm | ~30 s | $0.002 |
| One smoke recipe execution | ~3 min | $0.010 |
| Two smoke recipes (Learn + Deliver) | ~6 min | $0.020 |
| S3 storage (screenshots, 7-day TTL) | — | <$0.001 |
| **Total per Phase 5 run** | **~10 min wall** | **~$0.03** |

Idle = $0 (instance auto-stopped). Storage tail = ~$0.10/mo.

At ~50 phase-5 runs/month (10× weekly opp-eval cycles + ad-hoc reruns):
$1.50/mo plus $0.10 storage. Well under the $5/mo target.

AMI rebakes (~$1.62 each on c5n.metal) happen on CommCare APK
releases, ~6× per year. ~$10/year amortized.

## Operator runbook (Phase 5 cloud-mode pre-flight)

Anyone running `/ace:run` on an opp that should use the cloud
emulator needs:

1. `ACE_WEB_BASE_URL=https://labs.connect.dimagi.com/ace`
2. `ACE_WEB_PAT_TOKEN=<minted via /ace:ace-web-pat-mint>`
3. `ACE_MOBILE_BACKEND=cloud`

These belong in `~/.config/ace/.env` (or the per-opp env override).
The `/ace:run` driver doesn't need to know — `mcp/mobile/client.ts`
checks the env at construction time.

When the cloud runner is offline (e.g., during an AMI rebuild or
labs-account incident), set `ACE_MOBILE_BACKEND=AVD` to fall back to
the local emulator. Skills don't change.

## Open questions for Phase 5

1. **APK upload helper.** The plugin's `app-deploy` skill produces an
   opp-specific CommCare build (CCZ + signed APK). For Phase 5
   screenshots to render that APK, we need ace-web to expose
   `/api/mobile/upload-url` returning a presigned PUT URL the
   plugin can curl into. Easy addition; out of scope for this doc but
   the hook is named.
2. **`commcare_app_version` carry-through.** Phase 2's
   `app-deploy_summary.md` already records the deployed APK version.
   Phase 5 just reads it and selects the matching state. No new
   contract; the change is the skill picking it up from there
   instead of assuming "whatever the AVD has".
3. **Retain screenshots beyond 7 days.** Today S3 lifecycle drops
   artifacts after 7 days. Phase 5 uploads to Drive immediately so the
   permanent record is in Drive — the S3 lifecycle is only the
   "transient hop" cache. Confirm this assumption holds for any future
   "ace-web shows screenshot history" feature; if so, lift the lifecycle
   to 30 days.
4. **opp-eval reads.** The `app-screenshot-capture_verdict-shallow.yaml`
   and `app-screenshot-capture_manifest.yaml` artifacts roll up into
   `opp-eval`. No change needed for cloud — those are written to Drive
   the same way, after the screenshots upload.
5. **Multi-state handoff.** If an opp's PDD requires testing against
   multiple CommCare APK versions in one run (rare), the skill calls
   `ensure_running({state: ...})` multiple times. Each switch is ~30 s.
   The cost model adds ~$0.002 per state switch.

## Out of scope for this doc

- The `connect-baseline-screenshots` standalone skill (one-time per
  Connect APK). Same cloud surface, but not part of `/ace:run`'s
  per-opp dispatch.
- Phase 6 (`synthetic-data-and-workflows`) — doesn't drive mobile.
- Phase 8 (`execution-management`) — its mobile UAT runs are operator-led
  on a real device, not the cloud emulator.
- ARM64 / Graviton AMI variant.
- Concurrent runs / pool scaling.
- iOS Simulator support.

## Live state (2026-05-10 overnight run)

**What works end-to-end on labs:**

- AMI `ami-09cd3fd07fde9d1dc` (`2026-05-10-1`) baked + deployed
- EC2 instance `i-0b8a94fe5cb5dc7d5` running, nested-virt enabled
- `/api/mobile/status` + `/api/mobile/states` return correct payloads
- The Phase 5 dispatch flow (above) is **plausible** — needs the deploy
  rollout of PR #281 to clear the dash-vs-bash bug for `ensure-running`
  to fully succeed end-to-end through the deployed API.

**Known issue: snapshot persistence still broken.** The `-no-snapshot-save`
fix attempted in the 2026-05-10-1 bake **did not** restore CommCare to
the snapshot. The baked `cc-2.62.0-registered/` directory contains only
the 11-byte `snapshot.pb` metadata; the data files (ram.bin, textures.bin,
disk delta) are still lost. Hypothesis A (the fix) was wrong.

The runtime self-heal in `ace-emulator-launch` continues to install
CommCare on every cold boot — verified working on the new AMI. So the
*system* is functional, but every cold start pays an extra ~10 s of
APK install time the first time and ~30 s for the recipe to find
fresh PersonalID state (since /data is also fresh).

**Next investigation directions (not done yet):**

- Compare snapshot save behavior with vs without `-wipe-data` at boot.
- Try `qemu-img commit` on the userdata-qemu.img.qcow2 overlay
  before `adb emu kill` to fold disk writes into the base image
  (would survive AMI capture without depending on the snapshot
  mechanism).
- Investigate whether the named-snapshot save writes to `/tmp/...`
  (which would be lost across the AMI-capture clean boot) rather
  than directly to the AVD dir.
- Try the snapshot save → kill → re-bake-as-AMI flow with explicit
  `qemu-img convert userdata-qemu.img.qcow2 userdata-qemu.img` to
  flatten before capture.

For Phase 5 today: **rely on self-heal**. A new "what's running" probe
in the runtime (not yet implemented) could make the cold-start latency
predictable: emit a phase event "self-heal: installing CommCare" so
the calling skill knows it's normal.

## Acceptance criteria (the "we trust this" bar)

A Phase 5 run on cloud is "trusted" when **all five** of these hold:

1. `ACE_MOBILE_BACKEND=cloud /ace:run --resume turmeric` reaches the
   end of Phase 5 with both Learn + Deliver smokes producing
   screenshots in Drive.
2. `app-screenshot-capture_verdict-shallow.yaml` shows a real per-step
   screenshot count > 0 for both apps (no "skipped" / "halted" output).
3. Cost telemetry: 10 consecutive Phase 5 cloud runs cost <$0.50 of
   EC2 + S3 (verify via Cost Explorer).
4. Kill the orchestrator mid-run (`SIGKILL` the parent Claude process).
   Cloud instance auto-stops within 10 min via in-VM watchdog (layer 2)
   or CloudWatch alarm (layer 3).
5. Switch state mid-run (multi-version test): two consecutive smoke
   recipes against `cc-2.62.0` then `cc-2.63.0` (once we have a
   2.63.0 bake). Both produce screenshots.

#1, #2, and #4 can run today on the labs deployment. #3 needs ~10
real Phase 5 runs to accumulate enough billing signal. #5 needs a
multi-version AMI rebake, which is a one-line var change + `packer
build`.
