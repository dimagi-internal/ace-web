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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_status(request: Request) -> Response:
    # When the FakeCLIBackend is enabled (E2E tests, dev), the chat
    # backend doesn't need a real Claude token — report as authenticated
    # so the SendBox doesn't disable itself.
    if getattr(settings, "ACE_USE_FAKE_CLI_BACKEND", False):
        return Response(success_response({"authenticated": True}))
    return Response(
        success_response({"authenticated": auth_flow.validate_stored_token()})
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_upload(request: Request) -> Response:
    """Accept a credential blob (shape: {"claudeAiOauth": {...}}) and persist it.

    Intended caller: ``scripts/ace_cli_login.py`` running on a developer's
    laptop, reading from the local macOS Keychain or Linux
    ``~/.claude/.credentials.json``. Authentication is via session cookie
    (from a prior Connect OAuth login) or a personal Bearer token minted
    at ``/settings``.
    """
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
        token = auth_flow.store_credentials_blob(blob)
    except ValueError as exc:
        return Response(
            error_response(message=str(exc), code="bad_blob"),
            status=400,
        )

    authenticated = auth_flow.validate_stored_token()
    logger.info(
        "cli_auth_upload: user=%s stored token_len=%d authenticated=%s",
        getattr(request.user, "email", "?"), len(token), authenticated,
    )
    return Response(
        success_response({
            "stored": True,
            "authenticated": authenticated,
            "token_prefix": token[:15],
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
