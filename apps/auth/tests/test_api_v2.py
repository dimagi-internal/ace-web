"""Contract tests for apps.auth.api_v2."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

_FAKE_ME = {
    "id": 1,
    "email": "user@example.com",
    "display_name": "Test User",
    "is_staff": False,
    "workspaces": [{"slug": "my-ws", "name": "My Workspace"}],
}

_FAKE_CLI_STATUS = {
    "authenticated": True,
    "user": {"has_blob": True, "token_prefix": "sk-ant-oa"},
    "global_": {"has_blob": True},
}

_FAKE_NOVA_STATUS = {
    "connected": True,
    "valid": True,
    "expires_at": "2026-06-01T00:00:00Z",
    "scope": "openid",
    "can_manage": False,
}


@pytest.fixture
def auth_client(db, client):
    user = User.objects.create_user(email="user@example.com")
    client.force_login(user)
    return client, user


@pytest.fixture
def anon_client(db, client):
    return client


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.auth.api_v2.get_me_data",
        lambda user: _FAKE_ME,
    )
    resp = client.get("/api/v2/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "user@example.com"
    assert body["workspaces"][0]["slug"] == "my-ws"


@pytest.mark.django_db
def test_me_anon_401(anon_client):
    resp = anon_client.get("/api/v2/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_logout_204(auth_client):
    client, _ = auth_client
    resp = client.post("/api/v2/auth/logout")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_logout_anon_401(anon_client):
    resp = anon_client.post("/api/v2/auth/logout")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/e2e-login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_e2e_login_disabled_by_default(anon_client, settings):
    settings.ACE_E2E_AUTH_TOKEN = ""
    resp = anon_client.post(
        "/api/v2/auth/e2e-login",
        {"email": "ace@dimagi-ai.com", "token": "bad"},
        content_type="application/json",
    )
    # 404 because e2e login is disabled
    assert resp.status_code == 404


@pytest.mark.django_db
def test_e2e_login_wrong_token_403(anon_client, settings, monkeypatch):
    settings.ACE_E2E_AUTH_TOKEN = "correct-token"
    resp = anon_client.post(
        "/api/v2/auth/e2e-login",
        {"email": "ace@dimagi-ai.com", "token": "wrong-token"},
        content_type="application/json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_e2e_login_success_200(anon_client, settings, monkeypatch):
    settings.ACE_E2E_AUTH_TOKEN = "secret-token"
    settings.ACE_ALLOWED_EMAIL_DOMAINS = []
    monkeypatch.setattr(
        "apps.auth.api_v2.do_e2e_login",
        lambda req, body: {"user_id": 42, "email": body.email},
    )
    resp = anon_client.post(
        "/api/v2/auth/e2e-login",
        {"email": "ace@dimagi-ai.com", "token": "secret-token"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "ace@dimagi-ai.com"


# ---------------------------------------------------------------------------
# GET /auth/cli/status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cli_status_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.auth.api_v2.get_cli_auth_status",
        lambda user: _FAKE_CLI_STATUS,
    )
    resp = client.get("/api/v2/auth/cli/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True


@pytest.mark.django_db
def test_cli_status_anon_401(anon_client):
    resp = anon_client.get("/api/v2/auth/cli/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /auth/nova/status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nova_status_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.auth.api_v2.get_nova_status",
        lambda user: _FAKE_NOVA_STATUS,
    )
    resp = client.get("/api/v2/auth/nova/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["valid"] is True


@pytest.mark.django_db
def test_nova_status_anon_401(anon_client):
    resp = anon_client.get("/api/v2/auth/nova/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/nova/disconnect (admin only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_nova_disconnect_non_admin_403(auth_client, monkeypatch):
    client, _ = auth_client
    resp = client.post("/api/v2/auth/nova/disconnect")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_nova_disconnect_admin_200(db, client, monkeypatch):
    admin = User.objects.create_user(email="admin@dimagi-ai.com")
    client.force_login(admin)
    monkeypatch.setattr("apps.common.nova_auth_flow.clear_blob", lambda: None)
    resp = client.post("/api/v2/auth/nova/disconnect")
    assert resp.status_code == 200
    assert resp.json()["disconnected"] is True
