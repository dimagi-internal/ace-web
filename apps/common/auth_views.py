"""REST endpoints for the in-app PTY-based Claude CLI auth flow.

All endpoints return the standard {data, error} envelope. The actual PTY
work happens in apps.common.auth_flow.
"""
from __future__ import annotations

import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import auth_flow
from .envelope import error_response, success_response

logger = logging.getLogger(__name__)


def _token_looks_real(token: str | None) -> bool:
    """Cheap format check that rejects placeholders and obvious noise.

    Real Claude OAuth tokens look like "sk-ant-oatNN-<long opaque string>"
    where the opaque part is roughly base64url. We don't validate against
    Anthropic here — just enough to reject the placeholder we write when
    provisioning the Secrets Manager entry, and any mangled paste.
    """
    if not token:
        return False
    if not token.startswith("sk-ant-oat"):
        return False
    if len(token) < 40:
        return False
    if "placeholder" in token.lower():
        return False
    return True


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_status(request: Request) -> Response:
    from django.conf import settings

    # When the FakeCLIBackend is enabled (E2E tests, dev mode), the chat
    # backend doesn't need a real Claude token — report as authenticated
    # so the SendBox doesn't disable itself.
    if getattr(settings, "ACE_USE_FAKE_CLI_BACKEND", False):
        return Response(success_response({"authenticated": True}))
    token = auth_flow.get_stored_token()
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    # Chat works if either a real-looking CLI token OR the API key is available.
    authenticated = _token_looks_real(token) or bool(api_key)
    return Response(success_response({"authenticated": authenticated}))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_start(request: Request) -> Response:
    try:
        result = auth_flow.start()
    except RuntimeError as exc:
        return Response(
            error_response(message=str(exc), code="auth_flow_error"),
            status=400,
        )
    return Response(success_response(result))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_complete(request: Request) -> Response:
    code = request.data.get("code") or ""
    try:
        token = auth_flow.complete(code=code or None)
    except RuntimeError as exc:
        return Response(
            error_response(message=str(exc), code="auth_flow_error"),
            status=400,
        )
    return Response(success_response({"status": "complete", "token_set": bool(token)}))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_poll(request: Request) -> Response:
    return Response(success_response(auth_flow.poll()))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_cancel(request: Request) -> Response:
    auth_flow.cancel()
    return Response(success_response({"cancelled": True}))
