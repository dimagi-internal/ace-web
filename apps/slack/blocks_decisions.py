"""Block Kit helpers for decisions on phase tiles.

decisions_state_hash — hash used by the dispatcher to skip redundant
Slack API calls when decisions haven't changed.
"""
from __future__ import annotations

import hashlib
import json


def decisions_state_hash(decisions: list[dict], votes: dict) -> str:
    payload = {
        "decision_ids": sorted(d.get("id", "") for d in decisions),
        "statuses": sorted(d.get("status", "") for d in decisions),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:16]
