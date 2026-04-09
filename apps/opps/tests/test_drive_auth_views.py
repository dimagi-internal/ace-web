"""Tests for the /auth/drive/start and /auth/drive/callback views."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.auth.models import User
from apps.opps.encryption import decrypt_token


@pytest.fixture
def user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(user):
    c = Client()
    c.force_login(user)
    return c


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ACE_DRIVE_OAUTH_REDIRECT_URI="http://testserver/auth/drive/callback",
)
def test_start_redirects_to_google_consent(authed_client):
    response = authed_client.get(reverse("drive-auth-start"))
    assert response.status_code == 302
    parsed = urlparse(response.url)
    assert parsed.netloc == "accounts.google.com"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["client-id"]
    assert qs["response_type"] == ["code"]
    assert "drive.readonly" in qs["scope"][0]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["redirect_uri"] == ["http://testserver/auth/drive/callback"]


def test_start_requires_auth(db):
    client = Client()
    response = client.get(reverse("drive-auth-start"))
    assert response.status_code == 401


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ACE_DRIVE_OAUTH_REDIRECT_URI="http://testserver/auth/drive/callback",
)
def test_callback_exchanges_code_and_stores_token(authed_client, user):
    fake_token_response = {
        "access_token": "access-xyz",
        "refresh_token": "refresh-xyz",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile https://www.googleapis.com/auth/drive.readonly",
    }
    with patch("apps.opps.drive_auth_views._exchange_code", return_value=fake_token_response):
        response = authed_client.get(reverse("drive-auth-callback"), {"code": "abc123"})

    assert response.status_code == 302
    assert response.url == "/opps"

    user.refresh_from_db()
    assert user.drive_token_cache  # non-empty
    assert user.drive_token_refreshed_at is not None
    decrypted = decrypt_token(user.drive_token_cache)
    assert decrypted["access_token"] == "access-xyz"
    assert decrypted["refresh_token"] == "refresh-xyz"
    assert "drive.readonly" in decrypted["scopes"][0] or "drive.readonly" in " ".join(
        decrypted["scopes"]
    )


def test_callback_without_code_returns_400(authed_client):
    response = authed_client.get(reverse("drive-auth-callback"))
    assert response.status_code == 400
    assert "code" in response.json()["error"]["message"].lower()


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_callback_surfaces_exchange_failure(authed_client):
    with patch(
        "apps.opps.drive_auth_views._exchange_code",
        side_effect=RuntimeError("google said no"),
    ):
        response = authed_client.get(reverse("drive-auth-callback"), {"code": "abc"})
    assert response.status_code == 400
    assert "google said no" in response.json()["error"]["message"]
