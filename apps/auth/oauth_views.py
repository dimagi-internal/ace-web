"""
Connect OAuth Views.

Session-based OAuth implementation for the ACE web / labs AWS environment.
Stores tokens in session instead of database.
"""

import datetime
import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.auth import identity
from apps.auth.oauth import fetch_user_email, fetch_userinfo, introspect_token

logger = logging.getLogger(__name__)


def oauth_initiate(request: HttpRequest) -> HttpResponse:
    """
    Initiate OAuth PKCE flow to Connect production.

    Generates state + code_verifier, stores in session, redirects to
    Connect /o/authorize/ with appropriate query params.
    """
    if not settings.CONNECT_OAUTH_CLIENT_ID or not settings.CONNECT_OAUTH_CLIENT_SECRET:
        logger.error(
            "OAuth not configured — missing CONNECT_OAUTH_CLIENT_ID or "
            "CONNECT_OAUTH_CLIENT_SECRET"
        )
        messages.error(
            request, "OAuth authentication is not configured. Please contact your administrator."
        )
        return redirect("auth:login")

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = request.GET.get("next", settings.FORCE_SCRIPT_NAME or "/")

    # Generate PKCE code verifier and challenge (S256)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    )
    request.session["oauth_code_verifier"] = code_verifier

    # Build callback URL
    callback_url = request.build_absolute_uri(reverse("auth:callback"))

    # Get OAuth scopes from settings
    scopes = getattr(settings, "CONNECT_OAUTH_SCOPES", ["read"])
    scope_string = " ".join(scopes)

    # Build OAuth authorize URL with PKCE
    params = {
        "client_id": settings.CONNECT_OAUTH_CLIENT_ID,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": scope_string,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    authorize_url = f"{settings.CONNECT_PRODUCTION_URL}/o/authorize/?{urlencode(params)}"

    logger.info(
        "Initiating OAuth flow",
        extra={"session": request.session.session_key, "redirect_uri": callback_url},
    )

    return redirect(authorize_url)


def oauth_callback(request: HttpRequest) -> HttpResponse:
    """
    Handle OAuth callback from Connect production.

    Validates state, exchanges code for token, introspects token + fetches
    userinfo, enforces @dimagi.com domain, creates/updates the User row,
    and logs the user in via Django's standard auth.
    """
    # Verify state to prevent CSRF
    state = request.GET.get("state")
    saved_state = request.session.get("oauth_state")

    if not state or state != saved_state:
        logger.warning(
            "OAuth callback with invalid state parameter", extra={"received_state": state}
        )
        messages.error(request, "Invalid authentication state. Please try logging in again.")
        return redirect("auth:login")

    # Get authorization code
    code = request.GET.get("code")
    if not code:
        error = request.GET.get("error", "Unknown error")
        error_description = request.GET.get("error_description", "")
        logger.error(f"OAuth error: {error}", extra={"description": error_description})
        messages.error(request, f"Authentication failed: {error_description or error}")
        return redirect("auth:login")

    # Get PKCE code verifier from session
    code_verifier = request.session.get("oauth_code_verifier")
    if not code_verifier:
        logger.error("OAuth callback missing code verifier in session")
        messages.error(request, "Session expired. Please try logging in again.")
        return redirect("auth:login")

    # Exchange code for token with PKCE
    callback_url = request.build_absolute_uri(reverse("auth:callback"))
    token_url = f"{settings.CONNECT_PRODUCTION_URL}/o/token/"

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url,
        "client_id": settings.CONNECT_OAUTH_CLIENT_ID,
        "client_secret": settings.CONNECT_OAUTH_CLIENT_SECRET,
        "code_verifier": code_verifier,
        # response_type=token tells Connect to return an opaque access token
        # instead of trying to generate a signed JWT ID token (which crashes
        # with 500 when the OAuth app doesn't have OIDC signing keys configured).
        "response_type": "token",
    }

    try:
        response = httpx.post(token_url, data=token_data, timeout=10)
        response.raise_for_status()
        token_json = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"OAuth token exchange failed: status={e.response.status_code} "
            f"body={e.response.text[:500]}",
        )
        messages.error(request, "Failed to authenticate with Connect. Please try again.")
        return redirect("auth:login")
    except Exception as e:
        logger.error(f"OAuth token exchange failed: {str(e)}", exc_info=True)
        messages.error(request, "Authentication service unavailable. Please try again later.")
        return redirect("auth:login")

    # Get user info from Connect production via introspection
    access_token = token_json["access_token"]
    profile_data = introspect_token(
        access_token=access_token,
        client_id=settings.CONNECT_OAUTH_CLIENT_ID,
        client_secret=settings.CONNECT_OAUTH_CLIENT_SECRET,
        production_url=settings.CONNECT_PRODUCTION_URL,
    )

    if not profile_data:
        logger.error("Could not retrieve user information from token introspection")
        messages.error(request, "Could not retrieve your profile from Connect. Please try again.")
        return redirect("auth:login")

    logger.info(f"Introspection profile_data: {profile_data}")

    # Fetch OIDC userinfo for a reliable email address
    userinfo = fetch_userinfo(
        access_token=access_token, production_url=settings.CONNECT_PRODUCTION_URL
    )
    logger.info(f"OIDC userinfo response: {userinfo}")
    if userinfo and userinfo.get("email"):
        profile_data["email"] = userinfo["email"]
        logger.info(f"Got email from OIDC userinfo for {profile_data.get('username')}")

    # Fallback: if introspection and userinfo didn't return an email,
    # try Connect's user API endpoints directly.
    if not profile_data.get("email"):
        api_email = fetch_user_email(
            access_token=access_token,
            production_url=settings.CONNECT_PRODUCTION_URL,
        )
        if api_email:
            profile_data["email"] = api_email

    email = (profile_data.get("email") or "").strip().lower()
    logger.info(f"Final email for admission check: {email!r}")

    # Build display name
    first_name = profile_data.get("first_name", "")
    last_name = profile_data.get("last_name", "")
    display_name = (
        f"{first_name} {last_name}".strip()
        or profile_data.get("username")
        or email.split("@")[0]
    )

    # Read the post-login target before login() — it may flush the session.
    # Default to FORCE_SCRIPT_NAME so the redirect lands on ace-web,
    # not the ALB root (which routes to a different app on shared infra).
    _prefix = settings.FORCE_SCRIPT_NAME or ""
    default_next = f"{_prefix}/" if _prefix else "/"
    next_url = request.session.pop("oauth_next", default_next)
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_code_verifier", None)

    # Admission, linking (by email, case-insensitive), session and auto-join
    # are the SAME code for every sign-in method — apps/auth/identity.py.
    user, refusal = identity.sign_in(
        request, email, method=identity.METHOD_CONNECT,
        display_name=display_name, update_display_name=True,
    )
    if user is None:
        messages.error(request, refusal)
        return redirect("auth:login")

    # Store token info in session (NOT in the database — tokens are short-lived and
    # user-specific, sessions are the right scope). The Django session itself is
    # database-backed in production, so this survives across requests.
    expires_in = token_json.get("expires_in", 1209600)  # default 2 weeks
    request.session["labs_oauth"] = {
        "access_token": access_token,
        "refresh_token": token_json.get("refresh_token", ""),
        "expires_at": (timezone.now() + datetime.timedelta(seconds=expires_in)).timestamp(),
        "user_profile": {
            "email": email,
            "display_name": display_name,
        },
    }

    logger.info(f"Successfully authenticated user {email} via Connect OAuth")

    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/"

    return redirect(next_url)


def oauth_logout(request: HttpRequest) -> HttpResponse:
    """
    Log out the current user, clearing the session, and redirect to login.
    """
    logout(request)
    logger.info("User logged out")
    return redirect("auth:login")


def me(request: HttpRequest) -> HttpResponse:
    """GET /auth/me — return the current authenticated user's identity.

    Used by the SPA on /welcome to show "Logged in as <email>" so a
    user with zero workspace memberships can self-diagnose ("oh, I'm
    on the wrong account") instead of staring at the empty wizard.

    Returns 401 when not authenticated rather than redirecting, since
    the SPA renders this off an XHR.
    """
    from django.http import JsonResponse

    if not request.user.is_authenticated:
        return JsonResponse({"error": "not authenticated"}, status=401)
    user = request.user
    return JsonResponse({
        "user_id": user.pk,
        "email": user.email,
        "display_name": getattr(user, "display_name", "") or user.email,
    })
