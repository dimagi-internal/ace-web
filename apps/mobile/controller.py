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
import shlex
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from . import ssm
from .exceptions import EmulatorBootTimeout, MobileError, SSMFailure

# How long to wait for the EC2 instance + SSM agent to come ready
# after a cold ``StartInstances`` call.
_BOOT_HARD_TIMEOUT_SEC = 180
# How long to wait for the in-VM Android emulator (already-running EC2
# instance) to report ``sys.boot_completed=1``. The emulator is launched
# by the systemd unit baked into the AMI; first boot after a cold
# instance start can take ~60 s.
_EMULATOR_READY_TIMEOUT_SEC = 120
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
class RunningState:
    instance_id: str
    state: str
    public_dns: str | None
    started_at: str


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
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    artifacts: list[Artifact]


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
            return RunningState(
                instance_id=self.instance_id,
                state="running",
                public_dns=info.get("public_dns"),
                started_at=_iso_now(),
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
        return RunningState(
            instance_id=self.instance_id,
            state=info["state"],
            public_dns=info.get("public_dns"),
            started_at=_iso_now(),
        )

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
                f"touch {shlex.quote(_IDLE_MARKER_PATH)} || true",
                f"echo {shlex.quote(recipe_b64)} | base64 -d > {shlex.quote(recipe_path)}",
                f"sudo -u ubuntu /usr/local/bin/maestro test "
                f"--debug-output {shlex.quote(run_dir)} "
                f"{env_flags} {shlex.quote(recipe_path)}",
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
            return RunResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                artifacts=artifacts,
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
        """Probe the in-VM Android emulator until ``sys.boot_completed``.

        Issues a single SSM command that itself blocks for up to
        ``_EMULATOR_READY_TIMEOUT_SEC`` — that's cheaper than polling
        SSM repeatedly and the in-VM ``adb wait-for-device`` is the
        thing we actually need to wait for.
        """
        commands = [
            "set -eu",
            f"{_ADB} wait-for-device",
            f"for i in $(seq 1 60); do "
            f"  ready=$({_ADB} shell getprop sys.boot_completed 2>/dev/null | tr -d '\\r'); "
            "  if [ \"$ready\" = \"1\" ]; then echo READY; exit 0; fi; "
            "  sleep 2; "
            "done; "
            "echo NOT_READY; exit 1",
        ]
        try:
            ssm.run_command(
                self.ssm,
                self.instance_id,
                commands=commands,
                timeout_seconds=_EMULATOR_READY_TIMEOUT_SEC + 10,
            )
        except SSMFailure as e:
            raise EmulatorBootTimeout(
                f"emulator on {self.instance_id} did not reach boot_completed: {e.message}"
            ) from e

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
            "for i in $(seq 1 30); do "
            "  if ! pgrep -f 'emulator -avd' >/dev/null; then break; fi; "
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
