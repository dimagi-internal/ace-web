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


from urllib.parse import urlencode  # noqa: E402

from django.contrib.auth.decorators import login_required, user_passes_test  # noqa: E402
from django.http import HttpResponseBadRequest, HttpResponseRedirect  # noqa: E402
from django.urls import reverse  # noqa: E402
from slack_sdk import WebClient  # noqa: E402
from slack_sdk.errors import SlackApiError  # noqa: E402

from apps.workspaces.models import Workspace  # noqa: E402

from .models import SlackInstallation  # noqa: E402

_BOT_SCOPES = [
    "commands", "chat:write", "chat:write.public",
    "users:read", "users:read.email",
]


def _is_staff(user) -> bool:
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_is_staff)
def install(request: HttpRequest) -> HttpResponse:
    """Kick off the admin OAuth flow."""
    if not settings.SLACK_CLIENT_ID:
        return HttpResponseBadRequest("SLACK_CLIENT_ID not configured")
    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": ",".join(_BOT_SCOPES),
        # No user_scope — bot install only. Per-user identity link is
        # a separate Django-side OAuth.
        # IMPORTANT: build via `reverse(...)` so FORCE_SCRIPT_NAME (/ace)
        # gets prepended. Hardcoding the path skips the script-name layer
        # and Slack rejects the resulting URI with redirect_uri mismatch
        # against the app's configured https://.../ace/api/slack/oauth/callback.
        "redirect_uri": request.build_absolute_uri(reverse("slack:oauth_callback")),
    }
    return HttpResponseRedirect("https://slack.com/oauth/v2/authorize?" + urlencode(params))


def _exchange_code(code: str, redirect_uri: str) -> dict:
    client = WebClient()
    return client.oauth_v2_access(
        client_id=settings.SLACK_CLIENT_ID,
        client_secret=settings.SLACK_CLIENT_SECRET,
        code=code,
        redirect_uri=redirect_uri,
    ).data


@login_required
@user_passes_test(_is_staff)
def oauth_callback(request: HttpRequest) -> HttpResponse:
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("missing code")
    # Must match the redirect_uri we passed in `install` (Slack verifies them).
    redirect_uri = request.build_absolute_uri(reverse("slack:oauth_callback"))
    try:
        data = _exchange_code(code, redirect_uri)
    except SlackApiError as e:
        logger.exception("slack oauth exchange failed")
        return HttpResponseBadRequest(f"oauth failed: {e.response.get('error')}")
    if not data.get("ok"):
        return HttpResponseBadRequest(f"oauth not ok: {data}")
    workspace = Workspace.objects.get(slug="dimagi-team")
    inst, _ = SlackInstallation.objects.update_or_create(
        slack_team_id=data["team"]["id"],
        defaults={
            "slack_team_name": data["team"]["name"],
            "bot_user_id": data["bot_user_id"],
            "ace_workspace": workspace,
            "installed_by_user": request.user,
        },
    )
    inst.bot_token = data["access_token"]
    inst.save()
    return HttpResponse(
        f"<h1>Installed</h1><p>Slack team <b>{inst.slack_team_name}</b> "
        f"is now wired up. ace workspace: <b>{workspace.slug}</b>.</p>",
        status=200,
    )
