"""REST endpoints for the Claude CLI token.

The user runs `claude setup-token` on their laptop and pastes the resulting
`sk-ant-oat…` token into the ace-web UI. This module takes that token and
hands it off to apps.common.auth_flow for persistence (disk + env + Secrets
Manager). All endpoints return the standard {data, error} envelope.
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
    # Chat works if either the CLI token OR the API key is available
    return Response(success_response({"authenticated": bool(token or api_key)}))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_set_token(request: Request) -> Response:
    token = request.data.get("token") or ""
    try:
        auth_flow.store_token(token)
    except auth_flow.InvalidTokenError as exc:
        return Response(
            error_response(message=str(exc), code="invalid_token"),
            status=400,
        )
    return Response(success_response({"authenticated": True}))
