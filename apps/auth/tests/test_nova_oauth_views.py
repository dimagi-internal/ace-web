"""End-to-end exercise of the Nova OAuth redirect handlers.

Mocks httpx so we don't actually hit commcare.app, but the view code
runs in full: PKCE generation, state stash, token exchange body, blob
persistence.
"""
from __future__ import annotations

import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.common import nova_auth_flow as nf
from apps.common.models import SystemConfig


@pytest.fixture
def admin_client():
    """Distinct Client per fixture so admin/user_client don't share state."""
    user = get_user_model().objects.create_user(email="admin@dimagi.com")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def user_client():
    user = get_user_model().objects.create_user(email="someone@dimagi.com")
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def bot_client():
    """Automation account on @dimagi-ai.com — not is_staff, but allowed."""
    user = get_user_model().objects.create_user(email="ace@dimagi-ai.com")
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
def test_initiate_redirects_non_admins_to_login(user_client):
    resp = user_client.get("/auth/nova/initiate/")
    # user_passes_test bounces non-admins to LOGIN_URL
    assert resp.status_code == 302
    assert "/auth/login/" in resp["Location"]


@pytest.mark.django_db
def test_initiate_redirects_admin_to_authorize_with_pkce_and_resource(admin_client):
    fake_register = httpx.Response(
        200,
        request=httpx.Request("POST", nf.register_url()),
        json={
            "client_id": "registered-cid",
            "redirect_uris": ["http://testserver/auth/nova/callback/"],
        },
    )
    with patch.object(httpx, "post", return_value=fake_register):
        resp = admin_client.get("/auth/nova/initiate/")

    assert resp.status_code == 302
    parsed = urlparse(resp["Location"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == nf.authorize_url()
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["registered-cid"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["resource"] == [nf.NOVA_DEFAULT_RESOURCE]
    assert qs["scope"] == [nf.NOVA_DEFAULT_SCOPES]
    # PKCE verifier and state must be stashed in the session for the callback.
    session = admin_client.session
    assert "nova_oauth_state" in session
    assert "nova_oauth_verifier" in session
    assert qs["state"] == [session["nova_oauth_state"]]


@pytest.mark.django_db
def test_callback_exchanges_code_and_stores_blob(admin_client):
    # Seed registered client + plant matching state/verifier in session.
    SystemConfig.objects.create(
        key=nf.NOVA_CLIENT_KEY,
        value=json.dumps(
            {
                "client_id": "cid",
                "redirect_uris": ["http://testserver/auth/nova/callback/"],
            }
        ),
    )
    session = admin_client.session
    session["nova_oauth_state"] = "STATE"
    session["nova_oauth_verifier"] = "VERIFIER"
    session.save()

    token_response = httpx.Response(
        200,
        request=httpx.Request("POST", nf.token_url()),
        json={
            "access_token": "jwt-fresh",
            "refresh_token": "rt-fresh",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": nf.NOVA_DEFAULT_SCOPES,
        },
    )
    with patch.object(httpx, "post", return_value=token_response) as mock_post:
        resp = admin_client.get("/auth/nova/callback/?code=AUTHCODE&state=STATE")

    assert resp.status_code == 302
    assert "nova=connected" in resp["Location"]

    # Blob persisted with fresh JWT and correct scope.
    blob = nf.get_blob()
    assert blob["access_token"] == "jwt-fresh"
    assert blob["refresh_token"] == "rt-fresh"
    assert blob["scope"] == nf.NOVA_DEFAULT_SCOPES

    # /token call sent the resource indicator + PKCE verifier.
    sent = mock_post.call_args.kwargs["data"]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "AUTHCODE"
    assert sent["code_verifier"] == "VERIFIER"
    assert sent["resource"] == nf.NOVA_DEFAULT_RESOURCE


@pytest.mark.django_db
def test_callback_state_mismatch_redirects_to_settings_with_error(admin_client):
    session = admin_client.session
    session["nova_oauth_state"] = "REAL"
    session["nova_oauth_verifier"] = "V"
    session.save()

    resp = admin_client.get("/auth/nova/callback/?code=X&state=FORGED")
    assert resp.status_code == 302
    assert "nova=error" in resp["Location"]
    assert "state_mismatch" in resp["Location"]
    # Blob must NOT have been written.
    assert nf.get_blob() is None


@pytest.mark.django_db
def test_status_reports_not_connected_for_empty_db(user_client):
    resp = user_client.get("/api/v2/auth/nova/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["valid"] is False
    assert body["can_manage"] is False  # non-admin


@pytest.mark.django_db
def test_status_reports_connected_and_admin_can_manage(admin_client):
    SystemConfig.objects.create(
        key=nf.NOVA_BLOB_KEY,
        value=json.dumps(
            {
                "access_token": "jwt",
                "refresh_token": "rt",
                "expires_at": 9999999999,
                "scope": "nova.read",
            }
        ),
    )
    # Stub validate_token so we don't actually hit mcp.commcare.app.
    with patch.object(nf, "validate_token", return_value=True):
        resp = admin_client.get("/api/v2/auth/nova/status")

    body = resp.json()
    assert body["connected"] is True
    assert body["valid"] is True
    assert body["can_manage"] is True
    assert body["scope"] == "nova.read"


@pytest.mark.django_db
def test_status_reports_can_manage_for_bot_account(bot_client):
    """ace@dimagi-ai.com should see can_manage=True even without is_staff,
    so scripted rotation of the global blob can run as the bot."""
    resp = bot_client.get("/api/v2/auth/nova/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_manage"] is True


@pytest.mark.django_db
def test_initiate_accepts_bot_account_without_is_staff(bot_client):
    """The OAuth dance must be drivable by the bot — that's the whole point
    of having a single shared identity. Mirrors auth_views._can_write_global."""
    fake_register = httpx.Response(
        200,
        request=httpx.Request("POST", nf.register_url()),
        json={
            "client_id": "bot-cid",
            "redirect_uris": ["http://testserver/auth/nova/callback/"],
        },
    )
    with patch.object(httpx, "post", return_value=fake_register):
        resp = bot_client.get("/auth/nova/initiate/")
    assert resp.status_code == 302
    # Redirect target is commcare.app's authorize endpoint, not /auth/login/.
    assert nf.authorize_url() in resp["Location"]


@pytest.mark.django_db
def test_disconnect_removes_blob_admin_only(admin_client, user_client):
    SystemConfig.objects.create(
        key=nf.NOVA_BLOB_KEY,
        value=json.dumps({"access_token": "jwt", "expires_at": 1}),
    )

    # Non-admin: 403
    resp = user_client.post("/api/v2/auth/nova/disconnect", content_type="application/json")
    assert resp.status_code == 403
    assert nf.get_blob() is not None

    # Admin: 200, blob cleared.
    resp = admin_client.post("/api/v2/auth/nova/disconnect", content_type="application/json")
    assert resp.status_code == 200
    assert nf.get_blob() is None
