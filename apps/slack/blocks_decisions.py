"""Block Kit renderers for per-decision thread messages.

Each decision in the snapshot becomes its own Slack message, posted as a
thread reply under the phase tile. The message shows the question, AI
default, current voter (if any), and option buttons.

Multi-player: anyone in the channel can click an option; the message
updates to show who picked what (last-write-wins). Votes are staged on
SlackRunThread.phase_messages until someone clicks "Fork & re-run with
answers" on the phase tile.
"""
from __future__ import annotations

import hashlib
import json

_MAX_OPTION_BUTTONS = 4


def render_decision_message(
    decision: dict,
    *,
    opp_slug: str,
    phase_name: str,
    vote: dict | None = None,
    decision_index: int = 1,
) -> list[dict]:
    """Render a single decision as Block Kit blocks for a thread reply.

    Args:
        decision: A decision dict from the snapshot's current_run.decisions.
        opp_slug: The opp slug (for action value encoding).
        phase_name: The phase this decision belongs to.
        vote: Current vote dict {answer, voter_slack_id, voter_name} or None.
        decision_index: 1-based index for display ("Decision #3").
    """
    decision_id = decision.get("id", "")
    question = decision.get("question", "(no question)")
    ai_default = decision.get("default", "")
    skill = decision.get("skill", "")
    options = decision.get("options_considered") or []

    eyebrow_parts = [f":clipboard: Decision #{decision_index}"]
    if skill:
        eyebrow_parts.append(skill)
    eyebrow = " · ".join(eyebrow_parts)

    question_line = f"*{question}*"
    default_line = f"AI default: `{_truncate(ai_default, 200)}`" if ai_default else ""
    body_parts = [question_line]
    if default_line:
        body_parts.append(default_line)

    blocks: list[dict] = [
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": eyebrow}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": "\n".join(body_parts)}},
    ]

    if vote:
        answer = vote.get("answer", "")
        voter_line = f":speech_balloon: <@{vote['voter_slack_id']}> → `{_truncate(answer, 150)}`"
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": voter_line}]})
    else:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": "_No answer yet_"}]})

    action_value_prefix = f"{opp_slug}:{phase_name}:{decision_id}"
    action_elements: list[dict] = []
    for opt in options[:_MAX_OPTION_BUTTONS]:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": _truncate(opt, 75), "emoji": True},
            "action_id": f"answer_decision:{decision_id}:{_slug(opt)}",
            "value": f"{action_value_prefix}:{opt}",
        })
    action_elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Other…", "emoji": True},
        "action_id": f"answer_decision_other:{decision_id}",
        "value": action_value_prefix,
    })
    blocks.append({"type": "actions", "elements": action_elements})

    return blocks


def render_decision_summary(
    decisions: list[dict],
    votes: dict,
) -> str:
    """One-line mrkdwn summary for the phase tile.

    Args:
        decisions: All decisions for this phase from the snapshot.
        votes: The votes dict from phase_messages (decision_id → vote).

    Returns:
        e.g. ":clipboard: 20 decisions · 4 answered by 2 people"
    """
    total = len(decisions)
    if total == 0:
        return ""
    answered = sum(1 for d in decisions if d.get("id") in votes)
    voter_ids = {v["voter_slack_id"] for v in votes.values() if v.get("voter_slack_id")}
    voter_count = len(voter_ids)

    parts = [f":clipboard: {total} decision{'s' if total != 1 else ''}"]
    if answered > 0:
        ppl = "person" if voter_count == 1 else "people"
        voter_str = f" by {voter_count} {ppl}" if voter_count else ""
        parts.append(f"{answered} answered{voter_str}")
    else:
        parts.append("none answered yet")
    return " · ".join(parts)


def decisions_state_hash(decisions: list[dict], votes: dict) -> str:
    """Hash that changes when decisions or votes change.

    Used by the dispatcher to skip Slack API calls when nothing changed.
    """
    payload = {
        "decision_ids": sorted(d.get("id", "") for d in decisions),
        "votes": {k: v.get("answer", "") for k, v in sorted(votes.items())},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:16]


def render_fork_modal(
    opp_slug: str,
    phase_name: str,
    votes: dict,
    source_run_id: str,
) -> dict:
    """Build a Slack modal (view) confirming the fork-with-answers action.

    Shows the list of overridden decisions and a mode picker. The submit
    handler reads private_metadata to fire the fork API call.
    """
    decision_lines = []
    for did, vote in sorted(votes.items()):
        answer = _truncate(vote.get("answer", ""), 100)
        voter = vote.get("voter_name", "someone")
        decision_lines.append(f"• *{did}*: `{answer}` (by {voter})")
    if not decision_lines:
        decision_lines.append("_No decisions have been answered yet._")

    metadata = json.dumps({
        "opp_slug": opp_slug,
        "phase_name": phase_name,
        "source_run_id": source_run_id,
    })

    return {
        "type": "modal",
        "callback_id": "ace_fork_with_answers",
        "title": {"type": "plain_text", "text": "Fork & re-run"},
        "submit": {"type": "plain_text", "text": "Fork"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": metadata,
        "blocks": [
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": f"Fork *{opp_slug}* from phase *{phase_name}* with these answers:"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": "\n".join(decision_lines)}},
            {"type": "input",
             "block_id": "fork_mode",
             "label": {"type": "plain_text", "text": "Decision mode"},
             "element": {
                 "type": "static_select",
                 "action_id": "fork_mode_select",
                 "initial_option": {
                     "text": {"type": "plain_text", "text": "Keep only my overrides"},
                     "value": "keep-overrides-only",
                 },
                 "options": [
                     {"text": {"type": "plain_text", "text": "Keep only my overrides"},
                      "value": "keep-overrides-only"},
                     {"text": {"type": "plain_text", "text": "Keep all decisions"},
                      "value": "keep-all"},
                 ],
             }},
        ],
    }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def _slug(text: str) -> str:
    """Short slug for action_id uniqueness (action_ids must be unique per message)."""
    return hashlib.sha256(text.encode()).hexdigest()[:8]
