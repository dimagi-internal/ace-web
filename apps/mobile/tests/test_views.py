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
    Artifact,
    InstallResult,
    RunningState,
    RunResult,
    SnapshotResult,
    StoppedState,
)
from apps.mobile.exceptions import EmulatorBootTimeout, SSMTimeout

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


def test_capture_ui_dump_returns_xml_and_elements(bearer_client, configured):
    from apps.mobile.controller import UiDumpResult, UiElement

    fake = MagicMock()
    fake.capture_ui_dump.return_value = UiDumpResult(
        xml='<hierarchy><node text="hi" class="android.widget.TextView"/></hierarchy>',
        elements=[
            UiElement(
                id="com.x:id/g",
                text="hi",
                class_="android.widget.TextView",
                bounds="[0,0][1,1]",
            )
        ],
    )
    with patch("apps.mobile.views.EmulatorController", return_value=fake):
        resp = bearer_client.post(
            "/api/mobile/capture-ui-dump", {}, format="json"
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["xml"].startswith("<hierarchy>")
    assert data["elements"] == [
        {
            "id": "com.x:id/g",
            "text": "hi",
            "class": "android.widget.TextView",
            "bounds": "[0,0][1,1]",
        }
    ]


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
