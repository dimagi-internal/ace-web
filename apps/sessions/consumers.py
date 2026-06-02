"""SessionConsumer — the single WebSocket endpoint for Phase 3.

Protocol:
  Client → {"action": "<namespace.verb>", "data": {...}}
  Server → {"event": "<namespace.verb>", "data": {...}}

All business logic lives in sibling modules:
  drafts.py       — draft state machine (sync ORM, wrapped in sync_to_async)
  presence.py     — Redis HASH presence + debounced last_seen writer
  turn_driver.py  — assistant streaming loop (async, yields StreamEvents)

This module is the dispatch layer. It translates client actions into
helper calls, broadcasts results to the session's Channels group, and
handles per-connection lifecycle (presence on connect/disconnect, full
state replay on connect, stop-event cleanup).

Channels group naming:  session.{slug}    — all events for a session
Stop-signal Redis key:  turn.stop:{message_id}
"""
from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Prefetch

from apps.common import redis_client
from apps.common.chat_backend import StreamEvent, StreamEventType

from . import drafts, presence, turn_driver
from .models import Draft, Message, Session, SessionParticipant
from .serializers import (
    DraftSerializer,
    MessageSerializer,
    ParticipantSerializer,
)

logger = logging.getLogger(__name__)

EDITOR_ROLES = {"owner", "editor"}

# Module-level strong-reference set for in-flight turn tasks. ``consumer
# ._turn_tasks`` alone is not enough — when the WebSocket disconnects, the
# ``SessionConsumer`` instance is eligible for GC, and asyncio will cancel
# any task whose only strong reference came from that set. The broadcast
# layer (channels-redis) is per-process and independent of the consumer's
# connection, so as long as we hold a reference here the turn continues
# to run and stream events to any other clients in the same session group
# (including the same user reconnecting in a new tab). Removed by the
# task's own done-callback below. Mirrors the ``turn_driver._bg_tasks``
# pattern used for the auto-titler.
_TURN_BG_TASKS: set[asyncio.Task] = set()

# Slug-indexed view of ``_TURN_BG_TASKS`` for the turn-state API. The
# task itself doesn't carry the session slug as an attribute; tracking it
# in a separate dict keeps introspection O(1) instead of having to walk
# every task's coroutine frame. Updated in lockstep with _TURN_BG_TASKS
# below.
_TURN_TASKS_BY_SLUG: dict[str, asyncio.Task] = {}


def turn_task_for_slug(slug: str) -> asyncio.Task | None:
    """Return the in-flight turn task for this session slug if one is
    running on THIS worker process, else None. Used by the read-only
    turn-state endpoint to expose whether a chat turn is actively driving
    the backend right now."""
    return _TURN_TASKS_BY_SLUG.get(slug)


def _group_name(slug: str) -> str:
    return f"session.{slug}"


class SessionConsumer(AsyncJsonWebsocketConsumer):
    # ─────────────────── lifecycle ───────────────────
    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        user = self.scope.get("user")

        if user is None or not user.is_authenticated:
            # Reject at the handshake: send websocket.close without first
            # accepting. WebsocketCommunicator surfaces this as
            # (False, 4001), which the frontend can distinguish from a
            # normal post-accept close.
            await self.close(code=4001)
            return

        self.user = user
        self.participant_role = await sync_to_async(_participant_role)(
            self.slug, user.id
        )
        if self.participant_role is None:
            await self.close(code=4003)
            return

        # Per-consumer registry for background turn tasks so they keep a
        # strong reference (see turn_driver._bg_tasks for the same pattern).
        self._turn_tasks: set[asyncio.Task] = set()

        await self.channel_layer.group_add(_group_name(self.slug), self.channel_name)
        await self.accept()

        was_new = await presence.touch(self.slug, user.id)
        session_pk = await sync_to_async(_session_pk_for)(self.slug)
        if session_pk is not None:
            await presence.maybe_record_last_seen(
                self.slug, user.id, session_pk=session_pk
            )

        snapshot = await self._build_session_state()
        await self.send_json({"event": "session.state", "data": snapshot})

        if was_new:
            await self.channel_layer.group_send(
                _group_name(self.slug),
                {
                    "type": "presence.joined",
                    "user_id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                },
            )

    async def disconnect(self, code):
        slug = getattr(self, "slug", None)
        user = getattr(self, "user", None)
        if slug is None or user is None:
            return
        await presence.leave(slug, user.id)
        await self.channel_layer.group_discard(_group_name(slug), self.channel_name)
        await self.channel_layer.group_send(
            _group_name(slug),
            {"type": "presence.left", "user_id": user.id},
        )

    # ─────────────────── dispatch ───────────────────
    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        data = content.get("data") or {}
        handler = _HANDLERS.get(action)
        if handler is None:
            await self._error("bad_request", f"unknown action {action!r}")
            return
        try:
            await handler(self, data)
        except Exception:
            logger.exception("SessionConsumer handler %s failed", action)
            await self._error("internal", "handler failed")

    # ─────────────────── group event handlers (channels-called) ───────────────────
    async def draft_updated(self, event):
        await self.send_json({"event": "draft.updated", "data": event["data"]})

    async def draft_lock_changed(self, event):
        await self.send_json({"event": "draft.lock_changed", "data": event["data"]})

    async def draft_committed(self, event):
        await self.send_json({"event": "draft.committed", "data": event["data"]})

    async def draft_discarded(self, event):
        await self.send_json({"event": "draft.discarded", "data": event["data"]})

    async def chat_stream_start(self, event):
        await self.send_json({"event": "chat.stream_start", "data": event["data"]})

    async def chat_delta(self, event):
        await self.send_json({"event": "chat.delta", "data": event["data"]})

    async def chat_tool_use(self, event):
        await self.send_json({"event": "chat.tool_use", "data": event["data"]})

    async def chat_tool_result(self, event):
        await self.send_json({"event": "chat.tool_result", "data": event["data"]})

    async def chat_stream_complete(self, event):
        await self.send_json({"event": "chat.stream_complete", "data": event["data"]})

    async def chat_stream_error(self, event):
        await self.send_json({"event": "chat.stream_error", "data": event["data"]})

    async def chat_stream_cancelled(self, event):
        await self.send_json({"event": "chat.stream_cancelled", "data": event["data"]})

    async def session_title_updated(self, event):
        await self.send_json(
            {"event": "session.title_updated", "data": {"title": event["title"]}}
        )

    async def presence_joined(self, event):
        await self.send_json({
            "event": "presence.joined",
            "data": {
                "user_id": event["user_id"],
                "email": event["email"],
                "display_name": event["display_name"],
            },
        })

    async def presence_left(self, event):
        await self.send_json({
            "event": "presence.left",
            "data": {"user_id": event["user_id"]},
        })

    # ─────────────────── helpers ───────────────────
    async def _error(self, code: str, message: str, detail: dict | None = None):
        payload: dict = {"code": code, "message": message}
        if detail is not None:
            payload["detail"] = detail
        await self.send_json({"event": "session.error", "data": payload})

    async def _build_session_state(self) -> dict:
        state = await sync_to_async(_sync_build_state)(self.slug, self.user)
        state["presence_user_ids"] = await presence.snapshot(self.slug)
        state["current_user_id"] = self.user.id
        return state

    def _is_editor(self) -> bool:
        return self.participant_role in EDITOR_ROLES


# ────────────────────── handlers ──────────────────────

async def _handle_presence_heartbeat(consumer: SessionConsumer, data: dict):
    was_new = await presence.touch(consumer.slug, consumer.user.id)
    session_pk = await sync_to_async(_session_pk_for)(consumer.slug)
    if session_pk is not None:
        await presence.maybe_record_last_seen(
            consumer.slug, consumer.user.id, session_pk=session_pk
        )
    if was_new:
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "presence.joined",
                "user_id": consumer.user.id,
                "email": consumer.user.email,
                "display_name": consumer.user.display_name,
            },
        )


async def _handle_draft_update(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot edit drafts")
        return
    try:
        version = int(data["version"])
        body = str(data.get("body", ""))
    except (KeyError, TypeError, ValueError):
        await consumer._error("bad_request", "draft.update requires version and body")
        return

    draft_id = await sync_to_async(_active_draft_id)(consumer.slug, consumer.user)
    if draft_id is None:
        await consumer._error("not_found", "no active draft")
        return

    try:
        draft = await sync_to_async(drafts.update_body)(
            draft_id=draft_id,
            user=consumer.user,
            expected_version=version,
            new_body=body,
        )
    except drafts.DraftVersionMismatch as exc:
        await consumer._error(
            "draft_version_mismatch",
            "stale draft version",
            detail={
                "current_version": exc.current_version,
                "current_body": exc.current_body,
            },
        )
        return

    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.updated", "data": _draft_payload(draft)},
    )


async def _handle_draft_take_over(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot take over drafts")
        return
    draft_id = await sync_to_async(_active_draft_id)(consumer.slug, consumer.user)
    if draft_id is None:
        await consumer._error("not_found", "no active draft")
        return

    # KNOWN RACE: the holder can change between the _current_holder_id read
    # and the claim_lock transaction. Worst case is a spurious re-claim —
    # the next draft.update from the "losing" user will carry a stale
    # version and be rejected by the version guard. Fixing this properly
    # would require changing drafts.claim_lock to take a presence-checker
    # callable and re-check inside the transaction; out of scope for Task 9.
    current = await sync_to_async(_current_holder_id)(draft_id)
    holder_present = (
        await presence.is_present(consumer.slug, current) if current else False
    )

    try:
        draft = await sync_to_async(drafts.claim_lock)(
            draft_id=draft_id,
            user=consumer.user,
            holder_is_present=holder_present,
        )
    except drafts.DraftLockHeld as exc:
        await consumer._error(
            "draft_lock_held",
            "lock held by another editor",
            detail={
                "holder_user_id": exc.holder_user_id,
                "expires_at": exc.expires_at,
            },
        )
        return

    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {
            "type": "draft.lock_changed",
            "data": {
                "draft_id": draft.id,
                "holder_user_id": draft.last_editor_id,
                "expires_at": None,
            },
        },
    )


async def _handle_draft_discard(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot discard drafts")
        return
    draft_id = await sync_to_async(_active_draft_id)(consumer.slug, consumer.user)
    if draft_id is None:
        return
    draft = await sync_to_async(drafts.discard)(
        draft_id=draft_id, user=consumer.user
    )
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.discarded", "data": {"draft_id": draft.id}},
    )
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.updated", "data": _draft_payload(draft)},
    )


async def _handle_chat_send(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot send messages")
        return
    session = await sync_to_async(_load_session)(consumer.slug)
    if session is None:
        await consumer._error("not_found", "session not found")
        return

    # Auto-activate imported sessions on first message send (Phase 4 ingest)
    if session.status == "imported":
        await sync_to_async(_activate_imported_session)(session)

    result = await sync_to_async(drafts.commit_active_draft)(
        session=session, user=consumer.user
    )
    if result is None:
        return  # empty draft — silently ignore

    # Broadcast: committed draft + new empty draft + chat.stream_start
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {
            "type": "draft.committed",
            "data": {
                "draft_id": result.old_draft_id,
                "message_id": result.assistant_message_id,
                "user_message_id": result.user_message_id,
            },
        },
    )
    new_draft = await sync_to_async(_get_draft)(result.new_draft_id)
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {"type": "draft.updated", "data": _draft_payload(new_draft)},
    )
    await consumer.channel_layer.group_send(
        _group_name(consumer.slug),
        {
            "type": "chat.stream_start",
            "data": {
                "message_id": result.assistant_message_id,
                "turn_index": await sync_to_async(_turn_index_for)(
                    result.assistant_message_id
                ),
            },
        },
    )

    # Spawn the turn driver as a background task. Hold strong references
    # in BOTH the per-consumer set (so chat.stop on this connection can
    # find its in-flight turns) AND a module-level set (so the task
    # survives WS disconnect — see _TURN_BG_TASKS docstring). Also index
    # by slug so the turn-state API can find this task in O(1).
    task = asyncio.create_task(
        _run_turn_driver(consumer, result.assistant_message_id)
    )
    slug = consumer.slug
    consumer._turn_tasks.add(task)
    _TURN_BG_TASKS.add(task)
    _TURN_TASKS_BY_SLUG[slug] = task

    def _on_done(t: asyncio.Task) -> None:
        consumer._turn_tasks.discard(t)
        _TURN_BG_TASKS.discard(t)
        # Only clear the slug index if the entry is still this task —
        # a concurrent chat.send could have replaced it with a new turn.
        if _TURN_TASKS_BY_SLUG.get(slug) is t:
            _TURN_TASKS_BY_SLUG.pop(slug, None)

    task.add_done_callback(_on_done)


async def _handle_chat_stop(consumer: SessionConsumer, data: dict):
    if not consumer._is_editor():
        await consumer._error("forbidden", "viewers cannot stop a stream")
        return
    message_id = data.get("message_id")
    if not isinstance(message_id, int):
        await consumer._error("bad_request", "chat.stop requires message_id")
        return
    r = await redis_client.get_redis()
    await r.set(f"turn.stop:{message_id}", "1", ex=60)


async def _run_turn_driver(consumer: SessionConsumer, assistant_message_id: int):
    """Run the turn driver and broadcast its events to the session group.

    Polls the Redis stop key each loop iteration via a local
    asyncio.Event mirror, so cross-task cancellation works when a
    different consumer's chat.stop fires.
    """
    stop_event = asyncio.Event()

    async def watch_stop():
        r = await redis_client.get_redis()
        while not stop_event.is_set():
            value = await r.get(f"turn.stop:{assistant_message_id}")
            if value is not None:
                stop_event.set()
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(watch_stop())
    try:
        partial = 0
        async for event in turn_driver.drive_assistant_turn(
            assistant_message_id=assistant_message_id, stop_event=stop_event
        ):
            await _broadcast_stream_event(consumer, assistant_message_id, event)
            if event.type is StreamEventType.DELTA and event.text:
                partial += len(event.text)
            if event.type is StreamEventType.DONE:
                await consumer.channel_layer.group_send(
                    _group_name(consumer.slug),
                    {
                        "type": "chat.stream_complete",
                        "data": {
                            "message_id": assistant_message_id,
                            "plaintext": await sync_to_async(_load_plaintext)(
                                assistant_message_id
                            ),
                        },
                    },
                )
                return
            if event.type is StreamEventType.ERROR:
                await consumer.channel_layer.group_send(
                    _group_name(consumer.slug),
                    {
                        "type": "chat.stream_error",
                        "data": {
                            "message_id": assistant_message_id,
                            "detail": event.error or "unknown",
                        },
                    },
                )
                return
        if stop_event.is_set():
            await consumer.channel_layer.group_send(
                _group_name(consumer.slug),
                {
                    "type": "chat.stream_cancelled",
                    "data": {
                        "message_id": assistant_message_id,
                        "partial_len": partial,
                    },
                },
            )
    finally:
        stop_event.set()
        watcher.cancel()
        r = await redis_client.get_redis()
        await r.delete(f"turn.stop:{assistant_message_id}")


async def _broadcast_stream_event(
    consumer: SessionConsumer, message_id: int, event: StreamEvent
):
    if event.type is StreamEventType.DELTA:
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "chat.delta",
                "data": {"message_id": message_id, "text": event.text},
            },
        )
    elif event.type is StreamEventType.TOOL_USE:
        tool_id = await sync_to_async(_most_recent_tool_row_id)(
            consumer.slug, "tool_use"
        )
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "chat.tool_use",
                "data": {
                    "parent_message_id": message_id,
                    "tool_message_id": tool_id,
                    "block": event.tool_block,
                },
            },
        )
    elif event.type is StreamEventType.TOOL_RESULT:
        tool_id = await sync_to_async(_most_recent_tool_row_id)(
            consumer.slug, "tool_result"
        )
        await consumer.channel_layer.group_send(
            _group_name(consumer.slug),
            {
                "type": "chat.tool_result",
                "data": {
                    "parent_message_id": message_id,
                    "tool_message_id": tool_id,
                    "block": event.tool_block,
                },
            },
        )


def _slug_and_turn_for_message(message_id: int):
    """Return (session_slug, turn_index) for an assistant message, or None."""
    m = (
        Message.objects.select_related("session")
        .filter(pk=message_id)
        .first()
    )
    if m is None:
        return None
    return (m.session.slug, m.turn_index)


async def drive_and_broadcast(assistant_message_id: int) -> None:
    """Drive a single assistant turn WITHOUT a WebSocket consumer, broadcasting
    every event to the session's channel-layer group exactly as
    ``_run_turn_driver`` does.

    This is the programmatic/headless equivalent of a human opening the
    workbench and sending a message: the turn runs through the identical
    ``drive_assistant_turn`` state machine, and because it broadcasts to
    ``session.<slug>``, a client that opens the session sees it live (and the
    DB is persisted regardless). Invoked by the ``drive_turn`` management
    command, which the seeded-run action launches as a detached process so the
    run is decoupled from the request lifecycle. See ace-web#585.
    """
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    info = await sync_to_async(_slug_and_turn_for_message)(assistant_message_id)
    if info is None:
        logger.warning("drive_and_broadcast: message %s not found", assistant_message_id)
        return
    slug, turn_index = info
    group = _group_name(slug)
    stop_event = asyncio.Event()

    await channel_layer.group_send(
        group,
        {"type": "chat.stream_start",
         "data": {"message_id": assistant_message_id, "turn_index": turn_index}},
    )
    try:
        async for event in turn_driver.drive_assistant_turn(
            assistant_message_id=assistant_message_id, stop_event=stop_event
        ):
            if event.type is StreamEventType.DELTA:
                await channel_layer.group_send(
                    group,
                    {"type": "chat.delta",
                     "data": {"message_id": assistant_message_id, "text": event.text}},
                )
            elif event.type is StreamEventType.TOOL_USE:
                tid = await sync_to_async(_most_recent_tool_row_id)(slug, "tool_use")
                await channel_layer.group_send(
                    group,
                    {"type": "chat.tool_use",
                     "data": {"parent_message_id": assistant_message_id,
                              "tool_message_id": tid, "block": event.tool_block}},
                )
            elif event.type is StreamEventType.TOOL_RESULT:
                tid = await sync_to_async(_most_recent_tool_row_id)(slug, "tool_result")
                await channel_layer.group_send(
                    group,
                    {"type": "chat.tool_result",
                     "data": {"parent_message_id": assistant_message_id,
                              "tool_message_id": tid, "block": event.tool_block}},
                )
            elif event.type is StreamEventType.DONE:
                plaintext = await sync_to_async(_load_plaintext)(assistant_message_id)
                await channel_layer.group_send(
                    group,
                    {"type": "chat.stream_complete",
                     "data": {"message_id": assistant_message_id,
                              "plaintext": plaintext}},
                )
                return
            elif event.type is StreamEventType.ERROR:
                await channel_layer.group_send(
                    group,
                    {"type": "chat.stream_error",
                     "data": {"message_id": assistant_message_id,
                              "detail": event.error or "unknown"}},
                )
                return
    except Exception:
        logger.exception(
            "drive_and_broadcast failed for assistant message %s", assistant_message_id
        )


# ────────────────────── sync DB helpers ──────────────────────

def _participant_role(slug: str, user_id: int) -> str | None:
    """Look up the user's role in the session.

    If the user is already a participant, return their role.

    Otherwise, auto-join them as `editor` IF they're allowed to access
    the session — for workspace-tied sessions that means workspace
    membership; for orphan sessions that means session ownership.
    Strangers (non-members of the session's workspace, non-owners of
    an orphan session) get None and the consumer rejects the
    handshake with close 4003.

    Auto-join on first socket connect preserves the presence + draft +
    message semantics (which key off the participant row) for users
    who are entitled to the session in the first place.
    """
    session = (
        Session.objects.select_related("workspace")
        .filter(slug=slug)
        .first()
    )
    if session is None:
        return None
    role = (
        SessionParticipant.objects.filter(session_id=session.pk, user_id=user_id)
        .values_list("role", flat=True)
        .first()
    )
    if role is not None:
        return role

    # Not a participant yet — gate auto-join on workspace/owner.
    if session.workspace_id is not None:
        # Local imports avoid an apps.auth ↔ apps.sessions import-order
        # tangle at module load time.
        from apps.auth.models import User as _User
        from apps.workspaces.permissions import is_member
        try:
            user_obj = _User.objects.get(pk=user_id)
        except _User.DoesNotExist:
            return None
        if not is_member(user_obj, session.workspace):
            return None
    else:
        # Orphan session — only the owner may auto-join.
        if session.owner_id != user_id:
            return None

    SessionParticipant.objects.get_or_create(
        session_id=session.pk, user_id=user_id,
        defaults={"role": "editor"},
    )
    return "editor"


def _session_pk_for(slug: str) -> int | None:
    return Session.objects.filter(slug=slug).values_list("pk", flat=True).first()


def _load_session(slug: str) -> Session | None:
    try:
        return Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None


def _activate_imported_session(session: Session) -> None:
    """Transition an imported session to active on first send."""
    Session.objects.filter(pk=session.pk, status="imported").update(status="active")
    session.status = "active"


def _sync_build_state(slug: str, user) -> dict:
    session = Session.objects.prefetch_related(
        Prefetch("messages", queryset=Message.objects.order_by("turn_index")),
        Prefetch("participants__user"),
    ).get(slug=slug)
    messages = list(session.messages.all())
    participants = list(session.participants.all())
    # Eagerly create the active draft on connect so the client never has
    # to handle a null active_draft and the first keystroke does not race
    # with draft creation.
    active_draft = drafts.get_or_create_active_draft(session, user)
    return {
        "messages": MessageSerializer(messages, many=True).data,
        "active_draft": DraftSerializer(active_draft).data,
        "participants": ParticipantSerializer(participants, many=True).data,
    }


def _active_draft_id(slug: str, user) -> int | None:
    try:
        session = Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None
    draft = drafts.get_or_create_active_draft(session, user)
    return draft.id


def _current_holder_id(draft_id: int) -> int | None:
    return (
        Draft.objects.filter(pk=draft_id)
        .values_list("last_editor_id", flat=True)
        .first()
    )


def _get_draft(draft_id: int) -> Draft:
    return Draft.objects.get(pk=draft_id)


def _load_plaintext(message_id: int) -> str:
    return (
        Message.objects.filter(pk=message_id)
        .values_list("plaintext", flat=True)
        .first()
        or ""
    )


def _turn_index_for(message_id: int) -> int:
    return (
        Message.objects.filter(pk=message_id)
        .values_list("turn_index", flat=True)
        .first()
        or 0
    )


def _most_recent_tool_row_id(slug: str, role: str) -> int:
    return (
        Message.objects.filter(session__slug=slug, role=role)
        .order_by("-turn_index")
        .values_list("pk", flat=True)
        .first()
    ) or 0


def _draft_payload(draft: Draft) -> dict:
    return DraftSerializer(draft).data


_HANDLERS = {
    "chat.send": _handle_chat_send,
    "chat.stop": _handle_chat_stop,
    "draft.update": _handle_draft_update,
    "draft.take_over": _handle_draft_take_over,
    "draft.discard": _handle_draft_discard,
    "presence.heartbeat": _handle_presence_heartbeat,
}
