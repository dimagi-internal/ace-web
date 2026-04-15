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
from .opp_broadcast import maybe_emit_opp_updated

logger = logging.getLogger(__name__)

# Module-level singleton CLIBackend. Keep as a function so tests can patch it.
_backend: CLIBackend | None = None

_bg_tasks: set[asyncio.Task] = set()


def _get_backend():
    """Return the chat backend singleton.

    Priority:
    1. FakeCLIBackend if ACE_USE_FAKE_CLI_BACKEND is True (E2E tests)
    2. CLIBackend if the CLI OAuth token is available
    3. ApiBackend if ANTHROPIC_API_KEY is set (direct API fallback)
    4. CLIBackend anyway (will fail with a clear error)
    """
    from django.conf import settings

    if getattr(settings, "ACE_USE_FAKE_CLI_BACKEND", False):
        from apps.common.fake_cli_backend import FakeCLIBackend
        return FakeCLIBackend()

    global _backend
    if _backend is not None:
        return _backend

    # Prefer CLI if we have a token
    from apps.common.auth_flow import get_stored_token
    if get_stored_token():
        _backend = CLIBackend()
        return _backend

    # Fall back to API if we have a key
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if api_key:
        from apps.common.api_backend import ApiBackend
        _backend = ApiBackend()
        return _backend

    # No token, no API key — return CLIBackend which will fail with a
    # clear error message when used.
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

    Both ``next_task`` and ``stop_task`` are hoisted out of the loop body so
    that if this generator is cancelled while suspended inside ``asyncio.wait``
    (e.g. the consumer closes the WebSocket and the outer turn task is
    cancelled), the ``finally`` clause can drain BOTH tasks. If ``next_task``
    were leaked, it would still be holding the backend generator and the
    outer ``agen.aclose()`` would raise
    ``RuntimeError: aclose(): asynchronous generator is already running``.
    """
    next_task: asyncio.Task | None = None
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
                    next_task = None
                    return
                next_task = None
                yield event
            else:
                # stop_event fired before the backend produced another event.
                # The finally block will cancel next_task.
                return
    finally:
        for t in (next_task, stop_task):
            if t is not None and not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t


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
    # Snapshot the turn_index of the assistant message so we can later
    # harvest any tool_use rows that belong to THIS turn (rows created by
    # _create_tool_message have turn_index > this value).
    turn_start_index = message.turn_index
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

                # BEFORE yielding, persist tool rows so any consumer that
                # reads the DB (e.g. consumer._broadcast_stream_event for a
                # broadcast that needs the new row's id) sees the row
                # already in place.
                if event.type is StreamEventType.TOOL_USE:
                    await sync_to_async(_create_tool_message)(
                        message.session, event.tool_block, role="tool_use"
                    )
                elif event.type is StreamEventType.TOOL_RESULT:
                    await sync_to_async(_create_tool_message)(
                        message.session, event.tool_block, role="tool_result"
                    )

                # Accumulate delta text BEFORE yielding — this used to run
                # after the yield but was safe only by coincidence. Moving
                # it here means the accumulator is always up to date when
                # we hit the terminal DONE branch.
                if event.type is StreamEventType.DELTA and event.text:
                    accumulated.append(event.text)
                    now = asyncio.get_running_loop().time()
                    if now - last_db_write > 0.25:
                        await sync_to_async(_update_plaintext)(
                            message, "".join(accumulated)
                        )
                        last_db_write = now

                # Persist terminal state BEFORE yielding, so the consumer's
                # early return after receiving DONE (or ERROR) doesn't cut
                # off our DB writes. This was the Phase 3 bug: the elif
                # branches below the yield were never reached because
                # consumer._run_turn_driver hits `return` as soon as it
                # broadcasts chat.stream_complete, which closes this
                # generator via GeneratorExit at the yield line.
                if event.type is StreamEventType.DONE:
                    await sync_to_async(_mark_complete)(
                        message, "".join(accumulated)
                    )
                    _schedule_auto_title(message.session)
                    await _broadcast_opp_updated_if_needed(
                        message.session, turn_start_index
                    )
                    yield event
                    return
                if event.type is StreamEventType.ERROR:
                    await sync_to_async(_mark_error)(
                        message, event.error or "unknown"
                    )
                    yield event
                    return

                yield event
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
        await _broadcast_opp_updated_if_needed(message.session, turn_start_index)

    except CLIBackendError as exc:
        logger.exception("CLIBackend failed during assistant turn")
        await sync_to_async(_mark_error)(message, str(exc))
        yield StreamEvent.for_error(message=str(exc))

    except FileNotFoundError:
        # The `claude` binary is not installed on this server. The CLI
        # banner already tells users to connect, but if they send a
        # message anyway we need to flip the assistant message to error
        # state instead of leaving it stuck in 'streaming'.
        logger.exception("Claude CLI binary not found")
        detail = "Claude CLI is not installed on this server. Visit /auth/cli to connect."
        await sync_to_async(_mark_error)(message, detail)
        yield StreamEvent.for_error(message=detail)

    except Exception as exc:
        # Catch-all so any unexpected error in the backend or downstream
        # processing leaves the assistant message in a terminal 'error'
        # state instead of zombie 'streaming'.
        logger.exception("Unexpected error during assistant turn")
        detail = f"{type(exc).__name__}: {exc}"
        await sync_to_async(_mark_error)(message, detail)
        yield StreamEvent.for_error(message=detail)

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
    """Fire-and-forget auto-title task.

    The task is pinned in module-level _bg_tasks to keep a strong reference
    (Python 3.11+ only holds a weak ref to create_task() results, so without
    this a GC pass could cancel the task mid-execution). The task self-
    removes via add_done_callback so the set does not grow unboundedly.

    Same behavior as Phase 2; lifted from streaming.py with the GC-safe pinning.
    """
    from .auto_title import generate_title_for_session

    async def _runner():
        try:
            await generate_title_for_session(session)
        except Exception:
            logger.exception("Auto-title task failed for session %s", session.slug)

    task = asyncio.create_task(_runner())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


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


def _collect_tool_uses_for_turn(session: Session, turn_start_index: int) -> list[dict]:
    """Return tool_use blocks created during the current turn.

    Rows are created by ``_create_tool_message`` with ``turn_index`` strictly
    greater than the assistant message's ``turn_index`` (which is
    ``turn_start_index`` here). Filter accordingly so we only see tool_use
    rows from THIS turn, not earlier turns.
    """
    rows = Message.objects.filter(
        session=session, role="tool_use", turn_index__gt=turn_start_index
    ).values_list("content", flat=True)
    out: list[dict] = []
    for content in rows:
        if isinstance(content, dict):
            out.append(content)
    return out


async def _broadcast_opp_updated_if_needed(
    session: Session, turn_start_index: int
) -> None:
    """Harvest tool_use rows from this turn and emit opp.updated if warranted.

    Safe to call unconditionally: maybe_emit_opp_updated is a no-op for
    non-opp sessions or turns that didn't touch Drive.
    """
    tool_uses = await sync_to_async(_collect_tool_uses_for_turn)(
        session, turn_start_index
    )
    try:
        await maybe_emit_opp_updated(session, tool_uses)
    except Exception:
        # Broadcast failure must never abort a completed turn — the message
        # is already persisted; the worst case is the workbench misses an
        # auto-refetch and the user has to reload.
        logger.exception("opp.updated broadcast failed for session %s", session.slug)


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
