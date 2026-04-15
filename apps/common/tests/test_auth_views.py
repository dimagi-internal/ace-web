"""Tests for /api/auth/cli/* endpoints."""
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


def test_status_returns_authenticated_when_token_present(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-yes")
    resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"authenticated": True}, "error": None}


def test_status_returns_unauthenticated_when_no_token(client, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with patch("apps.common.auth_flow.load_stored_token", return_value=None):
        resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"authenticated": False}


def test_set_token_stores_valid_token(client):
    with patch("apps.common.auth_flow.store_token") as store:
        resp = client.post(
            "/api/auth/cli/token",
            {"token": "sk-ant-oat01-new"},
            format="json",
        )
    assert resp.status_code == 200
    assert resp.json()["data"] == {"authenticated": True}
    store.assert_called_once_with("sk-ant-oat01-new")


def test_set_token_rejects_invalid_token(client):
    resp = client.post("/api/auth/cli/token", {"token": "nope"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_token"


def test_set_token_rejects_missing_token(client):
    resp = client.post("/api/auth/cli/token", {}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_token"
