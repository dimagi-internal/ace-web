"""Nova OAuth (commcare.app) — server-side authorization_code + PKCE flow.

The HTML/redirect handlers — initiate the dance, catch the callback,
store the blob, return the user to /settings. Restricted to staff +
ACE automation accounts (``ace@dimagi-ai.com``) so the single shared
credential blob isn't trampled by random users; the bot identity needs
the same privilege so an admin script can rotate Nova auth without a
human in the loop. Mirrors the
``apps.common.auth_views._can_write_global`` rule for the Claude
credentials.

JSON status / disconnect endpoints live in apps/common/auth_views.py
under /api/auth/nova/* alongside the Claude credential ones.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps.common import nova_auth_flow as nf
from apps.common.auth_views import _can_write_global

logger = logging.getLogger(__name__)


def _staff_required(view):
    return login_required(user_passes_test(_can_write_global)(view))


def _settings_redirect(query: str = "") -> HttpResponse:
    prefix = settings.FORCE_SCRIPT_NAME or ""
    target = f"{prefix}/settings" if prefix else "/settings"
    if query:
        target = f"{target}?{query}"
    return redirect(target)


@_staff_required
def nova_oauth_initiate(request: HttpRequest) -> HttpResponse:
    callback_url = request.build_absolute_uri(reverse("auth:nova_callback"))
    try:
        client = nf.get_client(callback_url)
    except httpx.HTTPError as e:
        logger.error("nova: dynamic client registration failed — %s", e)
        return _settings_redirect("nova=error&reason=registration_failed")

    verifier = secrets.token_urlsafe(64)
    challenge = (
        urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    state = secrets.token_urlsafe(32)
    request.session["nova_oauth_state"] = state
    request.session["nova_oauth_verifier"] = verifier

    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": callback_url,
        "scope": nf.scopes(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": nf.resource(),
        "prompt": "consent",
    }
    return redirect(f"{nf.authorize_url()}?{urlencode(params)}")


@_staff_required
def nova_oauth_callback(request: HttpRequest) -> HttpResponse:
    state = request.GET.get("state")
    saved_state = request.session.pop("nova_oauth_state", None)
    verifier = request.session.pop("nova_oauth_verifier", None)

    if not state or state != saved_state:
        return _settings_redirect("nova=error&reason=state_mismatch")

    if "error" in request.GET:
        logger.warning(
            "nova: callback returned error=%s description=%s",
            request.GET.get("error"),
            request.GET.get("error_description", ""),
        )
        return _settings_redirect(f"nova=error&reason={request.GET.get('error')}")

    code = request.GET.get("code")
    if not code or not verifier:
        return _settings_redirect("nova=error&reason=missing_code")

    callback_url = request.build_absolute_uri(reverse("auth:nova_callback"))
    client = nf.get_stored_client()
    if not client:
        return _settings_redirect("nova=error&reason=no_client")

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url,
        "client_id": client["client_id"],
        "code_verifier": verifier,
        "resource": nf.resource(),
    }
    if client.get("client_secret"):
        body["client_secret"] = client["client_secret"]

    try:
        resp = httpx.post(nf.token_url(), data=body, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("nova: token exchange failed — %s", e)
        return _settings_redirect("nova=error&reason=token_exchange_failed")

    nf.store_blob(resp.json())
    logger.info("nova: stored fresh credential blob for user=%s", request.user.email)
    return _settings_redirect("nova=connected")
