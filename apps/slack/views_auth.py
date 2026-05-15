"""Slack-account-link page.

A logged-in ace-web user lands here from a DM the bot sent them. We
look up the pending command (saved when they tried to run a slash
command), create a SlackUserLink row, and replay the command so they
don't have to retype it.
"""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest

from .models import SlackInstallation, SlackUserLink
from .pending import PendingMissing, take_pending_command

logger = logging.getLogger(__name__)


def _replay_command(payload: dict) -> None:
    """Re-dispatch the originally-attempted slash command now that the
    user is linked. Best-effort — failures here are logged, not surfaced.
    """
    from .handlers import dispatch_slash_command
    try:
        dispatch_slash_command(
            text=payload["command_text"].removeprefix("/ace ").strip(),
            slack_user_id=payload["slack_user_id"],
            team_id=payload["team_id"],
            channel_id=payload["channel_id"],
            trigger_id=payload.get("trigger_id") or "",
            response_url="",  # we can't re-acquire the ephemeral url
        )
    except Exception:
        logger.exception("replay of pending slack command failed")


@login_required
def link_page(request: HttpRequest) -> HttpResponse:
    nonce = request.GET.get("nonce", "")
    try:
        pending = take_pending_command(nonce)
    except PendingMissing:
        return HttpResponseBadRequest("link expired or already used; run the "
                                      "command again from Slack")
    try:
        installation = SlackInstallation.objects.get(slack_team_id=pending["team_id"])
    except SlackInstallation.DoesNotExist:
        return HttpResponseBadRequest("no Slack installation for that team")
    SlackUserLink.objects.update_or_create(
        installation=installation,
        slack_user_id=pending["slack_user_id"],
        defaults={
            "ace_user": request.user,
            "slack_email": request.user.email or "",
            "slack_real_name": getattr(request.user, "display_name", "") or "",
            "unlinked_at": None,
        },
    )
    _replay_command(pending)
    return HttpResponse(
        "<h1>Linked!</h1><p>Your Slack identity is now connected to ace-web. "
        "You can close this tab and head back to Slack.</p>",
        status=200,
    )
