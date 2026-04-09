"""Drive one assistant turn end-to-end: kick off CLIBackend.stream_completion,
debounce plaintext updates to the Message row, create tool_use / tool_result
child rows, and propagate DONE / ERROR / CANCELLED terminal states.

This module is the Phase 3 replacement for the SSE generator in
apps.sessions.streaming. The SSE framing (`event: delta\\ndata: {...}`)
is gone; instead we yield raw StreamEvent objects so the consumer can
broadcast them to the Channels group however it wants.

Cancellation: the caller passes an asyncio.Event. The driver checks it
before each backend yield. When set, the backend's async generator is
closed (which triggers its finally block — SIGTERM → SIGKILL in
CLIBackend), the Message row is marked error with partial-length detail,
and drive_assistant_turn yields a single error event before returning.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError

from .models import Message, Session

logger = logging.getLogger(__name__)

# Module-level singleton CLIBackend. Keep as a function so tests can patch it.
_backend: CLIBackend | None = None


def _get_backend() -> CLIBackend:
    global _backend
    if _backend is None:
        _backend = CLIBackend()
    return _backend


async def _iter_until_stop(
    agen: AsyncIterator[StreamEvent], stop_event: asyncio.Event
) -> AsyncIterator[StreamEvent]:
    """Yield from ``agen`` until it exhausts OR ``stop_event`` is set.

    A naive ``async for`` would block forever on the next ``__anext__`` call
    if the backend's yield is slow, even if ``stop_event`` has been set in
    the meantime. This helper races the next event against the stop_event
    so cancellation is responsive within one backend yield.
    """
    stop_task: asyncio.Task | None = None
    try:
        while True:
            if stop_event.is_set():
                return

            next_task = asyncio.ensure_future(agen.__anext__())
            if stop_task is None or stop_task.done():
                stop_task = asyncio.ensure_future(stop_event.wait())

            done, _pending = await asyncio.wait(
                {next_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if next_task in done:
                try:
                    event = next_task.result()
                except StopAsyncIteration:
                    return
                yield event
            else:
                # stop_event fired before the backend produced another event
                next_task.cancel()
                with contextlib.suppress(BaseException):
                    await next_task
                return
    finally:
        if stop_task is not None and not stop_task.done():
            stop_task.cancel()
            with contextlib.suppress(BaseException):
                await stop_task


async def drive_assistant_turn(
    *, assistant_message_id: int, stop_event: asyncio.Event
) -> AsyncIterator[StreamEvent]:
    """Drive a single assistant turn. Yields StreamEvents to the caller.

    The caller is responsible for broadcasting events to any listening
    WebSocket group. This module just owns the backend + DB state
    machine.
    """
    message = await sync_to_async(_load_message)(assistant_message_id)
    if message is None:
        yield StreamEvent.for_error(message="assistant message not found")
        return

    if message.status in ("complete", "streaming"):
        if message.plaintext:
            yield StreamEvent.delta(text=message.plaintext)
        yield StreamEvent.done()
        return
    if message.status == "error":
        yield StreamEvent.for_error(message=message.error_detail or "unknown")
        return

    user_text = await sync_to_async(_load_last_user_text)(message)
    backend = _get_backend()
    await sync_to_async(_mark_streaming)(message)

    accumulated: list[str] = []
    last_db_write = asyncio.get_running_loop().time()

    try:
        agen = backend.stream_completion(
            session=message.session, new_user_message=user_text
        )
        try:
            async for event in _iter_until_stop(agen, stop_event):
                if stop_event.is_set():
                    break

                yield event

                if event.type is StreamEventType.DELTA and event.text:
                    accumulated.append(event.text)
                    now = asyncio.get_running_loop().time()
                    if now - last_db_write > 0.25:
                        await sync_to_async(_update_plaintext)(
                            message, "".join(accumulated)
                        )
                        last_db_write = now

                elif event.type is StreamEventType.TOOL_USE:
                    await sync_to_async(_create_tool_message)(
                        message.session, event.tool_block, role="tool_use"
                    )

                elif event.type is StreamEventType.TOOL_RESULT:
                    await sync_to_async(_create_tool_message)(
                        message.session, event.tool_block, role="tool_result"
                    )

                elif event.type is StreamEventType.DONE:
                    await sync_to_async(_mark_complete)(
                        message, "".join(accumulated)
                    )
                    _schedule_auto_title(message.session)
                    return

                elif event.type is StreamEventType.ERROR:
                    await sync_to_async(_mark_error)(
                        message, event.error or "unknown"
                    )
                    return
        finally:
            await agen.aclose()

        if stop_event.is_set():
            partial = "".join(accumulated)
            await sync_to_async(_mark_error)(
                message, f"cancelled (partial: {len(partial)} chars)"
            )
            yield StreamEvent.for_error(message="cancelled")
            return

        await sync_to_async(_mark_complete)(message, "".join(accumulated))
        _schedule_auto_title(message.session)

    except CLIBackendError as exc:
        logger.exception("CLIBackend failed during assistant turn")
        await sync_to_async(_mark_error)(message, str(exc))
        yield StreamEvent.for_error(message=str(exc))

    except asyncio.CancelledError:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(
                sync_to_async(_mark_error)(
                    message,
                    f"cancelled (partial: {len(''.join(accumulated))} chars)",
                )
            )
        raise


def _schedule_auto_title(session: Session) -> None:
    from .auto_title import generate_title_for_session

    async def _runner():
        try:
            await generate_title_for_session(session)
        except Exception:
            logger.exception("Auto-title task failed for session %s", session.slug)

    asyncio.create_task(_runner())


def _load_message(message_id: int) -> Message | None:
    try:
        return Message.objects.select_related("session").get(pk=message_id)
    except Message.DoesNotExist:
        return None


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
    if "name" in block:
        return str(block.get("name", ""))
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
