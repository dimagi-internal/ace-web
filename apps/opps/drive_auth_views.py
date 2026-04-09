"""Google OAuth flow views for the secondary Drive-scope authorization.

Two views:

- `GET /auth/drive/start` — redirects the logged-in user to Google's consent
  screen for Drive readonly + Sheets readonly access. Requires identity auth.

- `GET /auth/drive/callback?code=...` — exchanges the code for tokens, encrypts
  them, stores on the User, and redirects back to `/opps`.

The pattern matches ../connect-search/backend/app/api/auth.py, translated from
FastAPI to Django function views. The main semantic difference: connect-search
uses a single Google OAuth flow for BOTH identity and Drive access; ace-web
separates them — identity is handled by the hand-rolled CommCare Connect OAuth flow
(pattern ported from connect-labs), Drive is a secondary scoped grant layered on top.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.common.envelope import error_response
from apps.opps.encryption import encrypt_token

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _build_consent_url() -> str:
    params = {
        "client_id": settings.ACE_GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.ACE_DRIVE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(settings.ACE_DRIVE_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _exchange_code(code: str) -> dict:
    """Exchange an auth code for a token response. Separate function so tests can patch it."""
    data = {
        "code": code,
        "client_id": settings.ACE_GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.ACE_GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.ACE_DRIVE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    response = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=10.0)
    if response.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {response.text}")
    return response.json()


@api_view(["GET"])
def start(request):
    """Redirect the logged-in user to Google's Drive-scope consent screen."""
    if not request.user.is_authenticated:
        return Response(error_response("authentication required", code="auth-required"), status=401)
    return HttpResponseRedirect(_build_consent_url())


@api_view(["GET"])
def callback(request):
    """Exchange the auth code, store the encrypted token, redirect to /opps."""
    if not request.user.is_authenticated:
        return Response(error_response("authentication required", code="auth-required"), status=401)

    code = request.GET.get("code", "")
    if not code:
        return Response(
            error_response("missing code parameter", code="missing-code"), status=400
        )

    try:
        token_response = _exchange_code(code)
    except RuntimeError as exc:
        return Response(error_response(str(exc), code="token-exchange-failed"), status=400)

    # Derive expiry from expires_in (seconds).
    expires_in = token_response.get("expires_in")
    expiry_iso = None
    if expires_in:
        expiry_dt = datetime.now(UTC) + timedelta(seconds=int(expires_in))
        expiry_iso = expiry_dt.isoformat()

    scope_str = token_response.get("scope", "")
    scopes = scope_str.split() if scope_str else list(settings.ACE_DRIVE_OAUTH_SCOPES)

    token_data = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token"),
        "token_uri": GOOGLE_TOKEN_URL,
        "scopes": scopes,
        "expiry": expiry_iso,
    }

    user = request.user
    user.drive_token_cache = encrypt_token(token_data)
    user.drive_token_refreshed_at = datetime.now(UTC)
    user.save(update_fields=["drive_token_cache", "drive_token_refreshed_at"])

    return HttpResponseRedirect("/opps")
