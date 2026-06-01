"""Contract tests for apps.system.api."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

_FAKE_OVERVIEW = {
    "skills": [],
    "agents": [],
    "artifacts": [],
    "phases": [],
    "mcps": [],
    "plugin_version": "1.0",
    "remote_version": "1.0",
    "update_available": False,
    "warning": None,
}

_FAKE_VERSION = {
    "plugin_found": True,
    "plugin_version": "1.0",
    "remote_version": "1.1",
    "update_available": True,
    "plugin_path": "/app/vendor/ace",
}

_FAKE_SKILL_SUMMARY = {
    "name": "app-summary",
    "display_name": "App Summary",
    "description": "Summarizes an app",
    "ordinal": 1,
    "phase": "crispr",
    "has_judge": True,
    "is_recurring": False,
    "primary_output": None,
    "artifacts_produced": [],
    "artifacts_consumed": [],
}

_FAKE_SKILL = {
    **_FAKE_SKILL_SUMMARY,
    "body_markdown": "# App Summary\n...",
}

_FAKE_AGENT_SUMMARY = {
    "name": "crispr-agent",
    "description": "Main orchestrator",
    "model": "claude-sonnet",
}

_FAKE_AGENT = {
    **_FAKE_AGENT_SUMMARY,
    "body_markdown": "# Agent\n...",
}


@pytest.fixture
def auth_client(db, client):
    user = User.objects.create_user(email="sys@example.com")
    client.force_login(user)
    return client


@pytest.fixture
def anon_client(db, client):
    return client


# ---------------------------------------------------------------------------
# GET /system/overview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_overview_200(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_system_overview",
        lambda: _FAKE_OVERVIEW,
    )
    resp = auth_client.get("/api/system/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "skills" in body
    assert body["plugin_version"] == "1.0"


@pytest.mark.django_db
def test_overview_anon_401(anon_client):
    resp = anon_client.get("/api/system/overview")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /system/skills
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_skills_200(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_skills_list",
        lambda: [_FAKE_SKILL_SUMMARY],
    )
    resp = auth_client.get("/api/system/skills")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "app-summary"


# ---------------------------------------------------------------------------
# GET /system/skills/{name}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_skill_detail_200(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_skill_detail",
        lambda name: _FAKE_SKILL if name == "app-summary" else None,
    )
    resp = auth_client.get("/api/system/skills/app-summary")
    assert resp.status_code == 200
    assert resp.json()["body_markdown"] == "# App Summary\n..."


@pytest.mark.django_db
def test_skill_detail_404(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_skill_detail",
        lambda name: None,
    )
    resp = auth_client.get("/api/system/skills/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /system/agents
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_agents_200(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_agents_list",
        lambda: [_FAKE_AGENT_SUMMARY],
    )
    resp = auth_client.get("/api/system/agents")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "crispr-agent"


# ---------------------------------------------------------------------------
# GET /system/agents/{name}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_detail_200(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_agent_detail",
        lambda name: _FAKE_AGENT if name == "crispr-agent" else None,
    )
    resp = auth_client.get("/api/system/agents/crispr-agent")
    assert resp.status_code == 200
    assert resp.json()["body_markdown"] == "# Agent\n..."


@pytest.mark.django_db
def test_agent_detail_404(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_agent_detail",
        lambda name: None,
    )
    resp = auth_client.get("/api/system/agents/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /system/version
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_version_200(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.get_version_info",
        lambda: _FAKE_VERSION,
    )
    resp = auth_client.get("/api/system/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["update_available"] is True
    assert body["plugin_version"] == "1.0"


# ---------------------------------------------------------------------------
# POST /system/refresh-plugin
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_plugin_200_refreshed(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.run_plugin_refresh",
        lambda: {
            "ran": True,
            "refreshed": True,
            "version_before": "0.13.517",
            "version_after": "0.13.524",
            "detail": "swapped plugin cache",
        },
    )
    resp = auth_client.post("/api/system/refresh-plugin")
    assert resp.status_code == 200
    body = resp.json()
    assert body["refreshed"] is True
    assert body["version_after"] == "0.13.524"


@pytest.mark.django_db
def test_refresh_plugin_200_noop_when_already_latest(auth_client, monkeypatch):
    monkeypatch.setattr(
        "apps.system.api.run_plugin_refresh",
        lambda: {
            "ran": True,
            "refreshed": False,
            "version_before": "0.13.524",
            "version_after": "0.13.524",
            "detail": "version unchanged",
        },
    )
    resp = auth_client.post("/api/system/refresh-plugin")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ran"] is True
    assert body["refreshed"] is False


@pytest.mark.django_db
def test_refresh_plugin_anon_401(anon_client):
    resp = anon_client.post("/api/system/refresh-plugin")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_run_plugin_refresh_missing_script(monkeypatch, tmp_path):
    """run_plugin_refresh reports ran=False when the script is absent."""
    from django.test import override_settings

    from apps.system import api as system_api

    monkeypatch.setattr(
        "apps.system.version.check_version",
        lambda path: {"plugin_version": "0.13.524"},
    )
    with override_settings(BASE_DIR=tmp_path):
        result = system_api.run_plugin_refresh()
    assert result["ran"] is False
    assert result["refreshed"] is False
    assert "not found" in result["detail"]


# ---------------------------------------------------------------------------
# POST /system/cli-diag (admin/staff only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cli_diag_non_admin_403(auth_client, monkeypatch):
    resp = auth_client.post("/api/system/cli-diag")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_cli_diag_admin_200(db, client, monkeypatch):
    admin = User.objects.create_user(email="admin@dimagi-ai.com")
    client.force_login(admin)
    monkeypatch.setattr(
        "apps.system.api.run_cli_diag",
        lambda user, prompt=None, timeout_seconds=30.0: {
            "elapsed_seconds": 1.0,
            "returncode": 0,
            "stream_event_count": 3,
            "stderr_tail": "",
            "init_summary": None,
            "tool_uses": [],
        },
    )
    resp = client.post("/api/system/cli-diag")
    assert resp.status_code == 200
    assert resp.json()["returncode"] == 0
