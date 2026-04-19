"""Tests for /api/auth/cli/* endpoints."""
import json
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
    # The status endpoint runs a live ``claude -p`` subprocess. Mock the
    # CLI check so the unit test doesn't need a real Claude binary.
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


# ── upload endpoint ───────────────────────────────────────────────


def _full_blob():
    return {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-" + "a" * 90,
            "refreshToken": "rt-" + "b" * 30,
            "expiresAt": 1_700_000_000,
            "scopes": ["user:inference"],
        }
    }


def test_upload_rejects_unauthenticated():
    resp = APIClient().post("/api/auth/cli/upload", _full_blob(), format="json")
    assert resp.status_code in (401, 403)


def test_upload_stores_blob_and_returns_live_status(
    django_user_model, tmp_path, settings, monkeypatch
):
    """Global-scope upload writes the SystemConfig row and credentials file.

    scope=global requires is_staff, so use a dedicated staff user here
    (the default ``client`` fixture's user is non-staff).
    """
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    staff = django_user_model.objects.create_user(
        email="staff@example.com", display_name="staff"
    )
    staff.is_staff = True
    staff.save()
    c = APIClient()
    c.force_authenticate(user=staff)

    blob = _full_blob()
    with patch("apps.common.auth_flow._check_token_via_cli", return_value=True):
        resp = c.post("/api/auth/cli/upload?scope=global", blob, format="json")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stored"] is True
    assert data["authenticated"] is True
    assert data["token_prefix"].startswith("sk-ant-oat01-")
    assert data["scope"] == "global"

    from apps.common.models import SystemConfig
    stored = SystemConfig.objects.get(key="claude_credentials_blob")
    assert json.loads(stored.value) == blob
    assert (tmp_path / ".claude" / ".credentials.json").exists()


def test_upload_accepts_bare_inner_blob_and_wraps_it(client, tmp_path, settings, monkeypatch):
    """CLI tools sometimes hand us the inner ``claudeAiOauth`` value directly."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    inner = _full_blob()["claudeAiOauth"]
    with patch("apps.common.auth_flow._check_token_via_cli", return_value=True):
        resp = client.post("/api/auth/cli/upload", inner, format="json")
    assert resp.status_code == 200


def test_upload_rejects_missing_access_token(client):
    resp = client.post(
        "/api/auth/cli/upload",
        {"claudeAiOauth": {"refreshToken": "nope"}},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_blob"


def test_upload_reports_live_check_failure(client, tmp_path, settings, monkeypatch):
    """Server stored the blob but the live CLI check failed — return
    authenticated=False so the CLI tool can show a warning."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    settings.ACE_CLAUDE_HOME = str(tmp_path)

    with patch("apps.common.auth_flow._check_token_via_cli", return_value=False):
        resp = client.post("/api/auth/cli/upload", _full_blob(), format="json")
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        **resp.json()["data"],
        "stored": True,
        "authenticated": False,
    }


def test_expected_shape_is_public(django_user_model):
    """The shape endpoint is unauth'd so the CLI tool can introspect."""
    resp = APIClient().get("/api/auth/cli/expected-shape")
    assert resp.status_code == 200
    assert "claudeAiOauth" in resp.json()["data"]["shape"]
