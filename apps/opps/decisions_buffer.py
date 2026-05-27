"""Redis-backed shared edit buffer for multi-player decision editing.

Key: decisions:edits:{slug}:{run_id}
Shape: JSON dict of row_id -> {new_answer, editor_email, editor_name, edited_at}
TTL: 24 hours

Reusable pattern: any future multi-player feature can follow this
{feature}:edits:{context_key} shape with the same get/set/remove/clear API.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from django.core.cache import cache

_TTL_SECONDS = 86400  # 24 hours


def _key(slug: str, run_id: str) -> str:
    return f"decisions:edits:{slug}:{run_id}"


def get_edits(slug: str, run_id: str) -> dict:
    raw = cache.get(_key(slug, run_id))
    if raw is None:
        return {}
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def set_edit(slug: str, run_id: str, *, row_id: str, new_answer: str,
             editor_email: str, editor_name: str,
             override_reasoning: str = "") -> None:
    edits = get_edits(slug, run_id)
    edits[row_id] = {
        "new_answer": new_answer,
        "override_reasoning": override_reasoning,
        "editor_email": editor_email,
        "editor_name": editor_name,
        "edited_at": datetime.now(UTC).isoformat(),
    }
    cache.set(_key(slug, run_id), json.dumps(edits), timeout=_TTL_SECONDS)


def remove_edit(slug: str, run_id: str, *, row_id: str) -> None:
    edits = get_edits(slug, run_id)
    if row_id not in edits:
        return
    del edits[row_id]
    if edits:
        cache.set(_key(slug, run_id), json.dumps(edits), timeout=_TTL_SECONDS)
    else:
        cache.delete(_key(slug, run_id))


def clear_edits(slug: str, run_id: str) -> None:
    cache.delete(_key(slug, run_id))
