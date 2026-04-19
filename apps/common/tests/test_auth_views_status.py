import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.common.models import SystemConfig, UserCredential

REAL = "sk-ant-oat01-" + "x" * 40


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="s@dimagi.com")


@pytest.fixture(autouse=True)
def stub_live_check(monkeypatch):
    """Avoid invoking real claude binary and clear env-token leakage."""
    from apps.common import auth_flow
    monkeypatch.setattr(
        auth_flow, "_check_token_via_cli", lambda blob_json=None, on_refresh=None: True
    )
    # Prior tests may have set CLAUDE_CODE_OAUTH_TOKEN as a side effect of
    # calling store_*_credentials_blob; strip it so each test starts clean.
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    # Reset the validate_stored_token cache so results from a prior test
    # don't short-circuit this one.
    auth_flow._invalidate_validation_cache()


@pytest.mark.django_db
def test_status_reports_user_and_global_state(user):
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": REAL}}),
        token_prefix=REAL[:15],
    )
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-" + "g" * 40}}),
    )

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["authenticated"] is True
    assert data["user"]["has_blob"] is True
    assert data["user"]["token_prefix"] == REAL[:15]
    assert data["global"]["has_blob"] is True


@pytest.mark.django_db
def test_status_when_user_has_nothing(user):
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-" + "g" * 40}}),
    )

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get("/api/auth/cli/status")
    data = resp.json()["data"]
    assert data["authenticated"] is True
    assert data["user"]["has_blob"] is False
    assert data["user"].get("token_prefix") is None
    assert data["global"]["has_blob"] is True


@pytest.mark.django_db
def test_status_when_nothing_configured(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get("/api/auth/cli/status")
    data = resp.json()["data"]
    assert data["authenticated"] is False
    assert data["user"]["has_blob"] is False
    assert data["global"]["has_blob"] is False
