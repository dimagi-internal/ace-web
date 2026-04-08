"""Background task that generates a ~6-word title for a session.

Triggered from the SSE streaming view after the first assistant turn completes.
Best-effort: any failure is logged and swallowed so it cannot break the chat
experience.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError

from .models import Session

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Summarize the following user message in 6 words or fewer. "
    "Respond with ONLY the title, no quotes, no punctuation, no explanation:\n\n"
    "{text}"
)


_backend: CLIBackend | None = None


def _get_backend() -> CLIBackend:
    global _backend
    if _backend is None:
        _backend = CLIBackend()
    return _backend


async def generate_title_for_session(session: Session) -> None:
    """Generate and persist a title. Idempotent — does nothing if title is set."""
    await sync_to_async(session.refresh_from_db)()
    if session.title.strip():
        return

    user_text = await sync_to_async(_load_first_user_message_text)(session)
    if not user_text:
        return

    prompt = _TITLE_PROMPT.format(text=user_text)
    backend = _get_backend()

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


def _load_first_user_message_text(session: Session) -> str:
    msg = (
        session.messages.filter(role="user")
        .order_by("turn_index")
        .first()
    )
    return msg.plaintext if msg else ""


def _save_title(session: Session, title: str) -> None:
    Session.objects.filter(pk=session.pk).update(title=title)
