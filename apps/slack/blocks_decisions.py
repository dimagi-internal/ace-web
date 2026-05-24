"""Block Kit helpers for decisions on phase tiles.

render_decision_summary — one-line mrkdwn summary for the phase tile context block.
decisions_state_hash — hash used by the dispatcher to skip redundant Slack API calls.
"""
from __future__ import annotations

import hashlib
import json


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


