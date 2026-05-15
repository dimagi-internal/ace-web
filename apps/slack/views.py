"""Slack webhook entry points.

Each view: (1) verify signing-secret, (2) parse the typed payload,
(3) dispatch to handlers, (4) return Slack's expected response shape.

Handlers return JSON-serializable dicts; we wrap them in JsonResponse.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .verify import SignatureError, verify_slack_signature

logger = logging.getLogger(__name__)


def _verify(request: HttpRequest) -> None:
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    verify_slack_signature(
        secret=settings.SLACK_SIGNING_SECRET,
        body=request.body,
        timestamp=ts,
        signature=sig,
    )


@csrf_exempt
@require_POST
def slash_commands(request: HttpRequest) -> HttpResponse:
    try:
        _verify(request)
    except SignatureError as e:
        logger.warning("slack signature fail (commands): %s", e)
        return HttpResponse(status=401)

    from .handlers import dispatch_slash_command  # lazy to keep import-time light
    response = dispatch_slash_command(
        text=request.POST.get("text", "").strip(),
        slack_user_id=request.POST["user_id"],
        team_id=request.POST["team_id"],
        channel_id=request.POST["channel_id"],
        trigger_id=request.POST.get("trigger_id", ""),
        response_url=request.POST.get("response_url", ""),
    )
    return JsonResponse(response)


@csrf_exempt
@require_POST
def interactions(request: HttpRequest) -> HttpResponse:
    try:
        _verify(request)
    except SignatureError as e:
        logger.warning("slack signature fail (interactions): %s", e)
        return HttpResponse(status=401)

    payload = json.loads(request.POST.get("payload", "{}"))
    from .handlers import dispatch_interaction
    response = dispatch_interaction(payload)
    return JsonResponse(response)


@csrf_exempt
@require_POST
def events(request: HttpRequest) -> HttpResponse:
    """Inbound Events API. v1 only handles the URL verification challenge;
    we don't subscribe to app_mention or message events yet."""
    try:
        _verify(request)
    except SignatureError as e:
        logger.warning("slack signature fail (events): %s", e)
        return HttpResponse(status=401)

    body = json.loads(request.body or b"{}")
    if body.get("type") == "url_verification":
        return JsonResponse({"challenge": body["challenge"]})
    return JsonResponse({"ok": True})
