"""Background task that generates a ~6-word title for a session.

Triggered from the SSE streaming view after the first assistant turn completes.
Best-effort: any failure is logged and swallowed so it cannot break the chat
experience.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackendError

from .models import Session

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Summarize the following user message in 6 words or fewer. "
    "Respond with ONLY the title, no quotes, no punctuation, no explanation:\n\n"
    "{text}"
)


def _get_backend(user=None):
    """Select backend via the shared selector so auto-title and chat agree."""
    from apps.common.backend_selector import get_chat_backend

    return get_chat_backend(user=user)


async def generate_title_for_session(session: Session) -> None:
    """Generate and persist a title. Idempotent — does nothing if title is set."""
    await sync_to_async(session.refresh_from_db)()
    if session.title.strip():
        return

    user_text = await sync_to_async(_load_first_user_message_text)(session)
    if not user_text:
        return

    prompt = _TITLE_PROMPT.format(text=user_text)
    # ``session.owner`` is a ForeignKey access that triggers a sync DB query
    # if the FK isn't already cached. ``refresh_from_db`` above doesn't
    # populate FKs, so wrap the access in sync_to_async.
    owner = await sync_to_async(lambda: session.owner)()
    # Same async-context gotcha as turn_driver — _get_backend hits sync ORM
    # via the cli_is_ready validation probe. Without sync_to_async, Django
    # raises SynchronousOnlyOperation and we silently fall back to ApiBackend.
    backend = await sync_to_async(_get_backend)(user=owner)

    accumulated: list[str] = []
    try:
        async for event in backend.stream_completion(
            session=session,
            new_user_message=prompt,
            force_fresh_session=True,
        ):
            if event.type is StreamEventType.DELTA and event.text:
                accumulated.append(event.text)
            elif event.type in (StreamEventType.DONE, StreamEventType.ERROR):
                break
    except CLIBackendError as exc:
        logger.warning("Auto-title backend failed for session %s: %s", session.slug, exc)
        return

    title = "".join(accumulated).strip().strip('"').strip("'")
    if not title:
        return
    await sync_to_async(_save_title)(session, title)
    await _broadcast_title_updated(session.slug, title)


async def _broadcast_title_updated(slug: str, title: str) -> None:
    """Push the new title to every open chat tab on this session.

    Without this, the chat header and the recent-sessions sidebar stay
    `Untitled` until the user reloads — even though the DB row has the
    real title and `/sessions` lists it correctly. The broadcast lets
    those surfaces re-fetch immediately.
    """
    layer = get_channel_layer()
    if layer is None:
        # No channels layer configured (rare; mainly the in-memory test
        # path before pytest-asyncio fixtures patch it). Silent — same
        # philosophy as the rest of this module.
        return
    try:
        await layer.group_send(
            f"session.{slug}",
            {"type": "session.title_updated", "title": title},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("Failed to broadcast title for session %s: %s", slug, exc)


def _load_first_user_message_text(session: Session) -> str:
    msg = (
        session.messages.filter(role="user")
        .order_by("turn_index")
        .first()
    )
    return msg.plaintext if msg else ""


def _save_title(session: Session, title: str) -> None:
    Session.objects.filter(pk=session.pk).update(title=title)
