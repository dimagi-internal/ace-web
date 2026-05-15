"""Contract tests for apps.mobile.api."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

_FAKE_STATUS = {
    "instance_id": "i-123",
    "region": "us-east-1",
    "s3_bucket": "my-bucket",
    "ami_version": "1.0",
    "configured": True,
}

_FAKE_JOB = {
    "job_id": "job-abc",
    "operation": "run_recipe",
    "status": "completed",
    "owner": "owner-xyz",
    "started_at": "2026-05-14T09:00:00Z",
    "completed_at": "2026-05-14T09:01:00Z",
    "result": {"exit_code": 0},
    "error": None,
    "error_code": None,
}


@pytest.fixture
def auth_client(db, client):
    user = User.objects.create_user(email="user@example.com")
    client.force_login(user)
    return client, user


@pytest.fixture
def admin_client(db, client):
    # admin@dimagi-ai.com domain is the automation identity (_can_write_global)
    user = User.objects.create_user(email="admin@dimagi-ai.com")
    client.force_login(user)
    return client, user


@pytest.fixture
def anon_client(db, client):
    return client


# ---------------------------------------------------------------------------
# GET /mobile/status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mobile_status_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.get_mobile_status",
        lambda: _FAKE_STATUS,
    )
    resp = client.get("/api/mobile/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["instance_id"] == "i-123"


@pytest.mark.django_db
def test_mobile_status_anon_401(anon_client):
    resp = anon_client.get("/api/mobile/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /mobile/ensure-running
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ensure_running_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.ensure_running_op",
        lambda state=None: {"status": "running"},
    )
    resp = client.post("/api/mobile/ensure-running")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /mobile/diagnose
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_diagnose_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.diagnose_op",
        lambda: {
            "ssm_ok": True,
            "ssm_error": None,
            "adb_devices": [],
            "adb_visible_count": 0,
            "emulator_pid": None,
            "emulator_cmdline": None,
            "runner_service_state": "active",
            "marker_present": True,
            "marker_age_seconds": 30,
            "runner_log_tail": "",
            "emulator_log_tail": "",
        },
    )
    resp = client.get("/api/mobile/diagnose")
    assert resp.status_code == 200
    assert resp.json()["ssm_ok"] is True


# ---------------------------------------------------------------------------
# GET /mobile/states
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_states_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.list_states_op",
        lambda: {"default": "v2.6", "states": [], "active": "v2.6"},
    )
    resp = client.get("/api/mobile/states")
    assert resp.status_code == 200
    assert resp.json()["default"] == "v2.6"


# ---------------------------------------------------------------------------
# POST /mobile/run-recipe — 202
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_recipe_202(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.submit_run_recipe",
        lambda body: {"job_id": "job-abc", "status": "running"},
    )
    resp = client.post(
        "/api/mobile/run-recipe",
        {"recipe_yaml": "appId: com.example.app\n---"},
        content_type="application/json",
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "job-abc"
    assert body["status"] == "running"


# ---------------------------------------------------------------------------
# GET /mobile/jobs/{job_id}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_job_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.get_job_status",
        lambda job_id: _FAKE_JOB if job_id == "job-abc" else None,
    )
    resp = client.get("/api/mobile/jobs/job-abc")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@pytest.mark.django_db
def test_get_job_404(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.mobile.api.get_job_status",
        lambda job_id: None,
    )
    resp = client.get("/api/mobile/jobs/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /mobile/admin/patch-launch-script (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_launch_script_non_admin_403(auth_client, monkeypatch):
    client, _ = auth_client
    resp = client.post(
        "/api/mobile/admin/patch-launch-script",
        {"script_body": "#!/bin/bash\n", "restart_runner": True},
        content_type="application/json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_patch_launch_script_admin_200(admin_client, monkeypatch):
    client, user = admin_client
    monkeypatch.setattr(
        "apps.mobile.api.patch_launch_script_op",
        lambda u, body: {
            "id": 1,
            "created_at": "2026-05-14T09:00:00Z",
            "user_id": u.pk,
            "user_email": u.email,
            "sha256": "abc123",
            "bytes_written": 100,
            "restart_requested": True,
            "instance_id": "i-123",
            "ami_version": "1.0",
        },
    )
    resp = client.post(
        "/api/mobile/admin/patch-launch-script",
        {"script_body": "#!/bin/bash\n", "restart_runner": True},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["sha256"] == "abc123"


# ---------------------------------------------------------------------------
# GET /mobile/admin/launch-script-patches (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_patches_non_admin_403(auth_client):
    client, _ = auth_client
    resp = client.get("/api/mobile/admin/launch-script-patches")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_list_patches_admin_200(admin_client, monkeypatch):
    client, _ = admin_client
    monkeypatch.setattr(
        "apps.mobile.api.list_launch_script_patches",
        lambda offset=0, limit=50: {"patches": [], "total": 0, "limit": 50, "offset": 0},
    )
    resp = client.get("/api/mobile/admin/launch-script-patches")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
