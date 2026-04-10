import hashlib

import pytest
from rest_framework.test import APIClient

from apps.auth.models import PersonalToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


def test_create_token_returns_raw(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    assert len(raw) >= 32
    assert token.pk is not None
    assert token.user == user
    assert token.label == "test"
    assert token.revoked_at is None


def test_raw_token_is_not_stored(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()
    assert token.token_hash == expected_hash


def test_lookup_by_raw_token(user):
    raw, created = PersonalToken.create_for_user(user=user, label="test")
    found = PersonalToken.lookup(raw)
    assert found is not None
    assert found.pk == created.pk


def test_lookup_returns_none_for_bad_token(user):
    PersonalToken.create_for_user(user=user, label="test")
    assert PersonalToken.lookup("bad-token-value") is None


def test_lookup_returns_none_for_revoked(user):
    from django.utils import timezone
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    token.revoked_at = timezone.now()
    token.save()
    assert PersonalToken.lookup(raw) is None


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_create_token_endpoint(client):
    resp = client.post("/api/auth/tokens", {"label": "my laptop"}, format="json")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "raw_token" in body
    assert body["label"] == "my laptop"
    assert len(body["raw_token"]) >= 32


def test_list_tokens_endpoint(client, user):
    PersonalToken.create_for_user(user=user, label="token1")
    PersonalToken.create_for_user(user=user, label="token2")
    resp = client.get("/api/auth/tokens")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 2
    for item in items:
        assert "raw_token" not in item
        assert "token_hash" not in item
        assert "label" in item


def test_delete_token_endpoint(client, user):
    _, token = PersonalToken.create_for_user(user=user, label="to delete")
    resp = client.delete(f"/api/auth/tokens/{token.pk}")
    assert resp.status_code == 204
    token.refresh_from_db()
    assert token.revoked_at is not None


def test_delete_token_404_for_other_user(client, django_user_model):
    other = django_user_model.objects.create_user(
        email="other@example.com", display_name="other"
    )
    _, token = PersonalToken.create_for_user(user=other, label="theirs")
    resp = client.delete(f"/api/auth/tokens/{token.pk}")
    assert resp.status_code == 404


def test_bearer_auth_resolves_user(user):
    raw, _ = PersonalToken.create_for_user(user=user, label="test")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    resp = c.get("/api/sessions")
    assert resp.status_code == 200


def test_bearer_auth_rejects_revoked(user):
    from django.utils import timezone
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    token.revoked_at = timezone.now()
    token.save()
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    resp = c.get("/api/sessions")
    assert resp.status_code == 403


def test_bearer_auth_rejects_bad_token():
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer bad-token-value")
    resp = c.get("/api/sessions")
    assert resp.status_code == 403


def test_bearer_auth_updates_last_used(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    assert token.last_used_at is None
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    c.get("/api/sessions")
    token.refresh_from_db()
    assert token.last_used_at is not None
