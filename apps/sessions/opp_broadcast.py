"""Broadcast opp.updated events when a chat turn produced Drive side-effects.

Watched by OppWorkbenchPage (frontend, Task 7); triggers a refetch of the
opp snapshot. Pragmatic detection: any tool_use event with a name matching
ace-gdrive:drive_* or ace-gdrive:docs_*."""
from __future__ import annotations

from channels.layers import get_channel_layer

from apps.sessions.models import Session


def _touches_drive(tool_uses: list[dict]) -> bool:
    for tu in tool_uses:
        name = tu.get("name", "")
        if name.startswith("ace-gdrive:drive_") or name.startswith("ace-gdrive:docs_"):
            return True
    return False


def _opp_group(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


async def maybe_emit_opp_updated(session: Session, tool_uses: list[dict]) -> None:
    """Emit an opp.updated event if the session is opp-linked and a Drive tool ran."""
    if not session.opp_slug:
        return
    if not _touches_drive(tool_uses):
        return
    layer = get_channel_layer()
    if layer is None:
        return
    await layer.group_send(
        _opp_group(session.opp_slug, session.opp_run_id or ""),
        {
            "type": "opp.updated",
            "opp_slug": session.opp_slug,
            "run_id": session.opp_run_id or "",
        },
    )
