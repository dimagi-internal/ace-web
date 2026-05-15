"""Short-lived (10 min) cache of slash commands awaiting OAuth link.

Used so the first command from an unlinked Slack user doesn't have to be
retyped: we save it under a nonce, DM the user a link to /auth/slack/link/?nonce=,
and on successful link we pop the entry and replay the command.
"""
from __future__ import annotations

import json
import secrets

from django.core.cache import cache

_TTL_SECONDS = 10 * 60


class PendingMissing(KeyError):
    pass


def _key(nonce: str) -> str:
    return f"slack:pending:{nonce}"


def save_pending_command(*, slack_user_id: str, team_id: str,
                         channel_id: str, command_text: str,
                         trigger_id: str | None = None) -> str:
    nonce = secrets.token_urlsafe(24)
    payload = {
        "slack_user_id": slack_user_id,
        "team_id": team_id,
        "channel_id": channel_id,
        "command_text": command_text,
        "trigger_id": trigger_id,
    }
    cache.set(_key(nonce), json.dumps(payload), timeout=_TTL_SECONDS)
    return nonce


def take_pending_command(nonce: str) -> dict:
    raw = cache.get(_key(nonce))
    if raw is None:
        raise PendingMissing(nonce)
    cache.delete(_key(nonce))
    return json.loads(raw)
