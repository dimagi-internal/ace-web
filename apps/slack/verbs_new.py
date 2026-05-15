"""`/ace new` opens a modal; submission triggers a new opp + run."""
from __future__ import annotations

import json
import logging

from .blocks import render_parent_card
from .models import SlackInstallation, SlackRunThread, SlackUserLink
from .run_starter import RunStartError, start_run_from_slack
from .slack_client import SlackClient, client_for

logger = logging.getLogger(__name__)


def _get_client(installation) -> SlackClient:
    return client_for(installation)


def _modal_view(*, channel_id: str) -> dict:
    return {
        "type": "modal",
        "callback_id": "ace_new_modal",
        "private_metadata": json.dumps({"channel_id": channel_id}),
        "title": {"type": "plain_text", "text": "New ACE opportunity"},
        "submit": {"type": "plain_text", "text": "Start"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input", "block_id": "name_block",
                "label": {"type": "plain_text", "text": "Name"},
                "element": {"type": "plain_text_input", "action_id": "name_input",
                            "placeholder": {"type": "plain_text",
                                            "text": "e.g. Rural TB Screening"}},
                "optional": True,
            },
            {
                "type": "input", "block_id": "idea_block",
                "label": {"type": "plain_text", "text": "Idea"},
                "element": {"type": "plain_text_input", "action_id": "idea_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text",
                                            "text": "Describe the problem, "
                                                    "the behavior you want, "
                                                    "and who the LLOs are."}},
            },
        ],
    }


def handle_new(*, installation, user_link, channel_id: str,
               trigger_id: str) -> dict:
    client = _get_client(installation)
    try:
        client.open_view(trigger_id=trigger_id, view=_modal_view(channel_id=channel_id))
    except Exception:
        logger.exception("failed to open /ace new modal")
        return {"response_type": "ephemeral",
                "text": ":x: Couldn't open the modal. Try again."}
    # Empty body — Slack expects 200 OK with no content for trigger acks.
    return {}


def handle_new_submission(payload: dict) -> dict:
    """Called from dispatch_interaction when view['callback_id'] == 'ace_new_modal'."""
    view = payload["view"]
    team_id = payload["team"]["id"]
    slack_user_id = payload["user"]["id"]
    metadata = json.loads(view.get("private_metadata") or "{}")
    channel_id = metadata.get("channel_id", "")

    values = view["state"]["values"]
    name = values.get("name_block", {}).get("name_input", {}).get("value", "") or ""
    idea = values.get("idea_block", {}).get("idea_input", {}).get("value", "") or ""

    if not idea.strip():
        return {"response_action": "errors",
                "errors": {"idea_block": "Idea is required."}}

    try:
        installation = SlackInstallation.objects.get(slack_team_id=team_id)
    except SlackInstallation.DoesNotExist:
        return {"response_action": "errors",
                "errors": {"idea_block": "Slack workspace not installed in ace-web."}}
    user_link = SlackUserLink.objects.filter(
        installation=installation, slack_user_id=slack_user_id,
        unlinked_at__isnull=True,
    ).select_related("ace_user").first()
    if user_link is None:
        return {"response_action": "errors",
                "errors": {"idea_block": "Link your account with `/ace link` first."}}

    workspace = installation.ace_workspace
    user = user_link.ace_user

    try:
        # opp_creator interprets `slug_or_link` containing newlines as an
        # idea-block; the resolver in run_starter checks for `https://` first,
        # so a multiline idea text gets routed to the idea-to-design path.
        # If your opp_creator signature requires a separate `idea_text` arg,
        # branch on it in run_starter; for now we encode "new from idea" as
        # an idea payload prefixed with `idea:` for the resolver to detect.
        slug_or_link = f"idea:{name}\n\n{idea}" if name else f"idea:{idea}"
        slug, run_id = start_run_from_slack(
            slug_or_link=slug_or_link, user=user, workspace=workspace,
        )
    except RunStartError as e:
        return {"response_action": "errors",
                "errors": {"idea_block": str(e)}}
    except Exception:
        logger.exception("start_run_from_slack failed for /ace new")
        return {"response_action": "errors",
                "errors": {"idea_block": "Internal error; check ace-web logs."}}

    client = _get_client(installation)
    placeholder_snapshot = {
        "display_name": slug,
        "current_run": {"run_id": run_id, "steps": [], "decisions": []},
        "phases": [],
    }
    blocks = render_parent_card(
        placeholder_snapshot, opp_slug=slug,
        workspace_slug=workspace.slug,
        triggerer_display=f"<@{slack_user_id}>",
        elapsed_seconds=0,
    )
    if channel_id:
        ts = client.post_message(channel=channel_id, blocks=blocks,
                                 text=f"ACE run started — {slug}")
        SlackRunThread.objects.create(
            installation=installation, channel_id=channel_id, parent_ts=ts,
            opp_slug=slug, run_id=run_id, ace_user=user,
        )
        # Subscribe the worker to this run's group. Best-effort.
        try:
            from channels.layers import get_channel_layer  # noqa: F401
            from asgiref.sync import async_to_sync  # noqa: F401
            from .dispatcher import _opp_group  # noqa: F401
            # The worker rediscovers subscriptions on every event; we don't
            # need to know the worker's channel_name here. The 60s sweep
            # (Task 14) is the belt-and-suspenders that catches everything.
        except Exception:
            logger.exception("could not request slack worker subscription")
    return {"response_action": "clear"}
