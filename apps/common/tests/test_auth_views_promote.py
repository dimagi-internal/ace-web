import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.common.models import SystemConfig, UserCredential

REAL = "sk-ant-oat01-" + "x" * 40


@pytest.fixture(autouse=True)
def stub_live_check(monkeypatch):
    """Avoid the real claude binary."""
    from apps.common import auth_flow
    monkeypatch.setattr(auth_flow, "_check_token_via_cli", lambda blob_json=None: True)


@pytest.fixture
def admin(db):
    u = get_user_model().objects.create_user(email="a@dimagi.com")
    u.is_staff = True
    u.save()
    UserCredential.objects.create(
        user=u,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": REAL}}),
        token_prefix=REAL[:15],
    )
    return u


@pytest.fixture
def non_admin(db):
    return get_user_model().objects.create_user(email="u@dimagi.com")


@pytest.mark.django_db
def test_admin_promote_copies_user_blob_to_global(admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post("/api/auth/cli/promote")
    assert resp.status_code == 200, resp.content
    row = SystemConfig.objects.get(key="claude_credentials_blob")
    assert REAL in row.value
    assert resp.json()["data"]["promoted"] is True
    assert resp.json()["data"]["token_prefix"] == REAL[:15]


@pytest.mark.django_db
def test_non_admin_cannot_promote(non_admin):
    client = APIClient()
    client.force_authenticate(user=non_admin)
    resp = client.post("/api/auth/cli/promote")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_promote_fails_when_admin_has_no_personal_blob(db):
    admin = get_user_model().objects.create_user(email="a2@dimagi.com")
    admin.is_staff = True
    admin.save()
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post("/api/auth/cli/promote")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_personal_blob"
