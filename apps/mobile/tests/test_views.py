"""Endpoint contract tests for ``/api/mobile/*``.

Auth wiring + status remain from Step 1. The 7 lifecycle endpoints now
have real implementations; we mock ``EmulatorController`` at the views
module level so each test exercises the view layer (envelope, status
codes, lock acquisition, serializer validation) without needing boto3
stubs. Controller-level orchestration is covered by test_controller.py.
"""
from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from apps.auth.models import PersonalToken
from apps.mobile import singleton
from apps.mobile.controller import (
    AdbDevice,
    Artifact,
    Diagnostics,
    InstallResult,
    RunningState,
    RunResult,
    SnapshotResult,
    StoppedState,
)
from apps.mobile.exceptions import EmulatorBootTimeout, EmulatorNotReady, SSMTimeout

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="mobile-test@example.com", display_name="m"
    )


@pytest.fixture
def bearer_client(user):
    raw, _ = PersonalToken.create_for_user(user=user, label="mobile-test")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return c


@pytest.fixture
def configured(settings):
    settings.ACE_MOBILE_INSTANCE_ID = "i-0123456789abcdef0"
    settings.ACE_MOBILE_S3_BUCKET = "ace-mobile-artifacts-test"
    settings.ACE_MOBILE_AMI_VERSION = "v1"
    return settings


# ── Status (unchanged from Step 1) ───────────────────────────────────


def test_status_requires_auth():
    c = APIClient()
    resp = c.get("/api/mobile/status")
    assert resp.status_code in (401, 403)


def test_status_rejects_bad_bearer():
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    resp = c.get("/api/mobile/status")
    assert resp.status_code in (401, 403)


def test_status_returns_envelope(bearer_client, settings):
    settings.ACE_MOBILE_INSTANCE_ID = ""
    settings.ACE_MOBILE_S3_BUCKET = ""
    resp = bearer_client.get("/api/mobile/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["instance_id"] is None
    assert data["s3_bucket"] is None
    assert data["configured"] is False


def test_status_reports_configured_when_env_set(bearer_client, configured):
    resp = bearer_client.get("/api/mobile/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["instance_id"] == "i-0123456789abcdef0"
    assert data["s3_bucket"] == "ace-mobile-artifacts-test"
    assert data["ami_version"] == "v1"
    assert data["configured"] is True


# ── Auth gate on lifecycle endpoints ─────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/mobile/ensure-running",
        "/api/mobile/select-state",
        "/api/mobile/install-apk",
        "/api/mobile/run-recipe",
        "/api/mobile/save-snapshot",
        "/api/mobile/load-snapshot",
        "/api/mobile/capture-ui-dump",
        "/api/mobile/stop",
    ],
)
def test_lifecycle_endpoints_require_auth(path):
    c = APIClient()
    resp = c.post(path, {}, format="json")
    assert resp.status_code in (401, 403)


def test_states_requires_auth():
    c = APIClient()
    resp = c.get("/api/mobile/states")
    assert resp.status_code in (401, 403)


# ── 503 when not configured ─────────────────────────────────────────


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/mobile/ensure-running", {}),
        ("/api/mobile/select-state", {"state": "cc-2.62.0"}),
        ("/api/mobile/install-apk", {"apk_url": "https://x/c.apk"}),
        ("/api/mobile/run-recipe", {"recipe_yaml": "x"}),
        ("/api/mobile/save-snapshot", {"name": "snap"}),
        ("/api/mobile/load-snapshot", {"name": "snap"}),
        ("/api/mobile/capture-ui-dump", {}),
        ("/api/mobile/stop", {}),
    ],
)
def test_lifecycle_endpoints_503_when_unconfigured(bearer_client, settings, path, body):
    settings.ACE_MOBILE_INSTANCE_ID = ""
    settings.ACE_MOBILE_S3_BUCKET = ""
    resp = bearer_client.post(path, body, format="json")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not-configured"


def test_states_503_when_unconfigured(bearer_client, settings):
    settings.ACE_MOBILE_INSTANCE_ID = ""
    settings.ACE_MOBILE_S3_BUCKET = ""
    resp = bearer_client.get("/api/mobile/states")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not-configured"


def test_states_returns_catalog(bearer_client, configured):
    from apps.mobile.controller import State, StatesCatalog

    fake = MagicMock()
    fake.list_states.return_value = StatesCatalog(
        default="cc-2.62.0",
        states=[
            State(
                name="cc-2.62.0",
                snapshot="cc-2.62.0-registered",
                commcare_version="2.62.0",
                description="CommCare 2.62.0",
            ),
            State(
                name="cc-2.63.0",
                snapshot="cc-2.63.0-registered",
                commcare_version="2.63.0",
                description="CommCare 2.63.0",
            ),
        ],
        active="cc-2.62.0",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.get("/api/mobile/states")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["default"] == "cc-2.62.0"
    assert body["active"] == "cc-2.62.0"
    assert len(body["states"]) == 2
    assert body["states"][0]["commcare_version"] == "2.62.0"


def test_select_state_validates_name(bearer_client, configured):
    resp = bearer_client.post(
        "/api/mobile/select-state", {"state": "../../etc/passwd"}, format="json"
    )
    assert resp.status_code == 400


def test_select_state_dispatches_to_controller(bearer_client, configured):
    fake = MagicMock()
    fake.select_state.return_value = RunningState(
        instance_id="i-0123",
        state="running",
        public_dns="ec2-1.example.com",
        started_at="2026-05-09T00:00:00+00:00",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/select-state", {"state": "cc-2.63.0"}, format="json"
        )
    assert resp.status_code == 200
    fake.select_state.assert_called_once_with(state_name="cc-2.63.0")


def test_ensure_running_passes_state_to_controller(bearer_client, configured):
    fake = MagicMock()
    fake.ensure_running.return_value = RunningState(
        instance_id="i-0123",
        state="running",
        public_dns=None,
        started_at="2026-05-09T00:00:00+00:00",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/ensure-running", {"state": "cc-2.63.0"}, format="json"
        )
    assert resp.status_code == 200
    fake.ensure_running.assert_called_once_with(state_name="cc-2.63.0")


# ── ensure_running ─────────────────────────────────────────────────


def test_ensure_running_returns_envelope(bearer_client, configured):
    fake = MagicMock()
    fake.ensure_running.return_value = RunningState(
        instance_id="i-0123456789abcdef0",
        state="running",
        public_dns="ec2-1.example.com",
        started_at="2026-05-09T00:00:00+00:00",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post("/api/mobile/ensure-running", {}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["state"] == "running"


def test_ensure_running_boot_timeout_returns_504(bearer_client, configured):
    fake = MagicMock()
    fake.ensure_running.side_effect = EmulatorBootTimeout("boot timed out")
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post("/api/mobile/ensure-running", {}, format="json")
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "boot-timeout"


def test_ensure_running_emulator_not_ready_surfaces_diagnostics(
    bearer_client, configured
):
    """The 503 emulator-not-ready response must carry the diagnostic
    snapshot inline so the caller knows why."""
    diag = {
        "adb_devices": [],
        "adb_visible_count": 0,
        "emulator_pid": None,
        "runner_service_state": "failed",
        "marker_present": True,
        "marker_age_seconds": 1200,
        "runner_log_tail": "[ace-emulator-launch] ERROR: boot timed out",
        "emulator_log_tail": "(short)",
    }
    fake = MagicMock()
    fake.ensure_running.side_effect = EmulatorNotReady("stale marker", diagnostics=diag)
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post("/api/mobile/ensure-running", {}, format="json")
    assert resp.status_code == 503
    err = resp.json()["error"]
    assert err["code"] == "emulator-not-ready"
    assert err["diagnostics"]["adb_visible_count"] == 0
    assert err["diagnostics"]["runner_service_state"] == "failed"
    assert err["diagnostics"]["marker_age_seconds"] == 1200


# ── diagnose ──────────────────────────────────────────────────────


def test_diagnose_returns_full_snapshot(bearer_client, configured):
    fake = MagicMock()
    fake.diagnose.return_value = Diagnostics(
        ssm_ok=True,
        adb_devices=[AdbDevice(serial="emulator-5554", state="device")],
        emulator_pid=12345,
        emulator_cmdline="/opt/.../emulator -avd ACE_Pixel_API_34",
        runner_service_state="active",
        marker_present=True,
        marker_age_seconds=42,
        runner_log_tail="...",
        emulator_log_tail="...",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.get("/api/mobile/diagnose")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["ssm_ok"] is True
    assert data["adb_devices"] == [{"serial": "emulator-5554", "state": "device"}]
    assert data["emulator_pid"] == 12345
    assert data["runner_service_state"] == "active"


def test_diagnose_when_unconfigured_returns_503(bearer_client, settings):
    settings.ACE_MOBILE_INSTANCE_ID = ""
    settings.ACE_MOBILE_S3_BUCKET = ""
    resp = bearer_client.get("/api/mobile/diagnose")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not-configured"


def test_diagnose_requires_auth():
    c = APIClient()
    resp = c.get("/api/mobile/diagnose")
    assert resp.status_code in (401, 403)


# ── install_apk ────────────────────────────────────────────────────


def test_install_apk_validates_url(bearer_client, configured):
    resp = bearer_client.post(
        "/api/mobile/install-apk", {"apk_url": "not-a-url"}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-request"


def test_install_apk_returns_package_and_version(bearer_client, configured):
    fake = MagicMock()
    fake.install_apk.return_value = InstallResult(
        package_name="org.commcare.dalvik", version="2.62.0"
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/install-apk",
            {"apk_url": "https://example.com/cc.apk"},
            format="json",
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["package_name"] == "org.commcare.dalvik"
    assert data["version"] == "2.62.0"
    fake.install_apk.assert_called_once_with(apk_url="https://example.com/cc.apk")


# ── run_recipe ─────────────────────────────────────────────────────


def test_run_recipe_validates_recipe_yaml(bearer_client, configured):
    resp = bearer_client.post(
        "/api/mobile/run-recipe", {"recipe_yaml": ""}, format="json"
    )
    assert resp.status_code == 400


def test_run_recipe_happy_path_acquires_and_releases_lock(bearer_client, configured):
    fake = MagicMock()
    fake.run_recipe.return_value = RunResult(
        exit_code=0,
        stdout="ok",
        stderr="",
        artifacts=[
            Artifact(
                name="01.png",
                presigned_url="https://s3/01.png?sig=x",
                content_type="image/png",
            )
        ],
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/run-recipe",
            {
                "recipe_yaml": "appId: x",
                "env": {"FOO": "bar"},
                "screenshot_prefix": "run-1",
            },
            format="json",
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exit_code"] == 0
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["name"] == "01.png"
    # Lock must be released after the call.
    assert singleton.current_owner() == ""


def test_run_recipe_503_on_singleton_contention(bearer_client, configured):
    """Pre-acquire the lock; the endpoint must return 503 with the
    current owner string in the error envelope."""
    singleton.try_acquire("other-task:other-req")
    fake = MagicMock()
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/run-recipe",
            {"recipe_yaml": "x", "env": {}},
            format="json",
        )
    assert resp.status_code == 503
    err = resp.json()["error"]
    assert err["code"] == "singleton-busy"
    assert err["current_owner"] == "other-task:other-req"
    fake.run_recipe.assert_not_called()


def test_run_recipe_releases_lock_on_controller_exception(bearer_client, configured):
    fake = MagicMock()
    fake.run_recipe.side_effect = SSMTimeout("timed out")
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/run-recipe",
            {"recipe_yaml": "x", "env": {}},
            format="json",
        )
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "ssm-timeout"
    assert singleton.current_owner() == ""


# ── snapshots ──────────────────────────────────────────────────────


def test_save_snapshot_validates_name(bearer_client, configured):
    resp = bearer_client.post(
        "/api/mobile/save-snapshot", {"name": "bad name with spaces"}, format="json"
    )
    assert resp.status_code == 400


def test_save_snapshot_returns_envelope(bearer_client, configured):
    fake = MagicMock()
    fake.save_snapshot.return_value = SnapshotResult(
        name="snap-1", saved_at="2026-05-09T00:00:00+00:00"
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/save-snapshot", {"name": "snap-1"}, format="json"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["name"] == "snap-1"
    assert body["data"]["saved_at"] is not None


def test_load_snapshot_returns_envelope(bearer_client, configured):
    fake = MagicMock()
    fake.load_snapshot.return_value = SnapshotResult(
        name="snap-1", loaded_at="2026-05-09T00:00:00+00:00"
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/load-snapshot", {"name": "snap-1"}, format="json"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["name"] == "snap-1"
    assert body["data"]["loaded_at"] is not None


# ── capture_ui_dump ───────────────────────────────────────────────


def test_capture_ui_dump_returns_xml(bearer_client, configured):
    fake = MagicMock()
    fake.capture_ui_dump.return_value = "<hierarchy/>"
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/capture-ui-dump", {}, format="json"
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["xml"] == "<hierarchy/>"


# ── stop ─────────────────────────────────────────────────────────


def test_stop_does_not_take_singleton_lock(bearer_client, configured):
    """Stop must succeed even when the singleton is held mid-run."""
    singleton.try_acquire("other-task:other-req")
    fake = MagicMock()
    fake.stop.return_value = StoppedState(
        instance_id="i-0123456789abcdef0",
        state="stopping",
        stopped_at="2026-05-09T00:00:00+00:00",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post("/api/mobile/stop", {}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] == "stopping"
    # Lock should remain held — stop didn't touch it.
    assert singleton.current_owner() == "other-task:other-req"


def test_stop_returns_envelope(bearer_client, configured):
    fake = MagicMock()
    fake.stop.return_value = StoppedState(
        instance_id="i-0123456789abcdef0",
        state="stopping",
        stopped_at="2026-05-09T00:00:00+00:00",
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post("/api/mobile/stop", {}, format="json")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["instance_id"] == "i-0123456789abcdef0"
    assert data["state"] == "stopping"
    assert data["stopped_at"]


# ── restart-runner ────────────────────────────────────────────────


def test_restart_runner_returns_post_restart_diagnostics(bearer_client, configured):
    fake = MagicMock()
    fake.restart_runner.return_value = Diagnostics(
        ssm_ok=True,
        adb_devices=[AdbDevice(serial="emulator-5554", state="device")],
        emulator_pid=7777,
        runner_service_state="active",
        marker_present=True,
        marker_age_seconds=12,
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post("/api/mobile/restart-runner", {}, format="json")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["adb_devices"] == [{"serial": "emulator-5554", "state": "device"}]
    assert data["marker_present"] is True
    fake.restart_runner.assert_called_once_with(wait_for_ready=True)


def test_restart_runner_honours_wait_for_ready_false(bearer_client, configured):
    fake = MagicMock()
    fake.restart_runner.return_value = Diagnostics(
        ssm_ok=True, marker_present=False, runner_service_state="activating"
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/restart-runner",
            {"wait_for_ready": False},
            format="json",
        )
    assert resp.status_code == 200
    fake.restart_runner.assert_called_once_with(wait_for_ready=False)


def test_restart_runner_requires_auth():
    c = APIClient()
    resp = c.post("/api/mobile/restart-runner", {}, format="json")
    assert resp.status_code in (401, 403)


# ── admin/patch-launch-script ─────────────────────────────────────


def test_admin_patch_launch_script_writes_and_restarts(bearer_client, configured):
    """Happy path — body validates, controller is called with both
    fields, response surfaces the SHA the controller returned."""
    fake = MagicMock()
    fake.patch_launch_script.return_value = {
        "sha256": "abc123",
        "bytes_written": 1234,
        "restarted_runner": True,
        "restart_log": None,
    }
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/admin/patch-launch-script",
            {"script_body": "#!/bin/bash\necho hi\n", "restart_runner": True},
            format="json",
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["sha256"] == "abc123"
    assert data["restarted_runner"] is True
    fake.patch_launch_script.assert_called_once_with(
        script_body="#!/bin/bash\necho hi\n", restart=True
    )


def test_admin_patch_launch_script_requires_script_body(bearer_client, configured):
    resp = bearer_client.post(
        "/api/mobile/admin/patch-launch-script", {}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-request"


def test_admin_patch_launch_script_requires_auth():
    c = APIClient()
    resp = c.post(
        "/api/mobile/admin/patch-launch-script",
        {"script_body": "#!/bin/bash\n"},
        format="json",
    )
    assert resp.status_code in (401, 403)


# ── Sanity: dataclass round-trip ──────────────────────────────────


def test_dataclass_to_dict_roundtrip():
    r = RunResult(
        exit_code=0,
        stdout="x",
        stderr="",
        artifacts=[Artifact(name="a", presigned_url="https://x", content_type="image/png")],
    )
    d = asdict(r)
    assert d["artifacts"][0]["name"] == "a"
