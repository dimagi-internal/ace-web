"""Tests for Nova MCP credential storage + refresh.

Cover the OAuth-spec specifics that make Nova different from the Claude
credential flow: RFC 8707 ``resource`` indicator, refresh-near-expiry
threshold, ``refresh_token`` preservation when the AS doesn't return
a new one.
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import httpx
import pytest

from apps.common import nova_auth_flow as nf
from apps.common.models import SystemConfig


def _seed_client(client_id="cid-123", secret=None, redirect="http://x/cb"):
    blob = {"client_id": client_id, "redirect_uris": [redirect]}
    if secret:
        blob["client_secret"] = secret
    SystemConfig.objects.update_or_create(
        key=nf.NOVA_CLIENT_KEY, defaults={"value": json.dumps(blob)}
    )
    return blob


def _seed_blob(**overrides):
    blob = {
        "access_token": "jwt-old",
        "refresh_token": "rt-1",
        "expires_at": int(time.time()) + 3600,
        "scope": nf.NOVA_DEFAULT_SCOPES,
        "token_type": "Bearer",
    }
    blob.update(overrides)
    SystemConfig.objects.update_or_create(
        key=nf.NOVA_BLOB_KEY, defaults={"value": json.dumps(blob)}
    )
    return blob


@pytest.mark.django_db
def test_store_blob_normalizes_expires_in_to_expires_at():
    nf.store_blob({"access_token": "jwt", "expires_in": 3600, "refresh_token": "rt"})
    stored = nf.get_blob()
    assert "expires_at" in stored
    assert stored["expires_at"] - stored["obtained_at"] == 3600


@pytest.mark.django_db
def test_get_fresh_token_returns_cached_when_well_within_expiry():
    blob = _seed_blob(access_token="jwt-current")
    # No HTTP allowed — if refresh was attempted this would crash.
    with patch.object(httpx, "post", side_effect=AssertionError("no refresh expected")):
        assert nf.get_fresh_token() == "jwt-current"
    assert nf.get_blob()["access_token"] == blob["access_token"]


@pytest.mark.django_db
def test_get_fresh_token_refreshes_within_buffer_window():
    """Token still technically valid but inside the 5-min refresh buffer should refresh."""
    _seed_client(secret="csecret")
    _seed_blob(
        access_token="jwt-old",
        expires_at=int(time.time()) + 60,  # 1 min away — inside the 300s buffer
    )

    fake_response = httpx.Response(
        200,
        request=httpx.Request("POST", nf.token_url()),
        json={
            "access_token": "jwt-new",
            "refresh_token": "rt-2",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": nf.NOVA_DEFAULT_SCOPES,
        },
    )
    with patch.object(httpx, "post", return_value=fake_response) as mock_post:
        token = nf.get_fresh_token()

    assert token == "jwt-new"
    assert nf.get_blob()["access_token"] == "jwt-new"
    assert nf.get_blob()["refresh_token"] == "rt-2"

    # Verify we sent the resource indicator — Nova requires it on /token.
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["data"]["resource"] == nf.NOVA_DEFAULT_RESOURCE
    assert call_kwargs["data"]["grant_type"] == "refresh_token"
    assert call_kwargs["data"]["client_id"] == "cid-123"


@pytest.mark.django_db
def test_refresh_preserves_refresh_token_when_server_omits_it():
    """Some ASes don't return a new refresh_token on refresh; keep the old one."""
    _seed_client()
    _seed_blob(
        access_token="jwt-old",
        refresh_token="rt-keepme",
        expires_at=int(time.time()) - 10,  # already expired
    )

    fake_response = httpx.Response(
        200,
        request=httpx.Request("POST", nf.token_url()),
        json={
            "access_token": "jwt-new",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    with patch.object(httpx, "post", return_value=fake_response):
        nf.get_fresh_token()

    assert nf.get_blob()["refresh_token"] == "rt-keepme"


@pytest.mark.django_db
def test_get_fresh_token_returns_none_when_refresh_fails():
    _seed_client()
    _seed_blob(expires_at=int(time.time()) - 10)

    request = httpx.Request("POST", nf.token_url())
    fake_response = httpx.Response(400, request=request, text="invalid_grant")
    err = httpx.HTTPStatusError("400", request=request, response=fake_response)
    with patch.object(httpx, "post", side_effect=err):
        assert nf.get_fresh_token() is None


@pytest.mark.django_db
def test_get_fresh_token_returns_none_when_no_blob():
    assert nf.get_fresh_token() is None


@pytest.mark.django_db
def test_clear_blob_removes_systemconfig_row():
    _seed_blob()
    nf.clear_blob()
    assert SystemConfig.objects.filter(key=nf.NOVA_BLOB_KEY).count() == 0


@pytest.mark.django_db
def test_get_client_reuses_existing_when_redirect_matches():
    seeded = _seed_client(client_id="cid-A", redirect="http://x/cb")
    # No HTTP allowed — reuse path must not hit the registration endpoint.
    with patch.object(httpx, "post", side_effect=AssertionError("no register expected")):
        client = nf.get_client("http://x/cb")
    assert client["client_id"] == seeded["client_id"]


@pytest.mark.django_db
def test_get_client_re_registers_when_redirect_differs():
    _seed_client(client_id="cid-A", redirect="http://old/cb")
    fake_response = httpx.Response(
        200,
        request=httpx.Request("POST", nf.register_url()),
        json={"client_id": "cid-B", "redirect_uris": ["http://new/cb"]},
    )
    with patch.object(httpx, "post", return_value=fake_response) as mock_post:
        client = nf.get_client("http://new/cb")

    assert client["client_id"] == "cid-B"
    body = mock_post.call_args.kwargs["json"]
    assert body["redirect_uris"] == ["http://new/cb"]
    assert "authorization_code" in body["grant_types"]
    assert "refresh_token" in body["grant_types"]
