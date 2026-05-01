"""REST endpoints for Claude CLI credential management.

Two endpoints:
  * GET  /api/auth/cli/status  — is the stored token working right now?
  * POST /api/auth/cli/upload  — accept a credential blob from the CLI tool

The previous PTY-driven setup-token flow (``/api/auth/cli/start``,
``/complete``, ``/poll``, ``/cancel``) has been removed. See commit
history + docs/deploy.md for why.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import auth_flow
from .envelope import error_response, success_response

logger = logging.getLogger(__name__)

# Domain reserved for ACE automation identities (e.g. ace@dimagi-ai.com,
# the canonical e2e bot per CLAUDE.md). These accounts manage the shared
# global credential blob without needing is_staff, so automation can
# rotate the instance-wide subscription on its own.
_AUTOMATION_EMAIL_DOMAIN = "@dimagi-ai.com"


def _can_write_global(user) -> bool:
    if user.is_staff:
        return True
    email = (user.email or "").lower()
    return email.endswith(_AUTOMATION_EMAIL_DOMAIN)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_status(request: Request) -> Response:
    # When the FakeCLIBackend is enabled (E2E tests, dev), the chat
    # backend doesn't need a real Claude token — report as authenticated
    # so the SendBox doesn't disable itself.
    if getattr(settings, "ACE_USE_FAKE_CLI_BACKEND", False):
        return Response(success_response({
            "authenticated": True,
            "user": {"has_blob": False, "token_prefix": None},
            "global": {"has_blob": False},
        }))

    from .models import SystemConfig, UserCredential

    cred = UserCredential.objects.filter(user=request.user).first()
    user_panel = {
        "has_blob": cred is not None,
        "token_prefix": cred.token_prefix if cred else None,
    }

    global_row = SystemConfig.objects.filter(key=auth_flow._BLOB_DB_KEY).first()
    global_panel = {"has_blob": global_row is not None}

    # "authenticated" reflects whatever the chat path will actually pick for
    # this user — user blob first, else global.
    authenticated = auth_flow.validate_stored_token(user=request.user)

    return Response(
        success_response({
            "authenticated": authenticated,
            "user": user_panel,
            "global": global_panel,
        })
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_upload(request: Request) -> Response:
    """Accept a credential blob and persist it at user or global scope.

    Intended caller: ``scripts/ace_cli_login.py`` running on a developer's
    laptop, reading from the local macOS Keychain or Linux
    ``~/.claude/.credentials.json``. Authentication is via session cookie
    (from a prior Connect OAuth login) or a personal Bearer token minted
    at ``/settings``.

    Default scope is ``user`` (writes the caller's ``UserCredential`` row).
    ``?scope=global`` writes the shared ``SystemConfig`` blob but requires
    ``is_staff``.
    """
    scope = request.query_params.get("scope", "user")
    if scope not in ("user", "global"):
        return Response(
            error_response(message="scope must be 'user' or 'global'", code="bad_scope"),
            status=400,
        )
    if scope == "global" and not _can_write_global(request.user):
        return Response(
            error_response(
                message="global scope requires staff or automation account",
                code="forbidden",
            ),
            status=403,
        )

    blob = request.data
    if not isinstance(blob, dict):
        return Response(
            error_response(message="body must be a JSON object", code="bad_request"),
            status=400,
        )

    # Accept both `{"claudeAiOauth": {...}}` (macOS Keychain shape) and a
    # bare `{...}` (the inner object). Normalize to the wrapped form.
    if "claudeAiOauth" not in blob and "accessToken" in blob:
        blob = {"claudeAiOauth": blob}

    try:
        if scope == "user":
            token = auth_flow.store_user_credentials_blob(request.user, blob)
            authenticated = auth_flow.validate_stored_token(user=request.user)
            # Persist validation state so the resolver can fall back to global
            # if this blob is stored-but-dead.
            from django.utils import timezone

            from .models import UserCredential
            UserCredential.objects.filter(user=request.user).update(
                last_validated_at=timezone.now(),
                last_validation_ok=authenticated,
            )
        else:
            token = auth_flow.store_credentials_blob(blob)
            authenticated = auth_flow.validate_stored_token()
    except ValueError as exc:
        return Response(
            error_response(message=str(exc), code="bad_blob"),
            status=400,
        )

    logger.info(
        "cli_auth_upload: user=%s scope=%s token_len=%d authenticated=%s",
        getattr(request.user, "email", "?"), scope, len(token), authenticated,
    )
    return Response(
        success_response({
            "stored": True,
            "authenticated": authenticated,
            "token_prefix": token[:15],
            "scope": scope,
        })
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_promote(request: Request) -> Response:
    """Copy the caller's UserCredential blob to the global SystemConfig row.

    Allowed callers: ``is_staff`` users + automation accounts on the
    ``@dimagi-ai.com`` domain. The latter exists so the e2e bot
    (``ace@dimagi-ai.com``) can rotate the instance-wide subscription
    without a human in the loop.
    """
    if not _can_write_global(request.user):
        return Response(
            error_response(
                message="promote requires staff or automation account",
                code="forbidden",
            ),
            status=403,
        )
    from .models import UserCredential

    cred = UserCredential.objects.filter(user=request.user).first()
    if cred is None:
        return Response(
            error_response(
                message="no personal blob to promote — upload one first",
                code="no_personal_blob",
            ),
            status=400,
        )
    try:
        blob = json.loads(cred.blob_encrypted)
    except ValueError:
        return Response(
            error_response(message="personal blob is corrupt", code="bad_blob"),
            status=400,
        )
    try:
        auth_flow.store_credentials_blob(blob)
        authenticated = auth_flow.validate_stored_token()
    except ValueError as exc:
        # Structurally valid JSON but semantically malformed blob
        # (missing claudeAiOauth.accessToken, or token_looks_real rejects it).
        return Response(
            error_response(message=str(exc), code="bad_blob"),
            status=400,
        )
    logger.info(
        "cli_auth_promote: admin=%s promoted personal blob to global authenticated=%s",
        request.user.email, authenticated,
    )
    return Response(
        success_response({
            "promoted": True,
            "authenticated": authenticated,
            "token_prefix": cred.token_prefix,
        })
    )


# Stream-compatible JSON dump helper for the ace-cli-login script, so it
# can introspect the expected shape without parsing Python docs.
_EXPECTED_BLOB_SHAPE = {
    "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-<...>",
        "refreshToken": "<...>",
        "expiresAt": 0,
        "scopes": [],
    },
}


@api_view(["GET"])
def cli_auth_expected_shape(_request: Request) -> Response:
    """Unauth'd introspection endpoint — the CLI tool calls this to check
    which blob shape the server accepts, without needing credentials."""
    return Response(success_response({"shape": _EXPECTED_BLOB_SHAPE}))


def __deprecated_pty_endpoints() -> None:
    """Placeholder to make the removal explicit in history.

    The previous ``cli_auth_start`` / ``cli_auth_complete`` / ``cli_auth_poll``
    / ``cli_auth_cancel`` views drove ``claude setup-token`` through a PTY
    and tried to parse the OAuth token out of the interactive terminal
    output. That approach was replaced by the upload endpoint because
    PTY parsing proved too fragile (ANSI cursor positioning, line wrap
    at variable widths, version-dependent CLI rendering). Keep this stub
    for git-blame continuity — actual implementation is gone.
    """
    raise NotImplementedError(
        "Removed — use POST /api/auth/cli/upload with a credential blob "
        "captured by scripts/ace_cli_login.py"
    )
