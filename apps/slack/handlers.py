"""Slash command + interaction dispatcher.

Subcommand routing: text is everything after `/ace` in the raw command.
We split on whitespace; the first token is the verb.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from .models import SlackInstallation, SlackUserLink
from .pending import save_pending_command
from .slack_client import SlackClient, client_for

logger = logging.getLogger(__name__)


_HELP_TEXT = (
    "*ACE bot* — Run and monitor ACE opportunities from Slack.\n\n"
    "`/ace run <pdd-link-or-opp-slug>` — Start the full ACE lifecycle.\n"
    "`/ace new` — Open a modal to create a new opp from an idea.\n"
    "`/ace track <slug>[/<run_id>]` — Mirror an existing run (e.g. one you're "
    "driving from your laptop) into this channel.\n"
    "`/ace untrack <slug>` — Stop mirroring a run.\n"
    "`/ace status [<slug>]` — Show the current state of a run.\n"
    "`/ace list` — Show your 5 most recent active runs.\n"
    "`/ace link` — (Re)link your Slack identity to ace-web.\n"
    "`/ace help` — This message.\n"
)


def _get_client(installation) -> SlackClient:
    """Indirection so tests can patch."""
    return client_for(installation)


def _get_installation(team_id: str) -> SlackInstallation | None:
    try:
        return SlackInstallation.objects.get(slack_team_id=team_id)
    except SlackInstallation.DoesNotExist:
        return None


def _get_user_link(installation, slack_user_id: str) -> SlackUserLink | None:
    return SlackUserLink.objects.filter(
        installation=installation, slack_user_id=slack_user_id,
        unlinked_at__isnull=True,
    ).select_related("ace_user").first()


def _link_url(nonce: str) -> str:
    base = getattr(settings, "ACE_PUBLIC_BASE_URL", "https://labs.connect.dimagi.com/ace")
    return f"{base}{reverse('slack_auth:link')}?{urlencode({'nonce': nonce})}"


def _ephemeral(text: str) -> dict:
    return {"response_type": "ephemeral", "text": text}


def _send_link_dm(*, installation, slack_user_id: str, team_id: str,
                  channel_id: str, command_text: str, trigger_id: str) -> dict:
    nonce = save_pending_command(
        slack_user_id=slack_user_id, team_id=team_id,
        channel_id=channel_id, command_text=command_text,
        trigger_id=trigger_id or None,
    )
    url = _link_url(nonce)
    client = _get_client(installation)
    client.dm_user(
        user=slack_user_id,
        text=f"Link your ace-web account to use /ace: {url}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "Link your ace-web account to use `/ace`."}},
            {"type": "actions", "elements": [
                {"type": "button",
                 "text": {"type": "plain_text", "text": "Link account"},
                 "url": url, "action_id": "link_account"},
            ]},
        ],
    )
    return _ephemeral("I sent you a DM with a link to connect your account. "
                      "Once linked, I'll resume your command.")


def dispatch_slash_command(*, text: str, slack_user_id: str, team_id: str,
                           channel_id: str, trigger_id: str,
                           response_url: str) -> dict:
    parts = text.split(maxsplit=1) if text else [""]
    verb = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    installation = _get_installation(team_id)
    if installation is None:
        return _ephemeral("This Slack workspace isn't installed in ace-web. "
                          "Ask an admin to run the /api/slack/install flow.")

    if verb == "help" or verb == "":
        return _ephemeral(_HELP_TEXT)

    if verb == "link":
        return _send_link_dm(installation=installation, slack_user_id=slack_user_id,
                             team_id=team_id, channel_id=channel_id,
                             command_text=f"/ace {text}", trigger_id=trigger_id)

    user_link = _get_user_link(installation, slack_user_id)
    if user_link is None:
        return _send_link_dm(installation=installation, slack_user_id=slack_user_id,
                             team_id=team_id, channel_id=channel_id,
                             command_text=f"/ace {text}", trigger_id=trigger_id)

    # Verbs that require a linked user. Sub-handler imports are lazy to keep
    # import-time cheap and to let tests patch.
    if verb == "run":
        from .verbs_run import handle_run
        return handle_run(installation=installation, user_link=user_link,
                          rest=rest, channel_id=channel_id,
                          trigger_id=trigger_id)
    if verb == "new":
        from .verbs_new import handle_new
        return handle_new(installation=installation, user_link=user_link,
                          channel_id=channel_id, trigger_id=trigger_id)
    if verb == "status":
        from .verbs_query import handle_status
        return handle_status(installation=installation, user_link=user_link,
                             rest=rest, channel_id=channel_id)
    if verb == "list":
        from .verbs_query import handle_list
        return handle_list(installation=installation, user_link=user_link,
                           channel_id=channel_id)
    if verb == "track":
        from .verbs_track import handle_track
        return handle_track(installation=installation, user_link=user_link,
                            rest=rest, channel_id=channel_id)
    if verb == "untrack":
        from .verbs_track import handle_untrack
        return handle_untrack(installation=installation, user_link=user_link,
                              rest=rest)

    return _ephemeral(f"Unknown subcommand `{verb}`. {_HELP_TEXT}")


def dispatch_interaction(payload: dict) -> dict:
    """Block action / view submission entrypoint."""
    p_type = payload.get("type")
    if p_type == "view_submission":
        if payload["view"].get("callback_id") == "ace_new_modal":
            from .verbs_new import handle_new_submission
            return handle_new_submission(payload)
        return {}
    if p_type == "block_actions":
        action = (payload.get("actions") or [{}])[0]
        action_id = action.get("action_id", "")
        if action_id == "fork_from_phase":
            return _fork_redirect(payload, action)
        if action_id == "stop_watching":
            return _stop_watching(payload, action)
        if action_id == "link_account":
            return {}  # button has its own url; nothing to do server-side
        # Unknown actions — silently 200.
        return {}
    return {}


def _stop_watching(payload: dict, action: dict) -> dict:
    from .models import SlackRunThread
    from .verbs_track import _stop_thread

    thread_id = action.get("value", "")
    team_id = payload.get("team", {}).get("id", "")
    installation = _get_installation(team_id)
    if installation is None:
        return {"response_type": "ephemeral", "text": ":x: workspace not installed"}
    try:
        thread = SlackRunThread.objects.get(pk=thread_id, installation=installation)
    except (SlackRunThread.DoesNotExist, ValueError):
        return {"response_type": "ephemeral",
                "text": ":x: That run isn't being tracked anymore."}
    if thread.stopped_at is not None:
        return {"response_type": "ephemeral",
                "text": "Already stopped."}
    slack_user_id = payload.get("user", {}).get("id", "")
    user_link = _get_user_link(installation, slack_user_id) if slack_user_id else None
    stopper = user_link.ace_user if user_link else None
    _stop_thread(thread, stopper=stopper, installation=installation)
    return {"response_type": "ephemeral",
            "text": f":octagonal_sign: Stopped mirroring `{thread.opp_slug}/{thread.run_id}`."}


def _fork_redirect(payload: dict, action: dict) -> dict:
    value = action.get("value", "")
    try:
        slug, phase = value.split(":", 1)
    except ValueError:
        return {"response_type": "ephemeral", "text": ":x: malformed fork action"}
    team_id = payload.get("team", {}).get("id", "")
    installation = _get_installation(team_id)
    if installation is None:
        return {"response_type": "ephemeral", "text": ":x: workspace not installed"}
    workspace_slug = installation.ace_workspace.slug
    base = getattr(settings, "ACE_PUBLIC_BASE_URL",
                   "https://labs.connect.dimagi.com/ace")
    url = (f"{base}/w/{workspace_slug}/opps/{slug}"
           f"?fork={phase}")
    return {"response_type": "ephemeral",
            "text": f"Open the fork dialog: <{url}>"}
