"""Plain-Python serializer helpers for the sessions surface.

The DRF-era ``*Serializer`` classes (Message/Session/Draft/Participant/
ShareToken) were only ever consumed by consumers.py — the WebSocket chat
dispatch layer retired alongside apps/sessions/{consumers,drafts,presence,
routing}.py. ``_truncate_preview`` survives because apps/sessions/api.py's
list/detail dict-builders still use it directly.
"""
from __future__ import annotations

PREVIEW_LIMIT = 120


def _truncate_preview(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= PREVIEW_LIMIT:
        return text
    return text[: PREVIEW_LIMIT - 1].rstrip() + "…"
