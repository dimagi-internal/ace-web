"""Slash command + interaction dispatcher. Filled in by subsequent tasks."""
from __future__ import annotations


def dispatch_slash_command(*, text: str, slack_user_id: str, team_id: str,
                           channel_id: str, trigger_id: str,
                           response_url: str) -> dict:
    return {"response_type": "ephemeral",
            "text": "Slack integration not yet wired."}


def dispatch_interaction(payload: dict) -> dict:
    return {"response_type": "ephemeral",
            "text": "Slack integration not yet wired."}
