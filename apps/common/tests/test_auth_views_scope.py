import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.common.models import SystemConfig, UserCredential

REAL = "sk-ant-oat01-" + "x" * 40
BLOB = {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}}


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="u@dimagi.com")


@pytest.fixture
def admin(db):
    u = get_user_model().objects.create_user(email="a@dimagi.com")
    u.is_staff = True
    u.save()
    return u


@pytest.fixture(autouse=True)
def stub_live_check(monkeypatch):
    """Don't invoke real claude binary in upload tests."""
    from apps.common import auth_flow
    monkeypatch.setattr(auth_flow, "_check_token_via_cli", lambda blob_json=None: True)


@pytest.mark.django_db
def test_upload_defaults_to_user_scope(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/auth/cli/upload", BLOB, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["scope"] == "user"
    assert UserCredential.objects.filter(user=user).exists()
    assert not SystemConfig.objects.filter(key="claude_credentials_blob").exists()


@pytest.mark.django_db
def test_global_scope_requires_admin(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/auth/cli/upload?scope=global", BLOB, format="json")
    assert resp.status_code == 403
    assert not SystemConfig.objects.filter(key="claude_credentials_blob").exists()


@pytest.mark.django_db
def test_admin_can_write_global(admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post("/api/auth/cli/upload?scope=global", BLOB, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["scope"] == "global"
    assert SystemConfig.objects.filter(key="claude_credentials_blob").exists()


@pytest.mark.django_db
def test_malformed_blob_rejected(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/auth/cli/upload",
        {"claudeAiOauth": {"accessToken": "not-a-real-token"}},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_blob"


@pytest.mark.django_db
def test_user_upload_persists_validation_state(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/auth/cli/upload", BLOB, format="json")
    assert resp.status_code == 200
    cred = UserCredential.objects.get(user=user)
    assert cred.last_validation_ok is True
    assert cred.last_validated_at is not None


@pytest.mark.django_db
def test_user_upload_persists_validation_failure(user, monkeypatch):
    """When the live check returns False, last_validation_ok must persist as False
    so the resolver falls through to the global fallback."""
    from apps.common import auth_flow
    monkeypatch.setattr(auth_flow, "_check_token_via_cli", lambda blob_json=None: False)

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/auth/cli/upload", BLOB, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["authenticated"] is False

    cred = UserCredential.objects.get(user=user)
    assert cred.last_validation_ok is False
    assert cred.last_validated_at is not None
