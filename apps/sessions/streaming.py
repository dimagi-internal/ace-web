"""SSE streaming endpoint for assistant messages.

GET /api/messages/<id>/stream

Drives CLIBackend.stream_completion() for the given placeholder Message and
streams its events as text/event-stream frames to the client. Writes
incremental plaintext updates to the Message row (debounced ~250ms).

Reconnect semantics:
- complete or streaming: yield current plaintext + done, close.
  (streaming is treated as "someone else is still driving; just replay
   what we have and let the other driver finish". We do NOT start a
   second backend drive on the same message.)
- error: yield the error, close.
- pending: this is the first time we're streaming it; drive the backend.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

from asgiref.sync import sync_to_async
from django.db import transaction
from django.http import HttpRequest, StreamingHttpResponse
from django.utils import timezone

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError

from .models import Message, Session

logger = logging.getLogger(__name__)


# Module-level singleton — fine for Phase 2 (single instance Cloud Run).
_backend: CLIBackend | None = None


def _get_backend() -> CLIBackend:
    global _backend
    if _backend is None:
        _backend = CLIBackend()
    return _backend


async def stream_assistant_message(request: HttpRequest, message_id: int):
    """Async view that returns a text/event-stream response."""
    user = await sync_to_async(lambda: request.user)()
    if not user or not user.is_authenticated:
        return StreamingHttpResponse(
            iter([_sse_frame("error", {"message": "unauthenticated"})]),
            content_type="text/event-stream",
            status=401,
        )

    try:
        message = await sync_to_async(_load_message_for_user)(message_id, user)
    except Message.DoesNotExist:
        return StreamingHttpResponse(
            iter([_sse_frame("error", {"message": "message not found"})]),
            content_type="text/event-stream",
            status=404,
        )

    response = StreamingHttpResponse(
        _generate(message),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering
    return response


def _load_message_for_user(message_id: int, user) -> Message:
    return Message.objects.select_related("session").get(
        id=message_id, session__owner=user
    )


async def _generate(message: Message) -> AsyncIterator[bytes]:
    """The SSE generator. Replays existing state if reconnecting, then drives
    the backend if the message is still pending.

    Reconnect semantics:
    - complete or streaming: yield current plaintext + done, close.
      (streaming is treated as "someone else is still driving; just replay
       what we have and let the other driver finish". We do NOT start a
       second backend drive on the same message.)
    - error: yield the error, close.
    - pending: this is the first time we're streaming it; drive the backend.
    """
    if message.status in ("complete", "streaming"):
        if message.plaintext:
            yield _sse_frame("delta", {"text": message.plaintext})
        yield _sse_frame("done", {})
        return
    if message.status == "error":
        yield _sse_frame("error", {"message": message.error_detail or "unknown error"})
        return

    # status == "pending" — drive the backend
    user_text = await sync_to_async(_load_last_user_text)(message)
    backend = _get_backend()

    await sync_to_async(_mark_streaming)(message)

    accumulated: list[str] = []
    last_db_write = asyncio.get_running_loop().time()

    try:
        async for event in backend.stream_completion(
            session=message.session, new_user_message=user_text
        ):
            yield _sse_frame_for(event)

            if event.type is StreamEventType.DELTA and event.text:
                accumulated.append(event.text)
                now = asyncio.get_running_loop().time()
                if now - last_db_write > 0.25:
                    await sync_to_async(_update_plaintext)(
                        message, "".join(accumulated)
                    )
                    last_db_write = now

            elif event.type is StreamEventType.SESSION_ID:
                # Session.cli_session_id is persisted by the CLIBackend itself
                pass

            elif event.type is StreamEventType.TOOL_USE:
                await sync_to_async(_create_tool_message)(
                    message.session, event.tool_block, role="tool_use"
                )

            elif event.type is StreamEventType.TOOL_RESULT:
                await sync_to_async(_create_tool_message)(
                    message.session, event.tool_block, role="tool_result"
                )

            elif event.type is StreamEventType.DONE:
                await sync_to_async(_mark_complete)(message, "".join(accumulated))
                return

            elif event.type is StreamEventType.ERROR:
                await sync_to_async(_mark_error)(message, event.error or "unknown")
                return

        # Fix I2: loop exited cleanly without DONE/ERROR — mark complete with what we have
        await sync_to_async(_mark_complete)(message, "".join(accumulated))

    except CLIBackendError as exc:
        logger.exception("CLIBackend failed during stream")
        await sync_to_async(_mark_error)(message, str(exc))
        yield _sse_frame("error", {"message": str(exc)})

    except asyncio.CancelledError:
        # Fix I1: shield the DB write from cancellation re-delivery during shutdown
        logger.info("SSE stream cancelled by client for message %s", message.id)
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(
                sync_to_async(_mark_error)(
                    message,
                    f"cancelled (partial: {len(''.join(accumulated))} chars)",
                )
            )
        raise


# ────────────────────────────── helpers ──────────────────────────────

def _sse_frame(event_name: str, data: dict) -> bytes:
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n".encode()


def _sse_frame_for(event: StreamEvent) -> bytes:
    if event.type is StreamEventType.DELTA:
        return _sse_frame("delta", {"text": event.text})
    if event.type is StreamEventType.TOOL_USE:
        return _sse_frame("tool_use", {"block": event.tool_block})
    if event.type is StreamEventType.TOOL_RESULT:
        return _sse_frame("tool_result", {"block": event.tool_block})
    if event.type is StreamEventType.SESSION_ID:
        return _sse_frame("session_id", {"session_id": event.session_id})
    if event.type is StreamEventType.DONE:
        return _sse_frame("done", {})
    if event.type is StreamEventType.ERROR:
        return _sse_frame("error", {"message": event.error or ""})
    return b""


def _load_last_user_text(asst_message: Message) -> str:
    user_msg = (
        Message.objects.filter(
            session=asst_message.session,
            role="user",
            turn_index__lt=asst_message.turn_index,
        )
        .order_by("-turn_index")
        .first()
    )
    return user_msg.plaintext if user_msg else ""


def _mark_streaming(message: Message) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="streaming", started_at=timezone.now()
    )


def _update_plaintext(message: Message, text: str) -> None:
    Message.objects.filter(pk=message.pk).update(plaintext=text)


def _mark_complete(message: Message, text: str) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="complete",
        plaintext=text,
        content={"text": text},
        completed_at=timezone.now(),
    )


def _mark_error(message: Message, detail: str) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="error",
        error_detail=detail,
        completed_at=timezone.now(),
    )


def _summarize_tool_block(block: dict) -> str:
    """Extract a short human-readable plaintext summary from a tool_use or
    tool_result block. Keeps the full structured data in `content`; the
    plaintext is only for list previews and search.
    """
    # tool_use: show the tool name
    if "name" in block:
        return str(block.get("name", ""))
    # tool_result: flatten any text blocks
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _create_tool_message(session: Session, block: dict, *, role: str) -> None:
    with transaction.atomic():
        locked_session = Session.objects.select_for_update().get(pk=session.pk)
        last_turn = (
            Message.objects.filter(session=locked_session)
            .order_by("-turn_index")
            .values_list("turn_index", flat=True)
            .first()
        )
        Message.objects.create(
            session=locked_session,
            turn_index=(last_turn or 0) + 1,
            role=role,
            content=block,
            plaintext=_summarize_tool_block(block),
            status="complete",
            completed_at=timezone.now(),
        )
