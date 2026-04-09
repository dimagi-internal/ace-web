"""Tests for the OAuth credentials builder and refresh wrapper."""
from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings

from apps.opps.drive_credentials import (
    CredentialsRefreshFailed,
    build_credentials,
    ensure_fresh,
)


def _fake_token_data(expiry: datetime | None = None) -> dict:
    return {
        "access_token": "access-123",
        "refresh_token": "refresh-456",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "expiry": expiry.isoformat() if expiry else None,
    }


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_build_credentials_includes_client_id_and_secret():
    creds = build_credentials(_fake_token_data())
    assert creds.client_id == "client-id"
    assert creds.client_secret == "client-secret"
    assert creds.token == "access-123"
    assert creds.refresh_token == "refresh-456"


def test_ensure_fresh_returns_unchanged_when_not_expired():
    future = datetime.now(UTC) + timedelta(hours=1)
    token_data = _fake_token_data(expiry=future)

    with override_settings(
        ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
        ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ):
        creds, updated = ensure_fresh(token_data)
        assert creds.token == "access-123"
        assert updated is None  # nothing to persist


def test_ensure_fresh_refreshes_when_expired(monkeypatch):
    past = datetime.now(UTC) - timedelta(hours=1)
    token_data = _fake_token_data(expiry=past)

    # Patch the Credentials.refresh method to simulate a successful refresh.
    def fake_refresh(self, request):
        self.token = "access-NEW"
        self.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", fake_refresh
    )

    with override_settings(
        ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
        ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ):
        creds, updated = ensure_fresh(token_data)
        assert creds.token == "access-NEW"
        assert updated is not None
        assert updated["access_token"] == "access-NEW"
        assert updated["refresh_token"] == "refresh-456"  # preserved


def test_ensure_fresh_raises_when_refresh_fails(monkeypatch):
    past = datetime.now(UTC) - timedelta(hours=1)
    token_data = _fake_token_data(expiry=past)

    def boom(self, request):
        raise RuntimeError("refresh endpoint rejected the grant")

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", boom)

    with override_settings(
        ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
        ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ):
        with pytest.raises(CredentialsRefreshFailed):
            ensure_fresh(token_data)


@override_settings(ACE_GOOGLE_OAUTH_CLIENT_ID="", ACE_GOOGLE_OAUTH_CLIENT_SECRET="")
def test_build_credentials_raises_without_client_config():
    with pytest.raises(RuntimeError, match="not configured"):
        build_credentials(_fake_token_data())
