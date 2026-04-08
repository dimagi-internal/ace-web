"""SSE streaming endpoint for assistant messages.

GET /api/messages/<id>/stream

Drives CLIBackend.stream_completion() for the given placeholder Message and
streams its events as text/event-stream frames to the client. Writes
incremental plaintext updates to the Message row (debounced ~250ms).

Reconnect semantics:
- If the message is already in status=streaming, yield the current plaintext
  as a single delta event first, then continue driving the backend.
- If the message is already complete or error, yield the final state and close.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from asgiref.sync import sync_to_async
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
    the backend if the message is still pending."""
    # Reconnect: if already complete/error, yield current state and close
    if message.status == "complete":
        if message.plaintext:
            yield _sse_frame("delta", {"text": message.plaintext})
        yield _sse_frame("done", {})
        return
    if message.status == "error":
        yield _sse_frame("error", {"message": message.error_detail or "unknown error"})
        return

    # Reconnect to a streaming message: replay current plaintext, then continue
    if message.status == "streaming" and message.plaintext:
        yield _sse_frame("delta", {"text": message.plaintext})

    # Drive the backend
    user_text = await sync_to_async(_load_last_user_text)(message)
    backend = _get_backend()

    await sync_to_async(_mark_streaming)(message)

    accumulated: list[str] = [message.plaintext] if message.plaintext else []
    last_db_write = asyncio.get_event_loop().time()

    try:
        async for event in backend.stream_completion(
            session=message.session, new_user_message=user_text
        ):
            yield _sse_frame_for(event)

            if event.type is StreamEventType.DELTA and event.text:
                accumulated.append(event.text)
                now = asyncio.get_event_loop().time()
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

    except CLIBackendError as exc:
        logger.exception("CLIBackend failed during stream")
        await sync_to_async(_mark_error)(message, str(exc))
        yield _sse_frame("error", {"message": str(exc)})

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled by client for message %s", message.id)
        await sync_to_async(_mark_error)(
            message, f"cancelled (partial: {len(''.join(accumulated))} chars)"
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
        Message.objects.filter(session=asst_message.session, role="user")
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
        status="error", error_detail=detail
    )


def _create_tool_message(session: Session, block: dict, *, role: str) -> None:
    last_turn = (
        Message.objects.filter(session=session)
        .order_by("-turn_index")
        .values_list("turn_index", flat=True)
        .first()
    )
    Message.objects.create(
        session=session,
        turn_index=(last_turn or 0) + 1,
        role=role,
        content=block,
        plaintext=str(block.get("content") or block.get("input") or ""),
        status="complete",
        completed_at=timezone.now(),
    )
