"""Django Ninja v2 router for the auth JSON surface.

Only JSON-returning endpoints are ported here. Browser-redirect endpoints
(Connect OAuth initiate/callback, Nova OAuth initiate/callback,
and the HTML login page) stay as plain Django views.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import Router

from apps.api.auth import session_auth
from apps.api.errors import TYPE_FORBIDDEN, ProblemError

from .schemas import (
    CliAuthExpectedShapeOut,
    CliAuthPromoteOut,
    CliAuthStatusOut,
    CliAuthUploadOut,
    MeOut,
    NovaAuthStatusOut,
)

router = Router(tags=["auth"])


# ---------------------------------------------------------------------------
# GET /auth/me — current user info (authenticated)
# ---------------------------------------------------------------------------


def get_me_data(user) -> dict:
    """Return MeOut-compatible dict for the requesting user.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.workspaces.permissions import user_workspaces

    workspaces = user_workspaces(user)
    return {
        "id": user.pk,
        "email": user.email,
        "display_name": getattr(user, "display_name", "") or user.email,
        "is_staff": bool(user.is_staff),
        "workspaces": [
            {"slug": ws.slug, "name": ws.display_name} for ws in workspaces
        ],
    }


@router.get("/me", auth=session_auth, response={200: MeOut}, summary="Current user info")
def me(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    data = get_me_data(request.user)
    payload = MeOut.model_validate(data).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /auth/logout — logout (clears session)
# ---------------------------------------------------------------------------


@router.post("/logout", auth=session_auth, summary="Logout")
def logout(request: HttpRequest) -> HttpResponse:
    from django.contrib.auth import logout as auth_logout

    auth_logout(request)
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# POST /auth/pat-to-session — trade a PAT for a session cookie
# ---------------------------------------------------------------------------


@router.post(
    "/pat-to-session",
    auth=session_auth,
    summary="Trade a Bearer PAT for a Django session cookie",
)
def pat_to_session(request: HttpRequest) -> HttpResponse:
    """Set a session cookie for the Bearer-authenticated caller.

    Browsers can't set custom headers on WebSocket handshakes, so
    PAT-only clients can't connect to Channels routes (the ASGI auth
    middleware only sees the cookie jar from a browser-driven WS). This
    endpoint bridges that gap: a scripted client mints a PAT, calls
    /pat-to-session once with the Bearer header, and the response sets
    the same session cookie a regular OAuth login would have set. From
    that point the client can hand the cookie to a browser context
    (Playwright, etc.) and full session-based auth — including
    WebSockets — Just Works.

    The Bearer-token side of ``DjangoSessionAuth`` resolves the user
    before this view runs, so any valid PAT-bearer caller succeeds.
    """
    from django.contrib.auth import login

    # PersonalToken records have a single backend in ``AUTHENTICATION_BACKENDS``
    # for ace-web, so we don't need to specify which backend authenticated.
    login(request, request.user)
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# GET /auth/cli/status — CLI auth status
# ---------------------------------------------------------------------------


def get_cli_auth_status(user) -> dict:
    """Return CLI auth status dict.

    The monkeypatch target in contract tests is this module-level function.
    """
    from django.conf import settings as _s

    if getattr(_s, "ACE_USE_FAKE_CLI_BACKEND", False):
        return {
            "authenticated": True,
            "user": {"has_blob": False, "token_prefix": None},
            "global_": {"has_blob": False},
        }

    from apps.common import auth_flow
    from apps.common.models import SystemConfig, UserCredential

    cred = UserCredential.objects.filter(user=user).first()
    user_panel = {
        "has_blob": cred is not None,
        "token_prefix": cred.token_prefix if cred else None,
    }
    global_row = SystemConfig.objects.filter(key=auth_flow._BLOB_DB_KEY).first()  # noqa: SLF001
    global_panel = {"has_blob": global_row is not None}
    authenticated = auth_flow.validate_stored_token(user=user)
    return {
        "authenticated": authenticated,
        "user": user_panel,
        "global_": global_panel,
    }


@router.get(
    "/cli/status",
    auth=session_auth,
    response={200: CliAuthStatusOut},
    summary="CLI auth status",
)
def cli_auth_status(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    data = get_cli_auth_status(request.user)
    payload = CliAuthStatusOut.model_validate(data).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /auth/cli/upload — CLI credential upload
# ---------------------------------------------------------------------------


def upload_cli_credentials(user, blob: dict, scope: str) -> dict:
    """Store the CLI credential blob.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.common import auth_flow
    from apps.common.auth_views import _can_write_global

    if scope not in ("user", "global"):
        raise ProblemError(400, "scope must be 'user' or 'global'")

    if scope == "global" and not _can_write_global(user):
        raise ProblemError(
            403,
            "Global scope requires staff or automation account",
            type_=TYPE_FORBIDDEN,
        )

    if not isinstance(blob, dict):
        raise ProblemError(400, "Body must be a JSON object")

    if "claudeAiOauth" not in blob and "accessToken" in blob:
        blob = {"claudeAiOauth": blob}

    try:
        if scope == "user":
            token = auth_flow.store_user_credentials_blob(user, blob)
            authenticated = auth_flow.validate_stored_token(user=user)
        else:
            token = auth_flow.store_credentials_blob(blob)
            authenticated = auth_flow.validate_stored_token()
    except ValueError as exc:
        raise ProblemError(400, str(exc)) from exc

    return {
        "stored": True,
        "authenticated": authenticated,
        "token_prefix": token[:15],
        "scope": scope,
    }


@router.post(
    "/cli/upload",
    auth=session_auth,
    response={200: CliAuthUploadOut},
    summary="Upload CLI credentials",
)
def cli_auth_upload(
    request: HttpRequest,
    scope: str = "user",
) -> HttpResponse:
    import json as _json

    from django.http import JsonResponse

    try:
        blob = _json.loads(request.body or b"{}")
    except _json.JSONDecodeError as exc:
        raise ProblemError(400, "Body must be valid JSON") from exc

    result = upload_cli_credentials(request.user, blob, scope)
    payload = CliAuthUploadOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /auth/nova/status — Nova OAuth status
# ---------------------------------------------------------------------------


def get_nova_status(user) -> dict:
    """Return Nova auth status dict.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.common import nova_auth_flow
    from apps.common.auth_views import _can_write_global

    blob = nova_auth_flow.get_blob()
    if not blob:
        return {
            "connected": False,
            "valid": False,
            "expires_at": None,
            "scope": None,
            "can_manage": _can_write_global(user),
        }
    valid = nova_auth_flow.validate_token()
    # Normalise expires_at: the blob may store a unix-epoch integer or an ISO
    # string.  Pydantic expects str | None for NovaAuthStatusOut.
    raw_expires = blob.get("expires_at")
    if isinstance(raw_expires, (int, float)):
        import datetime
        expires_at: str | None = datetime.datetime.fromtimestamp(
            raw_expires, tz=datetime.UTC
        ).isoformat()
    else:
        expires_at = raw_expires  # already a string or None
    return {
        "connected": True,
        "valid": valid,
        "expires_at": expires_at,
        "scope": blob.get("scope"),
        "can_manage": _can_write_global(user),
    }


@router.get(
    "/nova/status",
    auth=session_auth,
    response={200: NovaAuthStatusOut},
    summary="Nova OAuth status",
)
def nova_auth_status(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    data = get_nova_status(request.user)
    payload = NovaAuthStatusOut.model_validate(data).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /auth/nova/disconnect — disconnect Nova OAuth (admin)
# ---------------------------------------------------------------------------


@router.post("/nova/disconnect", auth=session_auth, summary="Disconnect Nova OAuth (admin)")
def nova_auth_disconnect(request: HttpRequest) -> HttpResponse:
    import logging

    from django.http import JsonResponse

    from apps.common import nova_auth_flow
    from apps.common.auth_views import _can_write_global

    log = logging.getLogger(__name__)
    if not _can_write_global(request.user):
        raise ProblemError(
            403,
            "Disconnect requires staff or automation account",
            type_=TYPE_FORBIDDEN,
        )
    nova_auth_flow.clear_blob()
    log.info("nova: cleared global blob (admin=%s)", request.user.email)
    return JsonResponse({"disconnected": True})


# ---------------------------------------------------------------------------
# POST /auth/cli/promote — promote user credential blob to global scope
# ---------------------------------------------------------------------------


def promote_cli_credentials(user) -> dict:
    """Copy the caller's UserCredential blob to the global SystemConfig row.

    The monkeypatch target in contract tests is this module-level function.
    """
    import json as _json

    from apps.common import auth_flow
    from apps.common.auth_views import _can_write_global
    from apps.common.models import UserCredential

    if not _can_write_global(user):
        raise ProblemError(
            403,
            "Promote requires staff or automation account",
            type_=TYPE_FORBIDDEN,
        )

    cred = UserCredential.objects.filter(user=user).first()
    if cred is None:
        raise ProblemError(400, "No personal blob to promote — upload one first")

    try:
        blob = _json.loads(cred.blob_encrypted)
    except ValueError as exc:
        raise ProblemError(400, "Personal blob is corrupt") from exc

    try:
        auth_flow.store_credentials_blob(blob)
        authenticated = auth_flow.validate_stored_token()
    except ValueError as exc:
        raise ProblemError(400, str(exc)) from exc

    return {
        "promoted": True,
        "authenticated": authenticated,
        "token_prefix": cred.token_prefix,
    }


@router.post(
    "/cli/promote",
    auth=session_auth,
    response={200: CliAuthPromoteOut},
    summary="Promote user CLI credential to global scope (staff/automation only)",
)
def cli_auth_promote(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    result = promote_cli_credentials(request.user)
    payload = CliAuthPromoteOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /auth/cli/expected-shape — public schema introspection
# ---------------------------------------------------------------------------

_EXPECTED_BLOB_SHAPE = {
    "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-<...>",
        "refreshToken": "<...>",
        "expiresAt": 0,
        "scopes": [],
    },
}


@router.get(
    "/cli/expected-shape",
    auth=None,
    response={200: CliAuthExpectedShapeOut},
    summary="Expected CLI credential blob shape (public)",
)
def cli_auth_expected_shape(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    payload = CliAuthExpectedShapeOut.model_validate({"shape": _EXPECTED_BLOB_SHAPE}).model_dump(
        mode="json"
    )
    return JsonResponse(payload)
