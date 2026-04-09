"""Tests for apps.sessions.turn_driver.drive_assistant_turn.

Stubs ChatBackend with a scripted StreamEvent sequence and asserts both
the events yielded by drive_assistant_turn AND the final DB state of
the Message row.
"""
import asyncio
from unittest.mock import patch

import pytest

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.sessions import turn_driver
from apps.sessions.models import Message, Session, SessionParticipant

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    return s


@pytest.fixture
def user_and_assistant_messages(session):
    user_msg = Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    asst_msg = Message.objects.create(
        session=session, turn_index=2, role="assistant",
        content={"text": ""}, plaintext="", status="pending",
    )
    return user_msg, asst_msg


class FakeBackend:
    def __init__(self, events):
        self._events = events

    async def stream_completion(self, *, session, new_user_message, **kwargs):
        for e in self._events:
            yield e


async def _drain(agen):
    out = []
    async for item in agen:
        out.append(item)
    return out


async def test_happy_path_marks_complete_and_yields_events(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages
    events = [
        StreamEvent.delta(text="Hel"),
        StreamEvent.delta(text="lo"),
        StreamEvent.done(),
    ]
    stop_event = asyncio.Event()
    with patch("apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)):
        yielded = await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    # Backend events pass through 1:1 (plus maybe an implicit DONE dedup).
    assert any(e.type is StreamEventType.DELTA and e.text == "Hel" for e in yielded)
    assert any(e.type is StreamEventType.DELTA and e.text == "lo" for e in yielded)

    from asgiref.sync import sync_to_async
    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "complete"
    assert refreshed.plaintext == "Hello"


async def test_tool_use_creates_nested_message_row(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages
    events = [
        StreamEvent.delta(text="Let me search."),
        StreamEvent.tool_use(block={"name": "Grep", "id": "tool-1"}),
        StreamEvent.tool_result(block={"tool_use_id": "tool-1", "content": "ok"}),
        StreamEvent.done(),
    ]
    stop_event = asyncio.Event()
    with patch("apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)):
        await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    from asgiref.sync import sync_to_async

    def _load_roles():
        return list(
            Message.objects.filter(session=session)
            .order_by("turn_index")
            .values_list("role", flat=True)
        )

    roles = await sync_to_async(_load_roles)()
    assert "tool_use" in roles
    assert "tool_result" in roles


async def test_error_event_marks_message_error(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages
    events = [StreamEvent.for_error(message="boom")]
    stop_event = asyncio.Event()
    with patch("apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)):
        await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    from asgiref.sync import sync_to_async
    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "error"
    assert "boom" in refreshed.error_detail


async def test_stop_event_cancels_mid_stream(
    session, user_and_assistant_messages
):
    _user, asst = user_and_assistant_messages

    class SlowBackend:
        async def stream_completion(self, **kwargs):
            yield StreamEvent.delta(text="partial ")
            # Block forever; the stop_event should pull the plug.
            await asyncio.sleep(3600)
            yield StreamEvent.done()

    stop_event = asyncio.Event()

    async def run_and_stop():
        agen = turn_driver.drive_assistant_turn(
            assistant_message_id=asst.id, stop_event=stop_event
        )
        collected = []
        async for event in agen:
            collected.append(event)
            stop_event.set()
        return collected

    with patch("apps.sessions.turn_driver._get_backend", return_value=SlowBackend()):
        await asyncio.wait_for(run_and_stop(), timeout=5)

    from asgiref.sync import sync_to_async
    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "error"
    assert "cancelled" in refreshed.error_detail
