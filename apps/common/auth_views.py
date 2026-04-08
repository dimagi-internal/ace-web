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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_status(request: Request) -> Response:
    token = auth_flow.get_stored_token()
    return Response(success_response({"authenticated": bool(token)}))


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
