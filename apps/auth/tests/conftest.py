"""Shared fixtures for the sign-in tests: one gate, three methods."""
from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client
from django.utils import timezone

from apps.auth.models import User

GOOGLE_CLIENT_ID = "google-client-id"


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def google_cfg(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = GOOGLE_CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"


@pytest.fixture(scope="session")
def google_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google_signin(google_cfg, google_key):
    """`signin(client, **claims)` → the callback response for a Google sign-in.

    Runs the real initiate → callback round trip; only Google's two network
    endpoints are faked (token exchange, JWKS), so the ID token is genuinely
    RS256-signed and verified. Pass a claim as None to drop it.
    """

    def signin(client, *, flow_next=None, mode=None, state="auto", key=None, **claims):
        url = "/auth/google/initiate/"
        params = {k: v for k, v in {"next": flow_next, "mode": mode}.items() if v}
        client.get(url, params)
        flow = client.session["google_oauth"]
        now = timezone.now()
        body = {
            "iss": "https://accounts.google.com",
            "aud": GOOGLE_CLIENT_ID,
            "sub": "google-sub-1",
            "email": "person@example.com",
            "email_verified": True,
            "name": "Pat Person",
            "nonce": flow["nonce"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        }
        body.update(claims)
        body = {k: v for k, v in body.items() if v is not None}
        token = jwt.encode(body, key or google_key, algorithm="RS256")

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"id_token": token}

        with patch("apps.auth.google_oauth.httpx.post", return_value=_Resp()) as post, \
             patch("apps.auth.google_oauth._signing_key", return_value=google_key.public_key()):
            resp = client.get(
                "/auth/google/callback/",
                {"state": flow["state"] if state == "auto" else state, "code": "authcode"},
            )
        signin.last_post = post
        return resp

    return signin


@pytest.fixture
def workspace(db):
    from apps.workspaces.models import Workspace

    owner = User.objects.create(email="owner@dimagi.com", display_name="Owner")
    return Workspace.objects.create(
        slug="spark", display_name="Spark", drive_root_folder_id="f-spark", created_by=owner
    )


@pytest.fixture
def restricted(settings):
    """Invite-only mode: only @dimagi.com is admitted by domain."""
    settings.ACE_ALLOWED_EMAIL_DOMAINS = ["dimagi.com"]


def invite(workspace, email, *, role="viewer", **kw):
    from apps.workspaces.models import WorkspaceInvite

    return WorkspaceInvite.objects.create(
        workspace=workspace, email=email, role=role, invited_by=workspace.created_by,
        expires_at=kw.pop("expires_at", timezone.now() + timedelta(days=7)), **kw,
    )
