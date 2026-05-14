"""Contract tests for apps.service_accounts.api_v2."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

_FAKE_TOKEN = {
    "id": 1,
    "name": "my-token",
    "created_at": "2026-05-14T09:00:00Z",
    "last_used_at": None,
}

_FAKE_TOKEN_CREATED = {
    **_FAKE_TOKEN,
    "raw_token": "ace-tok-abc123",
}


@pytest.fixture
def auth_client(db, client):
    user = User.objects.create_user(email="tokenuser@example.com")
    client.force_login(user)
    return client, user


@pytest.fixture
def anon_client(db, client):
    return client


# ---------------------------------------------------------------------------
# GET /tokens
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_tokens_200(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.service_accounts.api_v2.list_personal_tokens",
        lambda user: [_FAKE_TOKEN],
    )
    resp = client.get("/api/v2/tokens")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "my-token"


@pytest.mark.django_db
def test_list_tokens_anon_401(anon_client):
    resp = anon_client.get("/api/v2/tokens")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /tokens
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_token_201(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.service_accounts.api_v2.create_personal_token",
        lambda user, name: {**_FAKE_TOKEN_CREATED, "name": name},
    )
    resp = client.post(
        "/api/v2/tokens",
        {"name": "ci-token"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "ci-token"
    assert "raw_token" in body


@pytest.mark.django_db
def test_create_token_anon_401(anon_client):
    resp = anon_client.post(
        "/api/v2/tokens",
        {"name": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /tokens/{id}
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_token_204(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.service_accounts.api_v2.revoke_personal_token",
        lambda user, token_id: True,
    )
    resp = client.delete("/api/v2/tokens/1")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_revoke_token_404(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(
        "apps.service_accounts.api_v2.revoke_personal_token",
        lambda user, token_id: False,
    )
    resp = client.delete("/api/v2/tokens/999")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_revoke_token_anon_401(anon_client):
    resp = anon_client.delete("/api/v2/tokens/1")
    assert resp.status_code == 401
