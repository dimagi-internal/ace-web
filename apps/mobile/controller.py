"""EmulatorController — orchestrates the lone EC2 emulator instance.

ace-web has no Drive credentials of its own; the runtime path is:

    request → EmulatorController → boto3 (EC2 + SSM + S3) → instance

For ``run_recipe`` we acquire the cross-task singleton (in the *view*,
not here, so 503 surfaces fast) and use a Python ``try/finally`` to
guarantee the in-VM idle marker is bumped one last time (so a long
``aws s3 cp`` finalization can't trip the 10 min idle shutdown). The
``finally`` does **not** auto-stop the instance — that's the in-VM idle
layer's job.

Boto3 clients are lazy-built and cached per controller instance.
"""
from __future__ import annotations

import base64
import json
import shlex
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from . import ssm
from .exceptions import (
    EmulatorBootTimeout,
    EmulatorNotReady,
    MobileError,
    SSMFailure,
    SSMTimeout,
)

# How long to wait for the EC2 instance + SSM agent to come ready
# after a cold ``StartInstances`` call.
_BOOT_HARD_TIMEOUT_SEC = 180
# How long to wait for the in-VM Android emulator + cold-boot
# registration to complete. ``ace-emulator-launch`` writes
# ``/run/ace-mobile/ready`` once the +7426 demo registration recipes
# finish — that's the signal we wait for. Budget: AVD boot ~60-90s,
# adb install ~10s, two registration recipes ~60s, total ~3 min.
# 5-min ceiling gives headroom for transient slowness without masking
# real failures.
_EMULATOR_READY_TIMEOUT_SEC = 300
_EMULATOR_READY_MARKER = "/run/ace-mobile/ready"
# Per-call SSM timeouts. Tuned for the typical command class.
_SSM_PROBE_TIMEOUT_SEC = 30
_SSM_OP_TIMEOUT_SEC = 300
_SSM_RECIPE_TIMEOUT_SEC = 1800  # 30 min — Maestro flows can be long.
# Absolute paths to in-VM tools. SSM's /bin/sh (dash) doesn't source
# /etc/profile.d/android-sdk.sh so PATH-relative invocations of `adb`
# fail with "adb: not found". Use the symlink target the bake's
# 10-android-sdk.sh installs to.
_ADB = "/opt/android-sdk/platform-tools/adb"
_MAESTRO = "/usr/local/bin/maestro"
# In-VM idle marker — must agree with files/idle-shutdown.sh in the AMI.
_IDLE_MARKER_PATH = "/var/run/ace-mobile/last-activity"
# Catalog of states (one per CommCare APK version) baked into the AMI.
# Written by ``infra/mobile-ami/scripts/50-bake-snapshot.sh``.
_STATES_YAML_PATH = "/opt/ace/states.yaml"
# Active-state marker, written by ``ace-emulator-launch`` on each
# emulator launch. Used by /api/mobile/states to surface which state is
# currently running. Best-effort: if the file is missing, ``active``
# defaults to ``default``.
_ACTIVE_STATE_PATH = "/run/ace-mobile/active-state"
# S3 presigned URL TTL — 1 hour matches the spec contract.
_PRESIGN_TTL_SEC = 3600


# ── Result dataclasses ────────────────────────────────────────────────


@dataclass
class AdbDevice:
    serial: str  # e.g. "emulator-5554"
    state: str  # "device" | "offline" | "unauthorized" | "no permissions" | ...


@dataclass
class Diagnostics:
    """Live snapshot of the in-VM emulator runtime, collected in one
    SSM call. Returned from ``ensure_running`` (success and failure
    paths) and from ``GET /api/mobile/diagnose``. Read this first when
    a caller can talk to the EC2 instance but can't run recipes.

    All fields are best-effort. If an SSM probe fails, the request as a
    whole is reported (``ssm_ok=False``, ``ssm_error``) and the other
    fields stay at their defaults so callers can still inspect what
    was learned before the failure."""

    ssm_ok: bool = True
    ssm_error: str | None = None
    adb_devices: list[AdbDevice] = field(default_factory=list)
    emulator_pid: int | None = None
    emulator_cmdline: str | None = None
    runner_service_state: str | None = None  # "active" | "inactive" | "failed" | ...
    marker_present: bool = False
    marker_age_seconds: int | None = None
    runner_log_tail: str = ""
    emulator_log_tail: str = ""

    @property
    def adb_visible_count(self) -> int:
        """Count of adb devices in the canonical 'device' state."""
        return sum(1 for d in self.adb_devices if d.state == "device")


@dataclass
class RunningState:
    instance_id: str
    state: str
    public_dns: str | None
    started_at: str
    diagnostics: Diagnostics | None = None


@dataclass
class StoppedState:
    instance_id: str
    state: str
    stopped_at: str


@dataclass
class Status:
    instance_id: str | None
    state: str | None
    last_run_at: str | None
    idle_for_seconds: int | None
    ami_version: str | None


@dataclass
class InstallResult:
    package_name: str
    version: str


@dataclass
class Artifact:
    name: str
    presigned_url: str
    content_type: str


@dataclass
class Step:
    """One executed Maestro command, lifted from the commands-*.json
    report Maestro writes into the --debug-output directory.

    Fields are best-effort: Maestro's exact JSON shape varies by version,
    so missing fields surface as None rather than raising.
    """

    index: int
    name: str
    status: str  # 'pass' | 'fail' | 'skipped' | 'unknown'
    screenshot: str | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    artifacts: list[Artifact]
    steps: list[Step] = field(default_factory=list)


@dataclass
class SnapshotResult:
    name: str
    saved_at: str | None = None
    loaded_at: str | None = None


@dataclass
class State:
    """One named state baked into the AMI (1:1 with a CommCare APK version)."""

    name: str
    snapshot: str
    commcare_version: str
    description: str = ""


@dataclass
class StatesCatalog:
    default: str
    states: list[State]
    active: str | None = None  # which state's emulator is currently loaded


# ── Controller ────────────────────────────────────────────────────────


class EmulatorController:
    """Orchestrate the single emulator EC2 instance.

    All boto3 clients are lazily constructed and cached on the instance;
    use a fresh ``EmulatorController`` per request so client state can't
    leak across tenants if we ever multi-tenant this surface.
    """

    def __init__(self, *, instance_id: str, region: str, s3_bucket: str, ami_version: str = ""):
        self.instance_id = instance_id
        self.region = region
        self.s3_bucket = s3_bucket
        self.ami_version = ami_version
        self._ec2: Any = None
        self._ssm: Any = None
        self._s3: Any = None

    # ── Lazy clients ─────────────────────────────────────────────

    @property
    def ec2(self) -> Any:
        if self._ec2 is None:
            self._ec2 = boto3.client("ec2", region_name=self.region)
        return self._ec2

    @property
    def ssm(self) -> Any:
        if self._ssm is None:
            self._ssm = boto3.client("ssm", region_name=self.region)
        return self._ssm

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3

    # ── Lifecycle ───────────────────────────────────────────────

    def ensure_running(self, state_name: str | None = None) -> RunningState:
        """Ensure the EC2 instance is running and the emulator is booted.

        ``state_name`` selects which named state (CommCare version) to
        load. ``None`` keeps whatever's already active (or the AMI's
        default on a cold start). Switching to a different state on a
        running instance kills the current emulator and relaunches it
        with the requested snapshot — adds ~30-60 s.
        """
        info = self._describe_instance()
        ec2_state = info["state"]

        if ec2_state == "running":
            self._wait_for_emulator()
            if state_name and state_name != self._read_active_state():
                self._switch_state(state_name)
            diag = self._collect_diagnostics()
            if diag.adb_visible_count == 0:
                # Marker probe returned READY but adb sees nothing — the
                # canonical "stale marker, dead emulator" state we hit
                # whenever the runner unit exited (idle-shutdown of the
                # emulator process, or any other reason) while EC2 stayed
                # up. Recover in-place once and re-check; the recovery is
                # cheap enough (~2-3 min cold boot) that the
                # alternatives — manual operator intervention or "stop
                # the EC2 and let next call cold-start" — aren't worth
                # the friction.
                self._recover_emulator()
                diag = self._collect_diagnostics()
            self._assert_adb_visible(diag)
            return RunningState(
                instance_id=self.instance_id,
                state="running",
                public_dns=info.get("public_dns"),
                started_at=_iso_now(),
                diagnostics=diag,
            )

        if ec2_state in ("pending", "stopping"):
            # Caller raced us; treat it like a cold start.
            self._wait_for_ec2_ok(_BOOT_HARD_TIMEOUT_SEC)
        elif ec2_state == "stopped":
            self._start_instance()
            self._wait_for_ec2_ok(_BOOT_HARD_TIMEOUT_SEC)
        else:
            raise MobileError(
                f"instance {self.instance_id} is in unexpected state {ec2_state!r}"
            )

        self._wait_for_emulator()
        if state_name and state_name != self._read_active_state():
            self._switch_state(state_name)
        info = self._describe_instance()
        diag = self._collect_diagnostics()
        self._assert_adb_visible(diag)
        return RunningState(
            instance_id=self.instance_id,
            state=info["state"],
            public_dns=info.get("public_dns"),
            started_at=_iso_now(),
            diagnostics=diag,
        )

    def diagnose(self) -> Diagnostics:
        """Read-only snapshot of the in-VM emulator runtime.

        Unlike ``ensure_running``, this never mutates EC2 state and
        never raises on unhealthy emulator state — it just reports
        what's there. Returns a Diagnostics with ``ssm_ok=False`` if
        the EC2 instance isn't running (so the API caller can
        distinguish "no instance" from "instance there, emulator
        broken")."""
        info = self._describe_instance()
        if info["state"] != "running":
            return Diagnostics(
                ssm_ok=False,
                ssm_error=f"instance {self.instance_id} is {info['state']!r}; "
                "start it with /api/mobile/ensure-running before diagnosing",
            )
        return self._collect_diagnostics()

    def stop(self) -> StoppedState:
        try:
            self.ec2.stop_instances(InstanceIds=[self.instance_id])
        except ClientError as e:
            raise MobileError(f"ec2.stop_instances failed: {e}") from e
        return StoppedState(
            instance_id=self.instance_id,
            state="stopping",
            stopped_at=_iso_now(),
        )

    def status(self) -> Status:
        try:
            info = self._describe_instance()
            state = info["state"]
        except MobileError:
            state = None

        last_run_at = None
        idle_for = None
        if state == "running":
            try:
                # Read the idle marker mtime via SSM. Cheap (sub-second).
                result = ssm.run_command(
                    self.ssm,
                    self.instance_id,
                    commands=[
                        f"stat -c %Y {shlex.quote(_IDLE_MARKER_PATH)} 2>/dev/null || echo 0"
                    ],
                    timeout_seconds=_SSM_PROBE_TIMEOUT_SEC,
                )
                last_epoch = int((result.stdout or "0").strip() or "0")
                if last_epoch > 0:
                    last_run_at = datetime.fromtimestamp(
                        last_epoch, tz=UTC
                    ).isoformat()
                    idle_for = max(0, int(time.time()) - last_epoch)
            except MobileError:
                # Status is best-effort — never fail the GET because the
                # idle marker probe blew up.
                pass

        return Status(
            instance_id=self.instance_id,
            state=state,
            last_run_at=last_run_at,
            idle_for_seconds=idle_for,
            ami_version=self.ami_version or None,
        )

    # ── Operations ───────────────────────────────────────────────

    def install_apk(self, apk_url: str) -> InstallResult:
        """Download an APK on the instance and install it via adb.

        Returns the package name + versionName parsed from ``aapt``.
        """
        self._assert_running()
        local = f"/tmp/install-{uuid.uuid4().hex}.apk"
        commands = [
            "set -eu",
            f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
            f"curl -fsSL -o {shlex.quote(local)} {shlex.quote(apk_url)}",
            f"{_ADB} install -r {shlex.quote(local)}",
            "PKG=$(aapt dump badging "
            f"{shlex.quote(local)} | awk -F\"'\" '/package: name=/{{print $2; exit}}')",
            "VER=$(aapt dump badging "
            f"{shlex.quote(local)} | awk -F\"'\" '/versionName=/{{print $4; exit}}')",
            "echo \"PACKAGE=$PKG\"",
            "echo \"VERSION=$VER\"",
            f"rm -f {shlex.quote(local)}",
        ]
        result = ssm.run_command(
            self.ssm,
            self.instance_id,
            commands=commands,
            timeout_seconds=_SSM_OP_TIMEOUT_SEC,
        )
        package = _grep_kv(result.stdout, "PACKAGE") or ""
        version = _grep_kv(result.stdout, "VERSION") or ""
        return InstallResult(package_name=package, version=version)

    def run_recipe(
        self,
        recipe_yaml: str,
        env: dict[str, str],
        screenshot_prefix: str | None,
    ) -> RunResult:
        """Run a Maestro recipe on the instance and collect S3 artifacts.

        The view is responsible for the singleton lock; this method does
        the in-VM ``try/finally`` to guarantee the idle marker bump.
        """
        self._assert_running()
        run_id = uuid.uuid4().hex
        prefix = (screenshot_prefix or run_id).strip("/")
        s3_prefix = f"screenshots/{prefix}"
        run_dir = f"/tmp/run-{run_id}"
        recipe_path = f"/tmp/recipe-{run_id}.yaml"
        recipe_b64 = base64.b64encode(recipe_yaml.encode("utf-8")).decode("ascii")
        env_flags = " ".join(
            f"--env {shlex.quote(f'{k}={v}')}" for k, v in (env or {}).items()
        )

        try:
            commands = [
                "set -eu",
                f"mkdir -p {shlex.quote(run_dir)}",
                # SSM runs as root by default; Maestro runs as `ubuntu`
                # and needs to create a `.maestro/` workdir inside
                # run_dir + write the recipe file it reads. Hand both
                # over to ubuntu before invoking maestro.
                f"chown -R ubuntu:ubuntu {shlex.quote(run_dir)}",
                f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
                f"echo {shlex.quote(recipe_b64)} | base64 -d > {shlex.quote(recipe_path)}",
                f"chown ubuntu:ubuntu {shlex.quote(recipe_path)}",
                # `cd run_dir` so Maestro's `takeScreenshot: "name"` (no
                # absolute path) lands inside run_dir alongside the
                # --debug-output artifacts, instead of relative to SSM's
                # cwd of `/` (which fails with Permission denied). Wrap
                # in `(...)` so the cwd change doesn't leak to the next
                # SSM step (the `aws s3 cp` below uses the absolute path).
                f"(cd {shlex.quote(run_dir)} && sudo -u ubuntu /usr/local/bin/maestro test "
                f"--debug-output {shlex.quote(run_dir)} "
                f"{env_flags} {shlex.quote(recipe_path)})",
                # Lift Maestro's per-command JSON report (if it exists)
                # out of the debug-output dir and emit it inline, framed
                # by markers, so the Python side can parse structured
                # step data without an extra SSM round-trip. We pick the
                # first ``commands-*.json`` — Maestro emits one per flow;
                # multi-flow recipes get the first flow's report (rare).
                # POSIX shell — dash on SSM doesn't have bash arrays. An
                # unmatched glob expands to the literal pattern, so we
                # guard with ``[ -f "$f" ]`` and break on the first hit.
                'echo "---STEPS_JSON_BEGIN---"',
                (
                    f"for f in {shlex.quote(run_dir)}/commands-*.json; do "
                    'if [ -f "$f" ]; then base64 -w0 < "$f"; break; fi; '
                    "done || true"
                ),
                'echo ""',
                'echo "---STEPS_JSON_END---"',
                f"aws s3 cp {shlex.quote(run_dir)}/ "
                f"s3://{self.s3_bucket}/{s3_prefix}/ --recursive",
                f"rm -f {shlex.quote(recipe_path)}",
                f"rm -rf {shlex.quote(run_dir)}",
            ]
            result = ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_SSM_RECIPE_TIMEOUT_SEC,
            )
            artifacts = self._presign_prefix(s3_prefix)
            steps = _parse_steps_marker(result.stdout)
            return RunResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                artifacts=artifacts,
                steps=steps,
            )
        finally:
            # Always bump the idle marker on the way out, even if the SSM
            # command failed mid-run. Without this, an upload-time fault
            # could leave a stale marker that trips the 10 min in-VM
            # auto-stop while the ECS task is still finalizing the
            # response. Best-effort — swallow failures so we don't mask
            # the original exception.
            try:
                ssm.run_command(
                    self.ssm,
                    self.instance_id,
                    commands=[f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true"],
                    timeout_seconds=_SSM_PROBE_TIMEOUT_SEC,
                )
            except Exception:
                pass
            # Singleton release is the view's job — the controller never
            # acquires the lock itself. See ``apps/mobile/views.py``
            # ``run_recipe`` for the lock lifecycle.

    def save_snapshot(self, name: str) -> SnapshotResult:
        self._assert_running()
        commands = [
            "set -eu",
            f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
            f"{_ADB} emu avd snapshot save {shlex.quote(name)}",
        ]
        ssm.run_command(
            self.ssm,
            self.instance_id,
            commands=commands,
            timeout_seconds=_SSM_OP_TIMEOUT_SEC,
        )
        return SnapshotResult(name=name, saved_at=_iso_now())

    def load_snapshot(self, name: str) -> SnapshotResult:
        self._assert_running()
        commands = [
            "set -eu",
            f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
            f"{_ADB} emu avd snapshot load {shlex.quote(name)}",
        ]
        ssm.run_command(
            self.ssm,
            self.instance_id,
            commands=commands,
            timeout_seconds=_SSM_OP_TIMEOUT_SEC,
        )
        return SnapshotResult(name=name, loaded_at=_iso_now())

    def list_states(self) -> StatesCatalog:
        """Read the AMI's baked-in states catalog via SSM.

        Cheap probe (~1 s) — we re-read on every call rather than
        cache, so an AMI rebake without ace-web restart picks up
        immediately. The instance must be running.
        """
        self._assert_running()
        commands = [
            "set +e",
            f"cat {shlex.quote(_STATES_YAML_PATH)} 2>/dev/null",
            "echo '---ACTIVE---'",
            f"cat {shlex.quote(_ACTIVE_STATE_PATH)} 2>/dev/null || true",
        ]
        result = ssm.run_command(
            self.ssm,
            self.instance_id,
            commands=commands,
            timeout_seconds=_SSM_PROBE_TIMEOUT_SEC,
        )
        return _parse_states_yaml(result.stdout)

    def select_state(self, state_name: str) -> RunningState:
        """Switch to a different baked state on a running instance.

        Stops the current emulator and relaunches it with the requested
        snapshot. ``ensure_running(state_name=...)`` is the typical path
        in; this method is the explicit op for callers that want to
        switch without rolling through ensure-running's other checks.
        """
        self._assert_running()
        self._switch_state(state_name)
        info = self._describe_instance()
        return RunningState(
            instance_id=self.instance_id,
            state=info["state"],
            public_dns=info.get("public_dns"),
            started_at=_iso_now(),
        )

    def capture_ui_dump(self) -> str:
        self._assert_running()
        commands = [
            "set -eu",
            f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
            f"{_ADB} shell uiautomator dump /sdcard/ui-dump.xml >/dev/null",
            f"{_ADB} shell cat /sdcard/ui-dump.xml",
        ]
        result = ssm.run_command(
            self.ssm,
            self.instance_id,
            commands=commands,
            timeout_seconds=_SSM_OP_TIMEOUT_SEC,
        )
        return result.stdout

    def capture_screenshot(self) -> Artifact:
        """Take a screenshot of the running AVD and return a presigned URL.

        Useful for "what's on screen right now" debug probes from
        skills, the API, or `/tmp/get-screenshot`. The PNG is uploaded
        to S3 with a timestamped key under ``screenshots/adhoc/``;
        S3's 7-day lifecycle cleans it up.
        """
        self._assert_running()
        run_id = uuid.uuid4().hex[:12]
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        local_path = f"/tmp/screen-{run_id}.png"
        s3_key = f"screenshots/adhoc/{ts}-{run_id}.png"
        commands = [
            "set -eu",
            f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
            f"sudo -u ubuntu {_ADB} shell screencap -p /sdcard/now.png",
            f"sudo -u ubuntu {_ADB} pull /sdcard/now.png {shlex.quote(local_path)} >/dev/null",
            f"aws s3 cp {shlex.quote(local_path)} "
            f"s3://{self.s3_bucket}/{shlex.quote(s3_key)} --quiet",
            f"rm -f {shlex.quote(local_path)}",
        ]
        ssm.run_command(
            self.ssm,
            self.instance_id,
            commands=commands,
            timeout_seconds=_SSM_OP_TIMEOUT_SEC,
        )
        try:
            url = self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.s3_bucket, "Key": s3_key},
                ExpiresIn=_PRESIGN_TTL_SEC,
            )
        except ClientError as e:
            raise MobileError(
                f"s3.generate_presigned_url failed for {s3_key}: {e}"
            ) from e
        return Artifact(
            name=f"{ts}-{run_id}.png",
            presigned_url=url,
            content_type="image/png",
        )

    # ── Internals ────────────────────────────────────────────────

    def _describe_instance(self) -> dict[str, Any]:
        try:
            resp = self.ec2.describe_instances(InstanceIds=[self.instance_id])
        except ClientError as e:
            raise MobileError(f"ec2.describe_instances failed: {e}") from e
        reservations = resp.get("Reservations") or []
        if not reservations or not reservations[0].get("Instances"):
            raise MobileError(f"instance {self.instance_id} not found")
        inst = reservations[0]["Instances"][0]
        return {
            "state": (inst.get("State") or {}).get("Name", "unknown"),
            "public_dns": inst.get("PublicDnsName") or None,
        }

    def _start_instance(self) -> None:
        try:
            self.ec2.start_instances(InstanceIds=[self.instance_id])
        except ClientError as e:
            raise MobileError(f"ec2.start_instances failed: {e}") from e

    def _wait_for_ec2_ok(self, timeout_sec: int) -> None:
        """Poll ``describe_instance_status`` until ``Status == 'ok'``.

        Means both the system reachability and instance reachability
        checks have passed *and* SSM agent is running.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                resp = self.ec2.describe_instance_status(
                    InstanceIds=[self.instance_id],
                    IncludeAllInstances=True,
                )
            except ClientError as e:
                raise MobileError(
                    f"ec2.describe_instance_status failed: {e}"
                ) from e
            statuses = resp.get("InstanceStatuses") or []
            if statuses:
                inst_state = (statuses[0].get("InstanceState") or {}).get("Name")
                inst_status = (statuses[0].get("InstanceStatus") or {}).get("Status")
                sys_status = (statuses[0].get("SystemStatus") or {}).get("Status")
                if (
                    inst_state == "running"
                    and inst_status == "ok"
                    and sys_status == "ok"
                ):
                    return
            time.sleep(5.0)
        raise EmulatorBootTimeout(
            f"instance {self.instance_id} did not reach 'ok' in {timeout_sec}s"
        )

    def _wait_for_emulator(self) -> None:
        """Probe the in-VM AVD until cold-boot registration completes.

        ``ace-emulator-launch`` writes ``_EMULATOR_READY_MARKER`` after:
          1. AVD boots (sys.boot_completed=1)
          2. CommCare APK is installed
          3. Both +7426 demo registration recipes succeed

        We poll for that marker rather than just ``sys.boot_completed``
        — the latter fires before registration, so callers would see
        "running" while the launcher is still typing into PersonalID.
        Budget: ~3 min on a cold instance start.

        Single source of truth for the timeout is the SSM wrapper's
        ``timeout_seconds``; the in-VM loop runs unbounded and just
        keeps polling until SSM tears the command down. Pre-fix the
        two layers had separate bounds (in-VM ``for i in seq 1 N``
        with ``N = timeout/5`` AND SSM ``timeout + 10``), so logs and
        errors were ambiguous about which one fired. With one bound,
        any timeout is always an SSM timeout.
        """
        marker = _EMULATOR_READY_MARKER
        commands = [
            "set -eu",
            # Unbounded in-VM poll — SSM's timeout_seconds is the
            # single source of truth. ``exec >/dev/null`` would also
            # work, but ``echo READY`` lets the caller's SSM result
            # text show progress if we ever surface it.
            f"while [ ! -f {shlex.quote(marker)} ]; do sleep 5; done; "
            "echo READY",
        ]
        try:
            ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_EMULATOR_READY_TIMEOUT_SEC,
            )
        except (SSMFailure, SSMTimeout) as e:
            raise EmulatorBootTimeout(
                f"emulator on {self.instance_id} did not reach boot_completed: {e.message}"
            ) from e

    def patch_launch_script(self, *, script_body: str, restart: bool) -> dict[str, Any]:
        """Hot-patch ``/usr/local/bin/ace-emulator-launch`` on the EC2
        instance with a new body, optionally restart the runner unit.

        Intent: emergency fix path for the launch script without a full
        AMI rebake. The same fix MUST also land in
        ``infra/mobile-ami/files/ace-emulator-launch`` in this repo so
        the next rebake picks it up — without that the live fix
        evaporates on next AMI roll.

        Body validation:
          - Must start with ``#!/bin/bash`` (no `env bash`, no `sh`).
          - Must be ≤ 64KB (current script is ~7KB; budget is for
            comments / pm-wait additions, not wholesale rewrites).

        Returns the SHA256 of the written body so the caller can confirm
        the live script matches what they sent.
        """
        if not script_body.startswith("#!/bin/bash"):
            raise MobileError(
                "launch script must start with '#!/bin/bash' shebang "
                "(got: " + repr(script_body[:32]) + ")"
            )
        if len(script_body.encode("utf-8")) > 64 * 1024:
            raise MobileError(
                "launch script body exceeds 64KB cap; this endpoint is "
                "for surgical fixes, not wholesale rewrites — rebake the AMI"
            )
        import hashlib

        sha = hashlib.sha256(script_body.encode("utf-8")).hexdigest()
        body_b64 = base64.b64encode(script_body.encode("utf-8")).decode("ascii")
        target = "/usr/local/bin/ace-emulator-launch"
        commands = [
            "set -eu",
            # Back up the prior version with a timestamp so an operator
            # can recover by hand if the patch turns out to be wrong.
            f"sudo cp -p {shlex.quote(target)} "
            f"{shlex.quote(target)}.bak.$(date +%Y%m%d-%H%M%S) || true",
            f"echo {shlex.quote(body_b64)} | base64 -d | "
            f"sudo tee {shlex.quote(target)} >/dev/null",
            f"sudo chmod 0755 {shlex.quote(target)}",
            # Verify the on-disk SHA matches what we sent — fail loud
            # if base64 / shell quoting corrupted the body.
            # KEY=value framing so the Python side can demux with
            # `_grep_kv`. The earlier "SHA256: " variant was a parser
            # mismatch and surfaced as live=None / spurious SHA-fail
            # 500s while the write itself was fine.
            f"echo \"SHA256=$(sha256sum {shlex.quote(target)} | awk '{{print $1}}')\"",
        ]
        try:
            result = ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_SSM_OP_TIMEOUT_SEC,
            )
        except SSMFailure as e:
            raise MobileError(f"launch-script patch SSM call failed: {e.message}") from e
        live_sha = _grep_kv(result.stdout, "SHA256")
        if live_sha != sha:
            raise MobileError(
                f"launch-script SHA mismatch after write — sent={sha} live={live_sha}; "
                "body may have been corrupted in transit"
            )
        restart_log = ""
        if restart:
            try:
                restart_result = ssm.run_command(
                    self.ssm,
                    self.instance_id,
                    commands=[
                        "set +e",
                        f"sudo rm -f {shlex.quote(_EMULATOR_READY_MARKER)}",
                        "sudo systemctl restart ace-mobile-runner.service",
                    ],
                    timeout_seconds=_SSM_OP_TIMEOUT_SEC,
                )
                restart_log = restart_result.stdout
            except SSMFailure as e:
                raise MobileError(
                    f"launch-script written (sha={sha}) but runner restart failed: {e.message}"
                ) from e
        return {
            "sha256": sha,
            "bytes_written": len(script_body.encode("utf-8")),
            "restarted_runner": restart,
            "restart_log": restart_log.strip() or None,
        }

    def restart_runner(self, *, wait_for_ready: bool = True) -> Diagnostics:
        """Cleanly restart the ace-mobile-runner systemd unit.

        Public-API counterpart to the private ``_recover_emulator``.
        Use when the caller wants a fresh cold-boot without the state-
        switching side-effects of ``select_state`` and without the
        marker-stale-detection gate of ``ensure_running``. Typical
        operator path: "the emulator is wedged, get me a clean
        cold-boot and tell me the new state."

        Steps (one SSM round-trip):
          1. Stop the .service and any leftover override unit; reset
             their failed state.
          2. Wait up to 30s for any emulator process to exit.
          3. rm /run/ace-mobile/ready so _wait_for_emulator's probe
             can't accept the prior boot's signal.
          4. `systemctl start ace-mobile-runner.service`.

        Then, when ``wait_for_ready=True`` (default), poll for the
        ready marker and re-collect diagnostics so the response shape
        is the same as ``ensure_running``. ``wait_for_ready=False`` is
        a fire-and-forget mode useful for the operator who wants to
        kick a restart and walk away — returns immediately with a
        partial Diagnostics snapshot.
        """
        marker = _EMULATOR_READY_MARKER
        commands = [
            "set +e",
            "sudo systemctl stop ace-mobile-runner.service 2>/dev/null || true",
            "sudo systemctl stop ace-mobile-runner-override 2>/dev/null || true",
            "sudo systemctl reset-failed ace-mobile-runner.service "
            "2>/dev/null || true",
            "sudo systemctl reset-failed ace-mobile-runner-override "
            "2>/dev/null || true",
            "for i in $(seq 1 30); do "
            "  if ! pgrep -f 'qemu-system-x86_64|emulator -avd' >/dev/null; "
            "  then break; fi; sleep 1; "
            "done",
            f"sudo rm -f {shlex.quote(marker)}",
            "sudo systemctl start ace-mobile-runner.service",
        ]
        try:
            ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_SSM_OP_TIMEOUT_SEC,
            )
        except SSMFailure as e:
            raise MobileError(
                f"runner restart on {self.instance_id} failed: {e.message}"
            ) from e
        if wait_for_ready:
            self._wait_for_emulator()
        return self._collect_diagnostics()

    def _recover_emulator(self) -> None:
        """Restart the runner systemd unit, then wait for a fresh ready
        marker. Used by ``ensure_running`` when it detects a stale
        marker (marker present but adb sees no device) — i.e. the
        emulator died but the EC2 instance stayed up so the ``marker``
        file is left over in tmpfs from the prior boot.

        We explicitly remove the marker before restarting so
        ``_wait_for_emulator``'s subsequent probe blocks until the
        fresh launch script touches it again. Without the explicit
        remove there's a TOCTOU window where the new script is still
        booting AND the stale marker is still present, so the probe
        would return immediately.
        """
        marker = _EMULATOR_READY_MARKER
        commands = [
            "set +e",
            # Remove the stale marker first so _wait_for_emulator's
            # next probe doesn't accept the prior boot's signal.
            f"sudo rm -f {shlex.quote(marker)}",
            # systemd considers the unit 'inactive' after the prior
            # script exited; restart cleanly. ace-mobile-runner.service
            # has Restart=no so it doesn't auto-respawn after an
            # idle-shutdown of the emulator process — recovery here is
            # an explicit operator action.
            "sudo systemctl restart ace-mobile-runner.service",
        ]
        try:
            ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_SSM_OP_TIMEOUT_SEC,
            )
        except SSMFailure as e:
            raise EmulatorBootTimeout(
                f"emulator recovery on {self.instance_id} failed at "
                f"systemctl restart: {e.message}"
            ) from e
        # Now wait for the fresh cold-boot to set the marker.
        self._wait_for_emulator()

    def _collect_diagnostics(self) -> Diagnostics:
        """One SSM round-trip that captures everything a human or caller
        needs to tell whether the in-VM emulator is actually usable.

        Output is framed by ``---<KEY>---`` lines so the Python side
        can demux without needing JSON tooling on the instance. Each
        section is best-effort — failures in one section don't poison
        the others; missing fields surface as defaults in
        ``Diagnostics``.
        """
        marker = _EMULATOR_READY_MARKER
        commands = [
            "set +e",
            "echo '---ADB_DEVICES---'",
            # adb devices output is two-column "<serial>\t<state>" after
            # a "List of devices attached" header line. We strip the
            # header in Python.
            f"sudo -u ubuntu {_ADB} devices 2>&1 || echo 'adb_failed'",
            "echo '---EMULATOR_PROC---'",
            # The `emulator` wrapper script exec's `qemu-system-x86_64`
            # for the actual emulation process, so we look for either
            # pattern. The wrapper line is what `nohup $EMU` invokes
            # and what `_switch_state`'s pgrep waits on, but the
            # wrapper exits early in the lifecycle and only
            # qemu-system-x86_64 survives. Without the qemu fallback
            # `emulator_pid` is reported `null` even when the emulator
            # is alive and responding on emulator-5554 (caught in vivo
            # 2026-05-12 — adb saw the device, pgrep on 'emulator -avd'
            # did not, so an operator looking at the diagnose payload
            # thought the emulator was dead while it was actively
            # serving requests).
            "pgrep -af 'qemu-system-x86_64|emulator -avd' | head -1 || true",
            "echo '---RUNNER_SERVICE---'",
            "systemctl is-active ace-mobile-runner.service 2>/dev/null "
            "|| systemctl is-active ace-mobile-runner-override 2>/dev/null "
            "|| echo unknown",
            "echo '---MARKER---'",
            f"if [ -f {shlex.quote(marker)} ]; then "
            f"  echo present; "
            f"  echo \"mtime=$(stat -c %Y {shlex.quote(marker)} 2>/dev/null || echo 0)\"; "
            "else echo absent; echo mtime=0; fi",
            "echo '---RUNNER_LOG_TAIL---'",
            "tail -n 30 /var/log/ace-mobile/runner.log 2>/dev/null || echo '(no runner.log)'",
            "echo '---EMULATOR_LOG_TAIL---'",
            "tail -n 30 /var/log/ace-mobile/emulator.log 2>/dev/null || echo '(no emulator.log)'",
            "echo '---END---'",
        ]
        try:
            result = ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_SSM_PROBE_TIMEOUT_SEC,
            )
        except MobileError as e:
            return Diagnostics(ssm_ok=False, ssm_error=e.message)
        return _parse_diagnostics(result.stdout)

    def _assert_adb_visible(self, diag: Diagnostics) -> None:
        """Raise EmulatorNotReady if the ready-marker was observed but
        adb sees no device in 'device' state.

        This catches the canonical failure: the marker is stale from a
        prior boot, the emulator process is gone (idle-killed,
        crashed, or never started), but ``ensure_running``'s marker
        probe still returned READY. Without this guard, callers see a
        success response and then their first ``run_recipe`` /
        ``capture_ui_dump`` fails with the cryptic "adb: no
        devices/emulators found"."""
        if diag.adb_visible_count > 0:
            return
        raise EmulatorNotReady(
            "emulator on "
            f"{self.instance_id} signalled ready but no device is visible "
            "to adb (likely a stale ready-marker after the emulator died, "
            "or a partial cold-boot). See diagnostics for the in-VM state.",
            diagnostics=_diagnostics_to_dict(diag),
        )

    def _switch_state(self, state_name: str) -> None:
        """Stop ace-mobile-runner, restart with the requested state, wait for boot."""
        # The runner unit's ExecStart is /usr/local/bin/ace-emulator-launch
        # (no args, picks default). To switch, we override the unit's
        # exec by running the launch script directly via systemd-run with
        # the requested state, after stopping the existing unit.
        commands = [
            "set +e",
            f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
            "sudo systemctl stop ace-mobile-runner.service || true",
            # Also stop and reset any leftover override unit from a
            # prior select_state. Without this the next
            # `systemd-run --unit=ace-mobile-runner-override` fails
            # with "Unit ace-mobile-runner-override.service was
            # already loaded or has a fragment file" — caught in vivo
            # 2026-05-12 as a first-call-fails-second-call-succeeds
            # flake.
            "sudo systemctl stop ace-mobile-runner-override 2>/dev/null || true",
            "sudo systemctl reset-failed ace-mobile-runner-override 2>/dev/null || true",
            "for i in $(seq 1 30); do "
            "  if ! pgrep -f 'qemu-system-x86_64|emulator -avd' >/dev/null; then break; fi; "
            "  sleep 1; "
            "done",
            f"echo {shlex.quote(state_name)} | "
            f"sudo tee {shlex.quote(_ACTIVE_STATE_PATH)} >/dev/null",
            "sudo systemd-run --unit=ace-mobile-runner-override "
            "--collect --uid=ubuntu --gid=ubuntu "
            "--setenv=ANDROID_SDK_ROOT=/opt/android-sdk "
            "--setenv=ANDROID_HOME=/opt/android-sdk "
            f"/usr/local/bin/ace-emulator-launch {shlex.quote(state_name)}",
        ]
        try:
            ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_SSM_OP_TIMEOUT_SEC,
            )
        except SSMFailure as e:
            raise MobileError(f"select_state({state_name}) failed: {e.message}") from e
        # Now wait for the emulator to come back up.
        self._wait_for_emulator()

    def _read_active_state(self) -> str | None:
        """Read /run/ace-mobile/active-state via SSM. Best-effort."""
        try:
            result = ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=[f"cat {shlex.quote(_ACTIVE_STATE_PATH)} 2>/dev/null || true"],
                timeout_seconds=_SSM_PROBE_TIMEOUT_SEC,
            )
            text = (result.stdout or "").strip()
            return text or None
        except MobileError:
            return None

    def _assert_running(self) -> None:
        info = self._describe_instance()
        if info["state"] != "running":
            raise MobileError(
                f"instance {self.instance_id} is {info['state']!r}, expected 'running'; "
                "call /api/mobile/ensure-running first"
            )

    def _presign_prefix(self, prefix: str) -> list[Artifact]:
        try:
            resp = self.s3.list_objects_v2(
                Bucket=self.s3_bucket, Prefix=f"{prefix}/"
            )
        except ClientError as e:
            raise MobileError(f"s3.list_objects_v2 failed: {e}") from e
        contents = resp.get("Contents") or []
        artifacts: list[Artifact] = []
        for obj in contents:
            key = obj["Key"]
            try:
                url = self.s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.s3_bucket, "Key": key},
                    ExpiresIn=_PRESIGN_TTL_SEC,
                )
            except ClientError as e:
                raise MobileError(
                    f"s3.generate_presigned_url failed for {key}: {e}"
                ) from e
            artifacts.append(
                Artifact(
                    name=key.rsplit("/", 1)[-1],
                    presigned_url=url,
                    content_type=_guess_content_type(key),
                )
            )
        return artifacts


# ── Helpers ──────────────────────────────────────────────────────────


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _grep_kv(text: str, key: str) -> str | None:
    """Find a ``KEY=value`` line in stdout and return ``value``."""
    needle = f"{key}="
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith(needle):
            return line[len(needle):].strip()
    return None


def _parse_diagnostics(stdout: str) -> Diagnostics:
    """Demux the framed output of ``_collect_diagnostics``.

    Sections are separated by ``---<KEY>---`` lines; the parser walks
    line by line, switching sections on each marker and accumulating
    body lines into the matching field. Best-effort: a missing
    section simply leaves the field at its default.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in (stdout or "").splitlines():
        if line.startswith("---") and line.endswith("---"):
            current = line[3:-3]
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    diag = Diagnostics()
    diag.adb_devices = _parse_adb_devices_lines(sections.get("ADB_DEVICES", []))

    emu_lines = [ln for ln in sections.get("EMULATOR_PROC", []) if ln.strip()]
    if emu_lines:
        first = emu_lines[0].strip()
        # "<pid> <cmdline...>"
        parts = first.split(None, 1)
        if parts and parts[0].isdigit():
            diag.emulator_pid = int(parts[0])
            diag.emulator_cmdline = parts[1] if len(parts) > 1 else ""

    runner_lines = [ln for ln in sections.get("RUNNER_SERVICE", []) if ln.strip()]
    if runner_lines:
        diag.runner_service_state = runner_lines[0].strip()

    marker_lines = [ln for ln in sections.get("MARKER", []) if ln.strip()]
    if marker_lines:
        diag.marker_present = marker_lines[0].strip() == "present"
        mtime = _grep_kv("\n".join(marker_lines), "mtime")
        try:
            mt = int(mtime or "0")
        except ValueError:
            mt = 0
        if mt > 0:
            diag.marker_age_seconds = max(0, int(time.time()) - mt)

    diag.runner_log_tail = "\n".join(sections.get("RUNNER_LOG_TAIL", [])).rstrip()
    diag.emulator_log_tail = "\n".join(sections.get("EMULATOR_LOG_TAIL", [])).rstrip()
    return diag


def _parse_adb_devices_lines(lines: list[str]) -> list[AdbDevice]:
    """Parse the body of ``adb devices`` output.

    ``adb devices`` emits one header (``List of devices attached``)
    and zero-or-more ``<serial>\\t<state>`` rows. ``adb_failed`` is a
    sentinel the SSM probe emits when adb itself isn't on PATH.
    """
    devices: list[AdbDevice] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("List of devices"):
            continue
        if line == "adb_failed":
            continue
        # Lines may use tab OR multiple spaces; split on whitespace.
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append(AdbDevice(serial=parts[0], state=parts[1]))
    return devices


def _diagnostics_to_dict(diag: Diagnostics) -> dict[str, Any]:
    """Flatten a Diagnostics into the JSON shape ``_to_payload`` would
    produce, so it can be embedded into ``EmulatorNotReady`` (which
    can't import the view's ``_to_payload`` without a circular dep)."""
    return {
        "ssm_ok": diag.ssm_ok,
        "ssm_error": diag.ssm_error,
        "adb_devices": [{"serial": d.serial, "state": d.state} for d in diag.adb_devices],
        "adb_visible_count": diag.adb_visible_count,
        "emulator_pid": diag.emulator_pid,
        "emulator_cmdline": diag.emulator_cmdline,
        "runner_service_state": diag.runner_service_state,
        "marker_present": diag.marker_present,
        "marker_age_seconds": diag.marker_age_seconds,
        "runner_log_tail": diag.runner_log_tail,
        "emulator_log_tail": diag.emulator_log_tail,
    }


_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "xml": "application/xml",
    "json": "application/json",
    "txt": "text/plain",
    "log": "text/plain",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "html": "text/html",
}


def _guess_content_type(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _parse_states_yaml(stdout: str) -> StatesCatalog:
    """Parse the SSM probe output that contains states.yaml + active-state marker.

    Avoids a hard dependency on PyYAML by handling our own simple
    structure (plus, the AMI's bake script is the only writer).
    """
    text = stdout or ""
    if "---ACTIVE---" in text:
        yaml_part, _, tail = text.partition("---ACTIVE---")
        active = tail.strip().splitlines()[0].strip() if tail.strip() else None
    else:
        yaml_part = text
        active = None

    default = ""
    states: list[State] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current.get("name"):
            states.append(
                State(
                    name=current.get("name", ""),
                    snapshot=current.get("snapshot", ""),
                    commcare_version=current.get("commcare_version", ""),
                    description=current.get("description", ""),
                )
            )
        current = {}

    for raw in yaml_part.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        if line.startswith("default:"):
            default = line.split(":", 1)[1].strip().strip('"')
            continue
        if line.startswith("states:"):
            continue
        if stripped.startswith("- name:"):
            flush()
            current["name"] = stripped.split(":", 1)[1].strip().strip('"')
            continue
        if ":" in stripped and current:
            k, _, v = stripped.partition(":")
            current[k.strip()] = v.strip().strip('"')
    flush()

    return StatesCatalog(default=default, states=states, active=active or default or None)


# ── Maestro --debug-output parsing ────────────────────────────────────


_STEPS_MARKER_BEGIN = "---STEPS_JSON_BEGIN---"
_STEPS_MARKER_END = "---STEPS_JSON_END---"

# Maestro statuses → our normalized triplet. Anything else falls through
# to 'unknown' so a new Maestro release doesn't crash the parse.
_STEP_STATUS_MAP = {
    "COMPLETED": "pass",
    "PASS": "pass",
    "PASSED": "pass",
    "SUCCESS": "pass",
    "OK": "pass",
    "FAILED": "fail",
    "FAIL": "fail",
    "ERROR": "fail",
    "SKIPPED": "skipped",
    "SKIP": "skipped",
    "PENDING": "skipped",
}


def _parse_steps_marker(stdout: str) -> list[Step]:
    """Extract Maestro's commands-*.json (base64) from stdout markers,
    decode, and lift into our normalized Step list. Returns [] on any
    parse failure — never raises. Maestro's exact JSON shape varies by
    version, so every lookup is defensive.
    """
    if not stdout:
        return []
    begin = stdout.find(_STEPS_MARKER_BEGIN)
    end = stdout.find(_STEPS_MARKER_END)
    if begin < 0 or end < 0 or end <= begin:
        return []
    body = stdout[begin + len(_STEPS_MARKER_BEGIN):end].strip()
    if not body:
        return []
    try:
        raw = base64.b64decode(body, validate=False).decode("utf-8", errors="replace")
    except Exception:
        return []
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return _lift_maestro_steps(data)


def _lift_maestro_steps(data: Any) -> list[Step]:
    """Walk a Maestro commands JSON and produce Step records.

    Maestro emits either a top-level list of command records, or a flow
    object containing a ``commands`` list. We accept both. Each command
    record's keys vary by version — known shapes:
      { command: { tapOnElement: {...} } | { tapOn: "..." } | { ... },
        status: "COMPLETED" | "FAILED" | ..., metadata?: {...} }
    or
      { command, metadata: { status, duration, ... }, screenshot? }
    """
    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        commands = data.get("commands")
        if isinstance(commands, list):
            items = commands
        else:
            return []
    else:
        return []

    out: list[Step] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        # ``status`` lives at top level on newer Maestro; on older it's
        # nested in metadata.
        raw_meta = item.get("metadata")
        meta_for_status = raw_meta if isinstance(raw_meta, dict) else None
        status_raw = item.get("status") or (
            meta_for_status.get("status") if meta_for_status else None
        )
        status = _STEP_STATUS_MAP.get(str(status_raw or "").upper(), "unknown")
        name = _maestro_command_label(item.get("command"))
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        duration_ms = meta.get("duration") or meta.get("durationMs") or item.get("duration")
        try:
            duration_ms = int(duration_ms) if duration_ms is not None else None
        except (TypeError, ValueError):
            duration_ms = None
        screenshot = item.get("screenshot") or meta.get("screenshot")
        error = item.get("error") or meta.get("error")
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error)
        out.append(
            Step(
                index=i,
                name=name or f"step-{i}",
                status=status,
                screenshot=screenshot if isinstance(screenshot, str) else None,
                error=error if isinstance(error, str) else None,
                duration_ms=duration_ms,
            )
        )
    return out


def _maestro_command_label(command: Any) -> str | None:
    """Best-effort one-line label for a Maestro command record.

    Maestro commands are a single-key dict naming the action (``tapOn``,
    ``assertVisible``, etc.) whose value carries arguments. We surface
    ``<action>: <text>`` when there's a string-y argument, else just
    ``<action>``. Unknown shapes → None.
    """
    if not isinstance(command, dict) or not command:
        return None
    # Take first key — Maestro commands have exactly one.
    action = next(iter(command.keys()), None)
    if not action:
        return None
    arg = command[action]
    if isinstance(arg, str):
        return f"{action}: {arg}"
    if isinstance(arg, dict):
        # Pick a likely-displayable field.
        for k in ("text", "id", "name", "label", "value"):
            v = arg.get(k)
            if isinstance(v, str) and v:
                return f"{action}: {v}"
    return action
