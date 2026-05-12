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
    # Final describe_instances to read state for return.
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )

    state = c.ensure_running()
    assert state.state == "running"
    assert state.instance_id == "i-0123456789abcdef0"


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
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )

    state = c.ensure_running()
    assert state.state == "running"


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


def test_status_returns_stopped_state_without_ssm_probe(controller_factory):
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("stopped")
    )
    s = c.status()
    assert s.state == "stopped"
    assert s.last_run_at is None
    assert s.idle_for_seconds is None


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


def test_run_recipe_finally_bumps_idle_marker_even_on_failure(controller_factory):
    """If the SSM run fails, the finally branch must still issue the
    idle-bump SSM call (which we observe by leaving exactly one idle
    bump SSM response queued — Stubber will assert all responses
    consumed at teardown)."""
    c = controller_factory()
    controller_factory.ec2_stub.add_response(
        "describe_instances", _describe_resp("running")
    )
    # First send_command succeeds, but get_command_invocation reports failure.
    controller_factory.ssm_stub.add_response(
        "send_command", _send_command_resp()
    )
    controller_factory.ssm_stub.add_response(
        "get_command_invocation",
        _invocation_resp(status="Failed", exit_code=1, stderr="boom"),
    )
    # finally idle-bump
    _queue_ssm_command(controller_factory.ssm_stub)

    with pytest.raises(SSMFailure):
        c.run_recipe(
            recipe_yaml="...",
            env={},
            screenshot_prefix=None,
        )
    # Both stub queues should be drained — Stubber.assert_no_pending_responses
    # is called at fixture teardown but we can also assert here.
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
