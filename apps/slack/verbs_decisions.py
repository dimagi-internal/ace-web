"""Interaction handlers for multi-player decision voting + fork.

Three entry points called from dispatch_interaction in handlers.py:

1. handle_answer_decision — button click on a decision option
2. handle_answer_other_submission — modal submit for free-form "Other…" answer
3. handle_fork_with_answers — "Fork & re-run with answers" button on phase tile
"""
from __future__ import annotations

import json
import logging
import threading

from .blocks_decisions import render_decision_message, render_fork_modal
from .models import SlackRunThread
from .slack_client import SlackChannelGone, client_for

logger = logging.getLogger(__name__)


def handle_answer_decision(payload: dict, action: dict) -> dict:
    """A user clicked an option button on a decision message."""
    value = action.get("value", "")
    parts = value.split(":", 3)
    if len(parts) < 4:
        return {"response_type": "ephemeral", "text": ":x: malformed answer action"}
    opp_slug, phase_name, decision_id, answer = parts

    slack_user_id = payload.get("user", {}).get("id", "")
    slack_user_name = payload.get("user", {}).get("username", "someone")
    channel_id = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("message", {}).get("ts", "")

    thread = _find_active_thread(opp_slug)
    if thread is None:
        return {"response_type": "ephemeral",
                "text": ":x: No active tracking for this opp."}

    _record_vote(
        thread=thread,
        phase_name=phase_name,
        decision_id=decision_id,
        answer=answer,
        voter_slack_id=slack_user_id,
        voter_name=slack_user_name,
    )

    _update_decision_message_after_vote(
        thread=thread,
        phase_name=phase_name,
        decision_id=decision_id,
        channel_id=channel_id,
        message_ts=message_ts,
        opp_slug=opp_slug,
    )

    _update_phase_tile_summary(thread=thread, phase_name=phase_name, opp_slug=opp_slug)

    return {}


def handle_answer_other_open(payload: dict, action: dict) -> dict:
    """User clicked "Other…" — open a modal with a text input."""
    value = action.get("value", "")
    parts = value.split(":", 2)
    if len(parts) < 3:
        return {"response_type": "ephemeral", "text": ":x: malformed action"}
    opp_slug, phase_name, decision_id = parts

    trigger_id = payload.get("trigger_id")
    if not trigger_id:
        return {"response_type": "ephemeral",
                "text": ":x: Missing trigger_id — can't open modal."}

    team_id = payload.get("team", {}).get("id", "")
    from .handlers import _get_installation
    installation = _get_installation(team_id)
    if installation is None:
        return {"response_type": "ephemeral", "text": ":x: workspace not installed"}

    message_ts = payload.get("message", {}).get("ts", "")
    channel_id = payload.get("channel", {}).get("id", "")

    metadata = json.dumps({
        "opp_slug": opp_slug,
        "phase_name": phase_name,
        "decision_id": decision_id,
        "message_ts": message_ts,
        "channel_id": channel_id,
    })

    view = {
        "type": "modal",
        "callback_id": "ace_answer_other",
        "title": {"type": "plain_text", "text": "Custom answer"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": metadata,
        "blocks": [
            {"type": "input",
             "block_id": "custom_answer",
             "label": {"type": "plain_text", "text": "Your answer"},
             "element": {
                 "type": "plain_text_input",
                 "action_id": "custom_answer_input",
                 "multiline": True,
                 "placeholder": {"type": "plain_text",
                                 "text": "Type your alternative answer…"},
             }},
        ],
    }

    client = client_for(installation)
    client.open_view(trigger_id=trigger_id, view=view)
    return {}


def handle_answer_other_submission(payload: dict) -> dict:
    """Modal submit for the free-form "Other…" answer."""
    view = payload.get("view", {})
    metadata = json.loads(view.get("private_metadata", "{}"))
    opp_slug = metadata.get("opp_slug", "")
    phase_name = metadata.get("phase_name", "")
    decision_id = metadata.get("decision_id", "")
    message_ts = metadata.get("message_ts", "")
    channel_id = metadata.get("channel_id", "")

    values = view.get("state", {}).get("values", {})
    answer = (values.get("custom_answer", {})
              .get("custom_answer_input", {})
              .get("value", ""))

    if not answer or not answer.strip():
        return {
            "response_action": "errors",
            "errors": {"custom_answer": "Please enter an answer."},
        }

    slack_user_id = payload.get("user", {}).get("id", "")
    slack_user_name = payload.get("user", {}).get("username", "someone")

    thread = _find_active_thread(opp_slug)
    if thread is None:
        return {}

    _record_vote(
        thread=thread,
        phase_name=phase_name,
        decision_id=decision_id,
        answer=answer.strip(),
        voter_slack_id=slack_user_id,
        voter_name=slack_user_name,
    )

    _update_decision_message_after_vote(
        thread=thread,
        phase_name=phase_name,
        decision_id=decision_id,
        channel_id=channel_id,
        message_ts=message_ts,
        opp_slug=opp_slug,
    )

    _update_phase_tile_summary(thread=thread, phase_name=phase_name, opp_slug=opp_slug)

    return {}


def handle_fork_with_answers(payload: dict, action: dict) -> dict:
    """Fork button on the phase tile — opens a confirmation modal."""
    value = action.get("value", "")
    parts = value.split(":", 2)
    if len(parts) < 3:
        return {"response_type": "ephemeral", "text": ":x: malformed fork action"}
    opp_slug, phase_name, run_id = parts

    trigger_id = payload.get("trigger_id")
    if not trigger_id:
        return {"response_type": "ephemeral",
                "text": ":x: Missing trigger_id — can't open modal."}

    team_id = payload.get("team", {}).get("id", "")
    from .handlers import _get_installation
    installation = _get_installation(team_id)
    if installation is None:
        return {"response_type": "ephemeral", "text": ":x: workspace not installed"}

    thread = _find_active_thread(opp_slug)
    if thread is None:
        return {"response_type": "ephemeral",
                "text": ":x: No active tracking for this opp."}

    phase_data = (thread.phase_messages or {}).get(phase_name, {})
    votes = phase_data.get("votes", {})

    if not votes:
        return {"response_type": "ephemeral",
                "text": ":x: No decisions have been answered yet."}

    modal = render_fork_modal(
        opp_slug=opp_slug,
        phase_name=phase_name,
        votes=votes,
        source_run_id=run_id,
    )
    client = client_for(installation)
    client.open_view(trigger_id=trigger_id, view=modal)
    return {}


def handle_fork_submission(payload: dict) -> dict:
    """Modal submit for the fork confirmation.

    Fires the fork async (Drive-heavy, 5-15s) and posts the result
    back to the channel thread.
    """
    view = payload.get("view", {})
    metadata = json.loads(view.get("private_metadata", "{}"))
    opp_slug = metadata.get("opp_slug", "")
    phase_name = metadata.get("phase_name", "")
    source_run_id = metadata.get("source_run_id", "")

    values = view.get("state", {}).get("values", {})
    mode = (values.get("fork_mode", {})
            .get("fork_mode_select", {})
            .get("selected_option", {})
            .get("value", "keep-overrides-only"))

    slack_user_id = payload.get("user", {}).get("id", "")

    thread = _find_active_thread(opp_slug)
    if thread is None:
        return {}

    phase_data = (thread.phase_messages or {}).get(phase_name, {})
    votes = phase_data.get("votes", {})

    edits = [{"row_id": did, "new_answer": v["answer"]}
             for did, v in votes.items()]

    threading.Thread(
        target=_execute_fork,
        args=(thread, opp_slug, phase_name, source_run_id, edits, mode, slack_user_id),
        daemon=True,
    ).start()

    return {}


def _execute_fork(thread, opp_slug, phase_name, source_run_id,
                  edits, mode, slack_user_id):
    """Run the fork in a background thread and post the result."""
    from apps.opps.api import fork_opp_and_return
    from apps.opps.schemas import OppForkEditIn, OppForkIn

    try:
        from .handlers import _get_user_link
        user_link = _get_user_link(thread.installation, slack_user_id)
        if user_link is None:
            _post_fork_result(thread, ":x: Your Slack account isn't linked to ace-web.")
            return

        body = OppForkIn(
            fork_at_phase=phase_name,
            source_run_id=source_run_id or None,
            edits=[OppForkEditIn(row_id=e["row_id"], new_answer=e["new_answer"])
                   for e in edits],
            mode=mode,
        )
        workspace = thread.installation.ace_workspace
        result = fork_opp_and_return(workspace, user_link.ace_user, opp_slug, body)

        from django.conf import settings
        base = settings.ACE_PUBLIC_BASE_URL
        ws_slug = workspace.slug
        url = f"{base}/w/{ws_slug}/opps/{result['slug']}?run_id={result['run_id']}"
        text = (f":tada: Forked *{opp_slug}* from *{phase_name}* → "
                f"new run `{result['run_id']}`\n<{url}|Open in ace-web>")
        _post_fork_result(thread, text)

    except Exception:
        logger.exception("fork from slack failed for %s", opp_slug)
        _post_fork_result(thread, ":x: Fork failed — check ace-web logs.")


def _post_fork_result(thread, text: str) -> None:
    """Post the fork result as a thread reply."""
    try:
        client = client_for(thread.installation)
        client.post_message(
            channel=thread.channel_id,
            blocks=[{"type": "section",
                     "text": {"type": "mrkdwn", "text": text}}],
            text=text,
            thread_ts=thread.parent_ts,
        )
    except SlackChannelGone:
        logger.info("channel gone while posting fork result for %s", thread.opp_slug)
    except Exception:
        logger.exception("failed to post fork result for %s", thread.opp_slug)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_active_thread(opp_slug: str) -> SlackRunThread | None:
    return (
        SlackRunThread.objects
        .select_related("installation__ace_workspace")
        .filter(opp_slug=opp_slug, broken_at__isnull=True, stopped_at__isnull=True)
        .first()
    )


def _record_vote(*, thread: SlackRunThread, phase_name: str,
                 decision_id: str, answer: str,
                 voter_slack_id: str, voter_name: str) -> None:
    phase_messages = dict(thread.phase_messages or {})
    phase_data = dict(phase_messages.get(phase_name, {}))
    votes = dict(phase_data.get("votes", {}))
    votes[decision_id] = {
        "answer": answer,
        "voter_slack_id": voter_slack_id,
        "voter_name": voter_name,
    }
    phase_data["votes"] = votes
    phase_messages[phase_name] = phase_data
    thread.phase_messages = phase_messages
    thread.save(update_fields=["phase_messages"])


def _update_decision_message_after_vote(
    *, thread: SlackRunThread, phase_name: str, decision_id: str,
    channel_id: str, message_ts: str, opp_slug: str,
) -> None:
    """Re-render and chat.update the decision message to show the new voter."""
    from .dispatcher import _load_snapshot

    workspace = thread.installation.ace_workspace
    snapshot = _load_snapshot(thread.opp_slug, workspace, run_id=thread.run_id or None)
    if snapshot is None:
        return

    decisions = snapshot.get("current_run", {}).get("decisions") or []
    decision = next((d for d in decisions if d.get("id") == decision_id), None)
    if decision is None:
        return

    phase_decisions = [d for d in decisions if d.get("phase") == phase_name]
    decision_index = next(
        (i + 1 for i, d in enumerate(phase_decisions) if d.get("id") == decision_id),
        1,
    )

    phase_data = (thread.phase_messages or {}).get(phase_name, {})
    vote = phase_data.get("votes", {}).get(decision_id)

    blocks = render_decision_message(
        decision,
        opp_slug=opp_slug,
        phase_name=phase_name,
        vote=vote,
        decision_index=decision_index,
    )

    try:
        client = client_for(thread.installation)
        client.update_message(
            channel=channel_id,
            ts=message_ts,
            blocks=blocks,
            text=f"Decision #{decision_index}: {decision.get('question', '')}",
        )
    except SlackChannelGone:
        pass
    except Exception:
        logger.exception("failed to update decision message %s/%s", opp_slug, decision_id)


def _update_phase_tile_summary(*, thread: SlackRunThread, phase_name: str,
                               opp_slug: str) -> None:
    """Re-render and chat.update the phase tile to refresh the decision summary."""
    from .blocks import render_phase_tile
    from .dispatcher import _load_snapshot

    workspace = thread.installation.ace_workspace
    snapshot = _load_snapshot(thread.opp_slug, workspace, run_id=thread.run_id or None)
    if snapshot is None:
        return

    phase_data = (thread.phase_messages or {}).get(phase_name, {})
    phase_ts = phase_data.get("ts")
    if not phase_ts:
        return

    votes = phase_data.get("votes", {})
    blocks = render_phase_tile(
        snapshot,
        phase_name=phase_name,
        opp_slug=opp_slug,
        workspace_slug=workspace.slug,
        votes=votes,
    )

    try:
        client = client_for(thread.installation)
        client.update_message(
            channel=thread.channel_id,
            ts=phase_ts,
            blocks=blocks,
            text=f"Phase: {phase_name}",
        )
    except SlackChannelGone:
        pass
    except Exception:
        logger.exception("failed to update phase tile %s/%s", opp_slug, phase_name)
