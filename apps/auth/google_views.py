"""Google sign-in views. Protocol: google_oauth.py. Policy: identity.py."""
from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.auth import google_oauth, identity
from apps.auth.google_oauth import GoogleAuthError
from apps.auth.models import User

logger = logging.getLogger(__name__)

SESSION_KEY = "google_oauth"


def _default_next() -> str:
    prefix = settings.FORCE_SCRIPT_NAME or ""
    return f"{prefix}/"


def google_initiate(request: HttpRequest) -> HttpResponse:
    """Start Google sign-in (`?mode=link` adds Google to the signed-in account)."""
    if not google_oauth.is_configured():
        raise Http404("Google sign-in is not configured")
    mode = "link" if request.GET.get("mode") == "link" else "login"
    if mode == "link" and not request.user.is_authenticated:
        return redirect("auth:login")

    next_url = request.GET.get("next") or _default_next()
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = _default_next()

    flow = google_oauth.new_flow()
    request.session[SESSION_KEY] = {**flow, "next": next_url, "mode": mode}
    redirect_uri = request.build_absolute_uri(reverse("auth:google_callback"))
    return redirect(google_oauth.authorize_url(flow, redirect_uri))


def google_callback(request: HttpRequest) -> HttpResponse:
    if not google_oauth.is_configured():
        raise Http404("Google sign-in is not configured")
    # Single use: popped whether or not the attempt succeeds.
    flow = request.session.pop(SESSION_KEY, None)
    mode = (flow or {}).get("mode", "login")
    failure = redirect("auth:account" if mode == "link" else "auth:login")

    state = request.GET.get("state", "")
    if not flow or not state or not hmac.compare_digest(state, flow["state"]):
        logger.warning("Google callback with missing or invalid state")
        messages.error(request, "Invalid authentication state. Please try signing in again.")
        return failure
    code = request.GET.get("code")
    if not code:
        logger.info("Google sign-in declined: %s", request.GET.get("error", "unknown"))
        messages.error(request, "Google sign-in was cancelled or failed. Please try again.")
        return failure

    redirect_uri = request.build_absolute_uri(reverse("auth:google_callback"))
    try:
        id_token = google_oauth.exchange_code(code, flow["verifier"], redirect_uri)
        who = google_oauth.verify_id_token(id_token, flow["nonce"])
    except GoogleAuthError as exc:
        messages.error(request, str(exc))
        return failure

    next_url = flow["next"]
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = _default_next()

    if mode == "link":
        error = _link(request, who)
        if error:
            messages.error(request, error)
        else:
            messages.success(request, "Google is now linked to your account.")
        return failure  # the account page, either way

    user, refusal = identity.sign_in(
        request, who.email, method=identity.METHOD_GOOGLE,
        display_name=who.name, google_sub=who.sub,
    )
    if user is None:
        messages.error(request, refusal)
        return failure
    return redirect(next_url)


def _link(request: HttpRequest, who: google_oauth.GoogleIdentity) -> str | None:
    """Attach a verified Google identity to the signed-in user. Error text, or None."""
    user = request.user
    if identity.normalize_email(user.email) != who.email:
        return (
            f"That Google account is {who.email}, but you are signed in as {user.email}. "
            "Choose the Google account with the same email address."
        )
    other = User.objects.filter(google_sub=who.sub).exclude(pk=user.pk).first()
    if other is not None:
        return "That Google account is already linked to another user."
    if user.google_sub and user.google_sub != who.sub:
        return "A different Google account is already linked to this user."
    user.google_sub = who.sub
    user.save(update_fields=["google_sub", "updated_at"])
    return None
