"""Tests for /api/auth/cli/* endpoints. auth_flow is mocked at the function
level so the tests do not actually spawn a PTY."""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(django_user_model):
    user = django_user_model.objects.create_user(
        email="dev@example.com", display_name="dev"
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_status_returns_authenticated_when_real_token_present(client, monkeypatch):
    monkeypatch.setenv(
        "CLAUDE_CODE_OAUTH_TOKEN",
        "sk-ant-oat01-" + "a" * 50,
    )
    # Mock the CLI subprocess check — in CI the `claude` binary isn't on
    # PATH (and locally it would make a real API call with the fake token).
    # This test covers the status endpoint's happy path, not the CLI shell-out.
    with patch("apps.common.auth_flow._check_token_via_cli", return_value=True):
        resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"authenticated": True}, "error": None}


def test_status_rejects_placeholder_token(client, monkeypatch):
    monkeypatch.setenv(
        "CLAUDE_CODE_OAUTH_TOKEN",
        "sk-ant-oat01-placeholder-reauth-via-ace-auth-cli",
    )
    resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"authenticated": False}


def test_status_rejects_obviously_short_token(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-short")
    resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"authenticated": False}


def test_status_returns_unauthenticated_when_no_token(client, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with patch("apps.common.auth_flow.load_stored_token", return_value=None):
        resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"authenticated": False}


def test_start_returns_auth_url(client):
    with patch(
        "apps.common.auth_flow.start",
        return_value={
            "auth_url": "https://claude.com/cai/oauth/authorize?x=1",
            "token": None,
            "status": "awaiting_code",
        },
    ):
        resp = client.post("/api/auth/cli/start")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["auth_url"].startswith("https://")
    assert body["status"] == "awaiting_code"


def test_complete_with_code_returns_token(client):
    with patch("apps.common.auth_flow.complete", return_value="sk-ant-oat01-fresh"):
        resp = client.post("/api/auth/cli/complete", {"code": "abc"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "complete"


def test_complete_without_active_session_returns_error(client):
    with patch(
        "apps.common.auth_flow.complete",
        side_effect=RuntimeError("No active auth flow."),
    ):
        resp = client.post("/api/auth/cli/complete", {"code": "abc"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "auth_flow_error"


def test_poll_returns_status(client):
    with patch(
        "apps.common.auth_flow.poll",
        return_value={"active": True, "authenticated": False, "elapsed_seconds": 5},
    ):
        resp = client.get("/api/auth/cli/poll")
    assert resp.status_code == 200
    assert resp.json()["data"]["active"] is True


def test_cancel_invokes_auth_flow_cancel(client):
    with patch("apps.common.auth_flow.cancel") as cancel:
        resp = client.post("/api/auth/cli/cancel")
    assert resp.status_code == 200
    cancel.assert_called_once()
