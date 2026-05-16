"""Controller orchestration tests.

We use ``botocore.stub.Stubber`` for boto3 calls so the test layer
exercises real client request/response shapes (parameter validation
included) without touching AWS. Each ``stub_*`` fixture comes pre-
activated; tests queue responses with ``add_response`` / ``add_client_error``.

Where the exact request parameters are not the point of the test, we use
``ANY`` to keep the test focused on the orchestration shape.
"""
from __future__ import annotations

import time

import pytest

from apps.mobile import singleton
from apps.mobile.exceptions import (
    EmulatorBootTimeout,
    EmulatorNotReady,
    MobileError,
    SSMFailure,
    SSMTimeout,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _describe_resp(state: str, dns: str = "ec2-1-2-3-4.compute.amazonaws.com") -> dict:
    return {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0123456789abcdef0",
                        "State": {"Name": state},
                        "PublicDnsName": dns,
                    }
                ]
            }
        ]
    }


def _instance_status_resp(
    inst_state: str = "running",
    inst_status: str = "ok",
    sys_status: str = "ok",
) -> dict:
    return {
        "InstanceStatuses": [
            {
                "InstanceId": "i-0123456789abcdef0",
                "InstanceState": {"Name": inst_state, "Code": 16},
                "InstanceStatus": {"Status": inst_status},
                "SystemStatus": {"Status": sys_status},
            }
        ]
    }


_DEFAULT_COMMAND_ID = "11111111-1111-1111-1111-111111111111"


def _send_command_resp(command_id: str = _DEFAULT_COMMAND_ID) -> dict:
    return {
        "Command": {
            "CommandId": command_id,
            "Status": "Pending",
        }
    }


def _invocation_resp(
    *,
    status: str = "Success",
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict:
    return {
        "CommandId": _DEFAULT_COMMAND_ID,
        "InstanceId": "i-0123456789abcdef0",
        "Status": status,
        "ResponseCode": exit_code,
        "StandardOutputContent": stdout,
        "StandardErrorContent": stderr,
    }


def _queue_ssm_command(stub, *, stdout: str = "", exit_code: int = 0):
    """Queue one SSM send_command + one terminal get_command_invocation."""
    stub.add_response("send_command", _send_command_resp())
    stub.add_response(
        "get_command_invocation",
        _invocation_resp(stdout=stdout, exit_code=exit_code),
    )


def _diagnostics_stdout(
    *,
    adb_devices: list[tuple[str, str]] | None = None,
    emulator_pid: int | None = 12345,
    runner_service: str = "active",
    marker_present: bool = True,
    marker_mtime: int = 0,  # 0 → "not set"
    runner_log: str = "[ace-emulator-launch] registration complete",
    emulator_log: str = "(emulator log)",
) -> str:
    """Compose the framed stdout that ``_collect_diagnostics`` parses."""
    devices = adb_devices if adb_devices is not None else [("emulator-5554", "device")]
    adb_lines = ["List of devices attached"]
    adb_lines += [f"{s}\t{st}" for s, st in devices]
    proc_line = (
        f"{emulator_pid} /opt/android-sdk/emulator/emulator -avd ACE_Pixel_API_34"
        if emulator_pid is not None
        else ""
    )
    marker_lines = (
        ["present", f"mtime={marker_mtime}"]
        if marker_present
        else ["absent", "mtime=0"]
    )
    return (
        "---ADB_DEVICES---\n"
        + "\n".join(adb_lines)
        + "\n---EMULATOR_PROC---\n"
        + proc_line
        + "\n---RUNNER_SERVICE---\n"
        + runner_service
        + "\n---MARKER---\n"
        + "\n".join(marker_lines)
        + "\n---RUNNER_LOG_TAIL---\n"
        + runner_log
        + "\n---EMULATOR_LOG_TAIL---\n"
        + emulator_log
        + "\n---END---\n"
    )


def _queue_diagnostics(stub, **kw):
    """Queue the SSM command + invocation pair for a _collect_diagnostics call."""
    _queue_ssm_command(stub, stdout=_diagnostics_stdout(**kw))


# ── Lifecycle: ensure_running ────────────────────────────────────────


def test_ensure_running_when_already_running_only_probes(controller_factory, monkeypatch):
    """Already-running instance should skip start + skip wait_for_ec2_ok,
    only probe the in-VM emulator via SSM."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    # _wait_for_emulator probe.
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    # _collect_diagnostics probe (one device visible → adb_visible_count>0).
    _queue_diagnostics(controller_factory.ssm_stub)

    state = c.ensure_running()
    assert state.state == "running"
    assert state.instance_id == "i-0123456789abcdef0"
    assert state.diagnostics is not None
    assert state.diagnostics.adb_visible_count == 1
    assert state.diagnostics.runner_service_state == "active"


def test_ensure_running_starts_stopped_instance(controller_factory, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("stopped")
    )
    controller_factory.ec2_stub.add_response(
        "start_instances",
        {"StartingInstances": []},
    )
    controller_factory.ec2_stub.add_response(
        "describe_instance_status", _instance_status_resp()
    )
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    _queue_diagnostics(controller_factory.ssm_stub)
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )

    state = c.ensure_running()
    assert state.state == "running"
    assert state.diagnostics is not None
    assert state.diagnostics.adb_visible_count == 1


def test_ensure_running_auto_recovers_stale_marker(
    controller_factory, monkeypatch
):
    """The canonical failure: ready-marker exists but adb sees no
    device. ensure_running must NOT just bail — it should restart the
    runner unit, wait for a fresh registration, and return success.

    Pre-fix the caller hit ``adb: no devices/emulators found`` on the
    next call (cryptic, no context). Mid-fix we raised EmulatorNotReady
    with a diagnostic snapshot (better, but still required an
    operator). This is the v3: auto-recover once, raise only if
    recovery itself fails."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    # Initial _wait_for_emulator probe — marker exists (stale).
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    # First _collect_diagnostics — empty adb (the stale-marker case).
    _queue_diagnostics(
        controller_factory.ssm_stub, adb_devices=[], emulator_pid=None
    )
    # _recover_emulator: stop+reset units, wait for qemu to die, rm
    # marker, start runner — same recipe restart_runner uses (one SSM
    # round-trip; see _runner_clean_restart_commands).
    _queue_ssm_command(controller_factory.ssm_stub, stdout="")
    # _wait_for_emulator again, this time on the fresh marker.
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    # Final _collect_diagnostics — adb sees the recovered emulator.
    _queue_diagnostics(controller_factory.ssm_stub)

    state = c.ensure_running()

    assert state.state == "running"
    assert state.diagnostics is not None
    assert state.diagnostics.adb_visible_count == 1


def test_recover_emulator_uses_full_runner_clean_restart(
    controller_factory, monkeypatch
):
    """Regression guard: ``_recover_emulator`` must use the same
    stop+kill+restart sequence as the public ``restart_runner`` path.
    Previously it just did ``rm marker; systemctl restart`` and skipped
    the qemu-process wait, so a still-running qemu from the prior boot
    held the AVD lock when the new launch script started and the boot
    failed with "AVD already in use"."""
    captured: list[list[str]] = []

    def fake_run_command(client, instance_id, *, commands, timeout_seconds, **_):
        captured.append(commands)
        from apps.mobile.ssm import CommandResult

        # _recover_emulator first invokes the cleanup SSM call, then
        # _wait_for_emulator polls for the READY marker — return READY
        # for the second call so the recovery completes.
        stdout = "READY\n" if len(captured) >= 2 else ""
        return CommandResult(status="Success", exit_code=0, stdout=stdout, stderr="")

    monkeypatch.setattr("apps.mobile.controller.ssm.run_command", fake_run_command)

    c = controller_factory()
    c._recover_emulator()

    cleanup = "\n".join(captured[0])
    # Must stop both the main unit AND the override unit (left over
    # from a prior select_state).
    assert "systemctl stop ace-mobile-runner.service" in cleanup
    assert "systemctl stop ace-mobile-runner-override" in cleanup
    # Must wait for qemu to exit before relaunching — the load-bearing
    # missing step the prior implementation skipped.
    assert "pgrep -f 'qemu-system-x86_64|emulator -avd'" in cleanup
    # Must clear the stale marker before the new launch touches it
    # (TOCTOU guard for _wait_for_emulator's probe). shlex.quote leaves
    # /run/ace-mobile/ready unchanged (no shell metacharacters), so the
    # literal string is fine to assert against.
    assert "rm -f /run/ace-mobile/ready" in cleanup
    # And only then start the fresh runner.
    assert "systemctl start ace-mobile-runner.service" in cleanup


def test_ensure_running_raises_emulator_not_ready_when_recovery_fails(
    controller_factory, monkeypatch
):
    """If recovery itself doesn't restore adb visibility, we surface
    the diagnostics on EmulatorNotReady. Recovery is best-effort — a
    sustained boot failure is an operator concern, not something we
    should mask."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    # Initial marker probe — present.
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    # First diagnostics — empty adb.
    _queue_diagnostics(
        controller_factory.ssm_stub, adb_devices=[], emulator_pid=None
    )
    # Recovery: rm + restart succeeds.
    _queue_ssm_command(controller_factory.ssm_stub, stdout="")
    # Re-wait for marker — succeeds (the runner script touched the
    # marker again).
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    # Second diagnostics — STILL empty (recovery touched the marker
    # but the emulator process didn't actually come back).
    _queue_diagnostics(
        controller_factory.ssm_stub, adb_devices=[], emulator_pid=None
    )

    with pytest.raises(EmulatorNotReady) as exc_info:
        c.ensure_running()
    diag = exc_info.value.diagnostics
    assert diag["adb_visible_count"] == 0
    assert "runner_log_tail" in diag


def test_ensure_running_raises_emulator_not_ready_when_only_offline_devices(
    controller_factory, monkeypatch
):
    """An adb device in 'offline' or 'unauthorized' state is not usable
    — only 'device' counts. The check has to look at state, not just
    the row count, otherwise a half-booted emulator passes the gate.
    Recovery is also attempted here; if it doesn't restore visibility,
    we raise."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    _queue_diagnostics(
        controller_factory.ssm_stub,
        adb_devices=[("emulator-5554", "offline")],
    )
    # Recovery attempted.
    _queue_ssm_command(controller_factory.ssm_stub, stdout="")
    _queue_ssm_command(controller_factory.ssm_stub, stdout="READY\n")
    _queue_diagnostics(
        controller_factory.ssm_stub,
        adb_devices=[("emulator-5554", "offline")],
    )

    with pytest.raises(EmulatorNotReady):
        c.ensure_running()


def test_ensure_running_unexpected_state_raises(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("terminated")
    )
    with pytest.raises(MobileError):
        c.ensure_running()


def test_ensure_running_boot_timeout_when_status_never_ok(
    controller_factory, monkeypatch
):
    """If describe_instance_status never reports 'ok', we hit the boot
    timeout and raise EmulatorBootTimeout."""
    # Crank time forward fast: each sleep advances the monotonic clock.
    fake_clock = {"t": 1000.0}

    def _mono():
        return fake_clock["t"]

    def _sleep(s):
        fake_clock["t"] += s

    monkeypatch.setattr(time, "monotonic", _mono)
    monkeypatch.setattr(time, "sleep", _sleep)

    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("stopped")
    )
    controller_factory.ec2_stub.add_response(
        "start_instances", {"StartingInstances": []}
    )
    # Queue a very long string of "initializing" responses — more than
    # the 180/5 = 36 polls _wait_for_ec2_ok will make before giving up.
    for _ in range(60):
        controller_factory.ec2_stub.add_response(
            "describe_instance_status",
            _instance_status_resp(inst_status="initializing"),
        )
    with pytest.raises(EmulatorBootTimeout):
        c.ensure_running()


# ── Lifecycle: stop ─────────────────────────────────────────────────


def test_stop_calls_ec2_stop_instances(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "stop_instances",
        {"StoppingInstances": []},
        expected_params={"InstanceIds": ["i-0123456789abcdef0"]},
    )
    result = c.stop()
    assert result.state == "stopping"
    assert result.instance_id == "i-0123456789abcdef0"


def test_stop_propagates_client_error(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_client_error(
        "stop_instances",
        service_error_code="UnauthorizedOperation",
        service_message="not allowed",
    )
    with pytest.raises(MobileError):
        c.stop()


# ── Lifecycle: status ───────────────────────────────────────────────


def test_status_reports_idle_marker_when_running(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    epoch = int(time.time()) - 30
    _queue_ssm_command(controller_factory.ssm_stub, stdout=f"{epoch}\n")
    s = c.status()
    assert s.state == "running"
    assert s.last_run_at is not None
    assert s.idle_for_seconds is not None
    assert 25 <= s.idle_for_seconds <= 60


def test_status_caches_idle_marker_skips_ssm_on_second_call(controller_factory):
    """Hot-path optimization: a second ``status()`` within the cache
    TTL must skip the SSM probe entirely. We queue exactly one SSM
    response and assert both calls succeed with the same idle_for —
    Stubber would fail the test if a second SSM round-trip happened
    (no response queued)."""
    c = controller_factory()
    # describe_instances fires on every status call (cheap EC2 API).
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    epoch = int(time.time()) - 30
    _queue_ssm_command(controller_factory.ssm_stub, stdout=f"{epoch}\n")

    s1 = c.status()
    s2 = c.status()

    assert s1.last_run_at == s2.last_run_at
    assert s1.idle_for_seconds is not None
    assert s2.idle_for_seconds is not None
    # Both calls must report a valid idle window; the second came from
    # the cache, not from SSM. Stubber would have raised on s2 if a
    # second SSM call had fired.
    controller_factory.ssm_stub.assert_no_pending_responses()


def test_status_caches_no_marker_case_too(controller_factory):
    """The "instance running but no recipe issued yet" path (marker
    file absent, ``stat`` returns 0) must also be cached so polling
    callers don't pay the SSM round-trip on every miss."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    # echo 0 → "no marker file" sentinel branch.
    _queue_ssm_command(controller_factory.ssm_stub, stdout="0\n")

    s1 = c.status()
    s2 = c.status()

    assert s1.last_run_at is None
    assert s1.idle_for_seconds is None
    assert s2.last_run_at is None
    assert s2.idle_for_seconds is None
    controller_factory.ssm_stub.assert_no_pending_responses()


def test_status_returns_stopped_state_without_ssm_probe(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("stopped")
    )
    s = c.status()
    assert s.state == "stopped"
    assert s.last_run_at is None
    assert s.idle_for_seconds is None


# ── Lifecycle: diagnose ─────────────────────────────────────────────


def test_diagnose_running_instance_reports_visible_emulator(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_diagnostics(controller_factory.ssm_stub)
    diag = c.diagnose()
    assert diag.ssm_ok is True
    assert diag.adb_visible_count == 1
    assert diag.adb_devices[0].serial == "emulator-5554"
    assert diag.adb_devices[0].state == "device"
    assert diag.emulator_pid == 12345
    assert diag.runner_service_state == "active"
    assert diag.marker_present is True


def test_diagnose_reports_unhealthy_emulator_without_raising(controller_factory):
    """Unlike ensure_running, diagnose never raises on degraded state —
    it just reports what it sees. This is the load-bearing contract:
    callers can probe without committing to a start."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_diagnostics(
        controller_factory.ssm_stub,
        adb_devices=[],
        emulator_pid=None,
        runner_service="failed",
    )
    diag = c.diagnose()
    assert diag.ssm_ok is True
    assert diag.adb_visible_count == 0
    assert diag.emulator_pid is None
    assert diag.runner_service_state == "failed"


def test_diagnose_when_instance_stopped_reports_ssm_unavailable(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("stopped")
    )
    diag = c.diagnose()
    assert diag.ssm_ok is False
    assert "is 'stopped'" in (diag.ssm_error or "")


# ── Operations: install_apk ─────────────────────────────────────────


def test_install_apk_parses_package_and_version(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(
        controller_factory.ssm_stub,
        stdout="PACKAGE=org.commcare.dalvik\nVERSION=2.62.0\n",
    )
    result = c.install_apk("https://example.com/cc.apk")
    assert result.package_name == "org.commcare.dalvik"
    assert result.version == "2.62.0"


def test_install_apk_when_not_running_raises(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("stopped")
    )
    with pytest.raises(MobileError):
        c.install_apk("https://example.com/cc.apk")


# ── Operations: run_recipe ──────────────────────────────────────────


def test_run_recipe_returns_artifacts_with_presigned_urls(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub, stdout="passed\n")
    # finally branch idle bump
    _queue_ssm_command(controller_factory.ssm_stub)
    controller_factory.s3_stub.add_response(
        "list_objects_v2",
        {
            "Contents": [
                {"Key": "screenshots/run-1/01.png", "Size": 100},
                {"Key": "screenshots/run-1/results.xml", "Size": 200},
            ]
        },
    )
    # generate_presigned_url is not stubbed (it's a client-side helper);
    # boto returns a real URL string from local creds. No queue needed.
    result = c.run_recipe(
        recipe_yaml="appId: com.example\n---\n- launchApp",
        env={"FOO": "bar"},
        screenshot_prefix="run-1",
    )
    assert result.exit_code == 0
    assert len(result.artifacts) == 2
    names = sorted(a.name for a in result.artifacts)
    assert names == ["01.png", "results.xml"]
    assert all(a.presigned_url.startswith("https://") for a in result.artifacts)
    types = {a.name: a.content_type for a in result.artifacts}
    assert types["01.png"] == "image/png"
    assert types["results.xml"] == "application/xml"
    # No steps marker in stdout → empty steps list (back-compat).
    assert result.steps == []


def test_run_recipe_parses_steps_from_marker_block(controller_factory):
    """End-to-end: stdout contains a base64-encoded Maestro commands JSON
    between the begin/end markers, and run_recipe lifts it into Step
    records on the response."""
    import base64 as _b64
    import json as _json

    maestro_json = _json.dumps([
        {
            "command": {"launchApp": "com.example"},
            "status": "COMPLETED",
            "metadata": {"duration": 1234},
        },
        {
            "command": {"tapOn": "Submit"},
            "status": "COMPLETED",
            "screenshot": "01.png",
        },
        {
            "command": {"assertVisible": {"text": "Welcome"}},
            "status": "FAILED",
            "error": {"message": "element not found"},
        },
    ])
    framed = (
        "...maestro chatter...\n"
        "---STEPS_JSON_BEGIN---\n"
        f"{_b64.b64encode(maestro_json.encode()).decode()}\n"
        "---STEPS_JSON_END---\n"
    )

    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub, stdout=framed)
    _queue_ssm_command(controller_factory.ssm_stub)  # finally branch idle bump
    controller_factory.s3_stub.add_response("list_objects_v2", {"Contents": []})

    result = c.run_recipe(recipe_yaml="...", env={}, screenshot_prefix="run-2")
    assert len(result.steps) == 3
    assert result.steps[0].name == "launchApp: com.example"
    assert result.steps[0].status == "pass"
    assert result.steps[0].duration_ms == 1234
    assert result.steps[1].screenshot == "01.png"
    assert result.steps[2].status == "fail"
    assert result.steps[2].error == "element not found"


def test_run_recipe_steps_absent_when_marker_block_empty(controller_factory):
    """Marker block present but empty body (no commands JSON file emitted
    by Maestro) → steps is an empty list, not an exception."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(
        controller_factory.ssm_stub,
        stdout="---STEPS_JSON_BEGIN---\n\n---STEPS_JSON_END---\n",
    )
    _queue_ssm_command(controller_factory.ssm_stub)  # finally idle bump
    controller_factory.s3_stub.add_response("list_objects_v2", {"Contents": []})

    result = c.run_recipe(recipe_yaml="...", env={}, screenshot_prefix="run-3")
    assert result.steps == []


def test_lift_maestro_steps_handles_flow_object_shape():
    """Maestro emits either a top-level list or a flow object with
    .commands. _lift_maestro_steps accepts both."""
    from apps.mobile.controller import _lift_maestro_steps

    flow_obj = {
        "name": "test-flow",
        "commands": [
            {"command": {"launchApp": "com.x"}, "status": "PASSED"},
            {"command": {"tapOn": "Next"}, "status": "SKIPPED"},
        ],
    }
    steps = _lift_maestro_steps(flow_obj)
    assert [s.status for s in steps] == ["pass", "skipped"]
    assert steps[0].name == "launchApp: com.x"


def test_lift_maestro_steps_unknown_status_maps_to_unknown():
    """A status we don't recognize must not crash — it falls through to
    'unknown' so callers can still surface the row."""
    from apps.mobile.controller import _lift_maestro_steps

    steps = _lift_maestro_steps([
        {"command": {"tapOn": "x"}, "status": "WEIRD_NEW_STATE"}
    ])
    assert steps[0].status == "unknown"


def test_run_recipe_returns_runresult_on_script_failure(controller_factory):
    """A Maestro recipe that exits non-zero (parse error, selector miss,
    assertion failure) must come back as a RunResult with the full
    stderr — NOT raised as SSMFailure. cloud.ts at the boundary needs
    the structured envelope to attach diagnostics; the raw exception
    string buries the actual Maestro frame.

    Pre-fix the controller raised SSMFailure with stderr truncated to
    500 chars in the exception message — losing structure and
    truncating long parse-error frames. New contract uses
    ``return_on_script_failure=True`` so the failed-script case is
    indistinguishable from the passed-script case at the controller
    boundary; the caller branches on exit_code in the result envelope.
    """
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    # Recipe runs, exits non-zero with a long Maestro parse-error frame.
    full_parse_error = "> Parsing Failed\n\n/tmp/recipe.yaml:15\n" + "x" * 1000
    controller_factory.ssm_stub.add_response("send_command", _send_command_resp())
    controller_factory.ssm_stub.add_response(
        "get_command_invocation",
        _invocation_resp(status="Failed", exit_code=1, stderr=full_parse_error),
    )
    # S3 list (no artifacts on parse error)
    controller_factory.s3_stub.add_response(
        "list_objects_v2",
        {"Contents": []},
    )
    # finally idle-bump
    _queue_ssm_command(controller_factory.ssm_stub)

    result = c.run_recipe(recipe_yaml="appId: x\n", env={}, screenshot_prefix=None)
    assert result.exit_code == 1
    # Full stderr preserved — not truncated, not wrapped in exception string.
    assert "Parsing Failed" in result.stderr
    assert "x" * 1000 in result.stderr
    controller_factory.ssm_stub.assert_no_pending_responses()


def test_run_recipe_still_raises_on_infrastructure_failure(controller_factory):
    """Negative exit_code (signal-killed: instance terminated mid-run,
    SSM agent crashed, etc.) is NOT a script-level failure. There's
    nothing to wrap in a RunResult, so it must still raise
    SSMFailure → 502. Distinguishes "the recipe ran and failed" from
    "the recipe never got a chance to run cleanly"."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.ssm_stub.add_response("send_command", _send_command_resp())
    controller_factory.ssm_stub.add_response(
        "get_command_invocation",
        _invocation_resp(status="Failed", exit_code=-1, stderr=""),
    )
    # finally idle-bump
    _queue_ssm_command(controller_factory.ssm_stub)

    with pytest.raises(SSMFailure):
        c.run_recipe(recipe_yaml="...", env={}, screenshot_prefix=None)
    controller_factory.ssm_stub.assert_no_pending_responses()


def test_run_recipe_finally_bumps_idle_marker_even_on_infrastructure_failure(
    controller_factory,
):
    """When the recipe-run genuinely raises (signal-killed), the finally
    branch must still issue the idle-bump SSM call so we don't leak a
    stale activity timestamp that trips the in-VM idle watchdog while
    ace-web is still wrapping things up."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.ssm_stub.add_response("send_command", _send_command_resp())
    controller_factory.ssm_stub.add_response(
        "get_command_invocation",
        _invocation_resp(status="Failed", exit_code=-1, stderr="killed"),
    )
    # finally idle-bump
    _queue_ssm_command(controller_factory.ssm_stub)

    with pytest.raises(SSMFailure):
        c.run_recipe(recipe_yaml="...", env={}, screenshot_prefix=None)
    controller_factory.ssm_stub.assert_no_pending_responses()


def test_run_recipe_ssm_timeout_surfaces_as_ssm_timeout(controller_factory, monkeypatch):
    """An SSM probe loop that exceeds the timeout must raise SSMTimeout
    so the view can map it to 504, not 500."""
    fake_clock = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: fake_clock["t"])

    def _sleep(s):
        # Each "1 s" sleep jumps a giant amount so we trip the timeout
        # in one iteration without spinning the test.
        fake_clock["t"] += 10_000

    monkeypatch.setattr(time, "sleep", _sleep)

    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.ssm_stub.add_response(
        "send_command", _send_command_resp()
    )
    controller_factory.ssm_stub.add_response(
        "get_command_invocation",
        _invocation_resp(status="InProgress"),
    )
    # finally idle-bump still fires.
    _queue_ssm_command(controller_factory.ssm_stub)

    with pytest.raises(SSMTimeout):
        c.run_recipe(recipe_yaml="...", env={}, screenshot_prefix=None)


def test_run_recipe_extracts_palette_when_provided(controller_factory, monkeypatch):
    """When ``palette_tar_b64`` is provided, the SSM command stream must
    decode it and ``tar xzf`` into ``run_dir`` before Maestro starts —
    that way the local-side ``runFlow: file: "./form-advance.yaml"``
    refs in the resolved top recipe land alongside sibling palette files.
    """
    captured: dict[str, list[str]] = {}

    def fake_run_command(client, instance_id, *, commands, timeout_seconds, **_):
        if "commands" not in captured:
            captured["commands"] = commands
        from apps.mobile.ssm import CommandResult

        return CommandResult(status="Success", exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("apps.mobile.controller.ssm.run_command", fake_run_command)

    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.s3_stub.add_response("list_objects_v2", {"Contents": []})

    palette_b64 = "SGVsbG8sIFdvcmxkIQ=="  # synthetic — controller doesn't decode
    c.run_recipe(
        recipe_yaml="appId: com.example\n",
        env={},
        screenshot_prefix="run-with-palette",
        palette_tar_b64=palette_b64,
    )

    joined = "\n".join(captured["commands"])
    # Palette tarball flows through to a `tar xzf` step.
    assert palette_b64 in joined
    assert "base64 -d | sudo -u ubuntu tar xzf -" in joined
    # Recipe lives inside run_dir so sibling-file refs resolve.
    assert "/tmp/run-" in joined
    # Extraction precedes recipe write (so palette files don't clobber
    # the resolved top recipe even if names collide).
    palette_idx = joined.index("tar xzf -")
    recipe_write_idx = joined.index("base64 -d > /tmp/run-")
    assert palette_idx < recipe_write_idx, (
        "palette must extract before recipe is written so a same-named "
        "palette entry doesn't clobber the resolved top recipe"
    )


def test_run_recipe_skips_palette_step_when_absent(controller_factory, monkeypatch):
    """Back-compat: callers that don't ship a palette get the unchanged
    command stream — no ``tar xzf`` step, no behavior drift for pre-
    palette-shipping clients (the cloud ace-web before 2026-05-16)."""
    captured: dict[str, list[str]] = {}

    def fake_run_command(client, instance_id, *, commands, timeout_seconds, **_):
        if "commands" not in captured:
            captured["commands"] = commands
        from apps.mobile.ssm import CommandResult

        return CommandResult(status="Success", exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("apps.mobile.controller.ssm.run_command", fake_run_command)

    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.s3_stub.add_response("list_objects_v2", {"Contents": []})

    c.run_recipe(recipe_yaml="appId: x\n", env={}, screenshot_prefix=None)

    joined = "\n".join(captured["commands"])
    assert "tar xzf" not in joined


def test_run_recipe_shell_quotes_s3_destination_url(controller_factory, monkeypatch):
    """Belt-and-suspenders against shell injection in the ``aws s3 cp``
    SSM command: even if a future serializer widening lets an unsafe
    character through, the controller must ``shlex.quote`` the
    assembled ``s3://...`` URL so it can't break out of its shell token.

    We bypass the serializer by calling the controller directly with a
    prefix that contains shell metacharacters; the controller is the
    layer under test here. A safe prefix would pass through
    ``shlex.quote`` unchanged (POSIX doesn't quote alphanumerics), so
    the test wouldn't actually exercise the quoting code path."""
    captured: dict[str, list[str]] = {}

    def fake_run_command(client, instance_id, *, commands, timeout_seconds, **_):
        # Record only the first invocation (the recipe run itself); the
        # finally-branch idle bump is a separate call.
        if "commands" not in captured:
            captured["commands"] = commands
        from apps.mobile.ssm import CommandResult

        return CommandResult(status="Success", exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("apps.mobile.controller.ssm.run_command", fake_run_command)

    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    controller_factory.s3_stub.add_response("list_objects_v2", {"Contents": []})

    # Classic command-substitution payload — if the controller didn't
    # shlex.quote the URL, the in-VM shell would expand $(id) before
    # ``aws s3 cp`` ever ran.
    c.run_recipe(recipe_yaml="x", env={}, screenshot_prefix="evil$(id)")

    joined = "\n".join(captured["commands"])
    # The dangerous payload must appear only inside a shell-quoted
    # token; never as a raw substitution the shell would expand.
    assert "$(id)" in joined, "test setup broken: payload missing"
    # ``shlex.quote`` wraps strings containing ``$`` in single quotes.
    # Verify the s3:// URL was emitted as one such single-quoted token.
    assert "'s3://" in joined and "$(id)" not in joined.split("'s3://", 1)[0], (
        f"s3:// URL was not shell-quoted; injection vector open:\n{joined}"
    )
    # And the single-quoted token must contain the payload, proving
    # the quoter wrapped the whole URL (not just the safe prefix).
    quoted_segment = joined.split("'s3://", 1)[1].split("'", 1)[0]
    assert "$(id)" in quoted_segment, (
        f"payload escaped the shell-quoted token:\n{joined}"
    )


def test_presign_prefix_paginates_past_1000_keys(controller_factory):
    """Regression guard: ``_presign_prefix`` must use the boto3
    paginator so artifact lists past the 1000-key ``list_objects_v2``
    page limit don't silently truncate. We queue two pages — page 1
    truncated with ``IsTruncated=True`` + ``NextContinuationToken``,
    page 2 the remainder — and verify every key gets presigned.
    Pre-fix, the second page was never fetched and the caller saw
    only the first 1000 artifacts."""
    c = controller_factory()
    page1_keys = [f"run-big/{i:04d}.png" for i in range(1000)]
    page2_keys = [f"run-big/{i:04d}.png" for i in range(1000, 1234)]

    # Stubber wraps the underlying client.list_objects_v2 call regardless
    # of whether the caller goes through the paginator or invokes the
    # method directly — the paginator just loops calling the same op.
    controller_factory.s3_stub.add_response(
        "list_objects_v2",
        {
            "Contents": [{"Key": k, "Size": 100} for k in page1_keys],
            "IsTruncated": True,
            "NextContinuationToken": "page-2-token",
        },
    )
    controller_factory.s3_stub.add_response(
        "list_objects_v2",
        {
            "Contents": [{"Key": k, "Size": 100} for k in page2_keys],
            "IsTruncated": False,
        },
    )

    artifacts = c._presign_prefix("screenshots/run-big")

    assert len(artifacts) == len(page1_keys) + len(page2_keys), (
        f"expected paginator to fetch both pages; got {len(artifacts)} artifacts"
    )
    # Spot-check the boundary: last key on page 1 and first key on page 2.
    names = [a.name for a in artifacts]
    assert "0999.png" in names
    assert "1000.png" in names
    assert "1233.png" in names


def test_run_recipe_finally_swallows_idle_bump_errors(controller_factory):
    """If the idle-bump SSM call fails, the finally must not mask the
    main result. We observe by verifying a successful run still returns
    the result even when the idle bump errors out."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub, stdout="ok")
    # Idle bump fails terminally.
    controller_factory.ssm_stub.add_response(
        "send_command",
        _send_command_resp("22222222-2222-2222-2222-222222222222"),
    )
    controller_factory.ssm_stub.add_response(
        "get_command_invocation",
        _invocation_resp(status="Failed", exit_code=1),
    )
    controller_factory.s3_stub.add_response(
        "list_objects_v2", {"Contents": []}
    )
    result = c.run_recipe(recipe_yaml="...", env={}, screenshot_prefix=None)
    assert result.exit_code == 0
    assert result.artifacts == []


# ── Operations: snapshots + ui dump ────────────────────────────────


def test_save_snapshot_returns_name_and_timestamp(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub)
    r = c.save_snapshot("registered-test-user")
    assert r.name == "registered-test-user"
    assert r.saved_at is not None


def test_load_snapshot_returns_name_and_timestamp(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub)
    r = c.load_snapshot("registered-test-user")
    assert r.name == "registered-test-user"
    assert r.loaded_at is not None


def test_capture_ui_dump_returns_xml_string(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(
        controller_factory.ssm_stub,
        stdout="<hierarchy><node text='hi'/></hierarchy>\n",
    )
    xml = c.capture_ui_dump()
    assert "<hierarchy>" in xml


# ── Lock interaction at view layer is tested in test_views.py.
# Here we double-check the controller does NOT acquire the lock itself.


def test_run_recipe_does_not_take_singleton_lock(controller_factory, fake_redis):
    """The lock is the view's job. After a run_recipe call, the lock
    must still be unset (no orphan key)."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    _queue_ssm_command(controller_factory.ssm_stub)
    _queue_ssm_command(controller_factory.ssm_stub)  # finally idle bump
    controller_factory.s3_stub.add_response(
        "list_objects_v2", {"Contents": []}
    )
    c.run_recipe(recipe_yaml="x", env={}, screenshot_prefix=None)
    assert singleton.current_owner() == ""


# ── Sanity: dataclass shape ─────────────────────────────────────────


def test_install_result_is_a_dataclass():
    from apps.mobile.controller import InstallResult

    r = InstallResult(package_name="x", version="1")
    assert r.package_name == "x"
