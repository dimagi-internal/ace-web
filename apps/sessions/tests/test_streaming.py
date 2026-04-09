"""Tests for the SSE streaming endpoint. CLIBackend is patched to a fake that
yields a deterministic StreamEvent sequence."""
import asyncio
from unittest.mock import patch

import pytest

from apps.common.chat_backend import StreamEvent
from apps.sessions.models import Message, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )
    return Session.objects.create(owner=user, title="x")


@pytest.fixture
def assistant_message(session):
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    return Message.objects.create(
        session=session, turn_index=2, role="assistant",
        content={"text": ""}, plaintext="", status="pending",
    )


class FakeBackend:
    def __init__(self, events):
        self._events = events

    async def stream_completion(self, *, session, new_user_message, **kwargs):
        for e in self._events:
            yield e


def _consume(streaming_content) -> str:
    """Drain a streaming_content iterable (sync or async) of bytes into a string."""
    import inspect
    if inspect.isasyncgen(streaming_content):
        async def _drain():
            chunks = []
            async for chunk in streaming_content:
                chunks.append(chunk)
            return b"".join(chunks)
        return asyncio.run(_drain()).decode("utf-8")
    return b"".join(streaming_content).decode("utf-8")


def test_complete_message_replays_then_done(client_authenticated_for, session, assistant_message):
    assistant_message.status = "complete"
    assistant_message.plaintext = "hello there"
    assistant_message.save()

    client = client_authenticated_for(session.owner)
    resp = client.get(f"/api/messages/{assistant_message.id}/stream")
    body = _consume(resp.streaming_content)
    assert "event: delta" in body
    assert "hello there" in body
    assert "event: done" in body


def test_error_message_yields_error(client_authenticated_for, session, assistant_message):
    assistant_message.status = "error"
    assistant_message.error_detail = "boom"
    assistant_message.save()

    client = client_authenticated_for(session.owner)
    resp = client.get(f"/api/messages/{assistant_message.id}/stream")
    body = _consume(resp.streaming_content)
    assert "event: error" in body
    assert "boom" in body


@pytest.mark.django_db(transaction=True)
def test_pending_message_drives_backend(client_authenticated_for, session, assistant_message):
    fake = FakeBackend([
        StreamEvent.delta(text="Hi "),
        StreamEvent.delta(text="there!"),
        StreamEvent.done(),
    ])
    client = client_authenticated_for(session.owner)

    with patch("apps.sessions.streaming._get_backend", return_value=fake):
        resp = client.get(f"/api/messages/{assistant_message.id}/stream")
        body = _consume(resp.streaming_content)

    assert body.count("event: delta") == 2
    assert "event: done" in body

    assistant_message.refresh_from_db()
    assert assistant_message.status == "complete"
    assert assistant_message.plaintext == "Hi there!"


@pytest.mark.django_db(transaction=True)
def test_tool_use_event_creates_message_row(client_authenticated_for, session, assistant_message):
    fake = FakeBackend([
        StreamEvent.delta(text="Reading file"),
        StreamEvent.tool_use(block={"id": "t1", "name": "Read", "input": {"file_path": "/x"}}),
        StreamEvent.tool_result(block={"tool_use_id": "t1", "content": "file body"}),
        StreamEvent.delta(text="Done"),
        StreamEvent.done(),
    ])
    client = client_authenticated_for(session.owner)
    with patch("apps.sessions.streaming._get_backend", return_value=fake):
        resp = client.get(f"/api/messages/{assistant_message.id}/stream")
        _consume(resp.streaming_content)

    tool_messages = Message.objects.filter(
        session=session, role__in=["tool_use", "tool_result"]
    )
    assert tool_messages.count() == 2


def test_load_last_user_text_picks_correct_turn(client_authenticated_for, session):
    """C1 regression: _load_last_user_text must pick the user message that
    immediately precedes the assistant placeholder, not the most recent one
    in the whole session."""
    # Turn 1: user
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "first question"}, plaintext="first question",
        status="complete",
    )
    # Turn 2: assistant placeholder (this is what we're streaming)
    asst = Message.objects.create(
        session=session, turn_index=2, role="assistant",
        content={"text": ""}, plaintext="", status="pending",
    )
    # Turn 3: a newer user message (from a race / double-send)
    Message.objects.create(
        session=session, turn_index=3, role="user",
        content={"text": "second question"}, plaintext="second question",
        status="complete",
    )

    # _load_last_user_text should return "first question", not "second question"
    from apps.sessions.streaming import _load_last_user_text
    assert _load_last_user_text(asst) == "first question"


def test_reconnect_to_streaming_does_not_drive_backend_again(
    client_authenticated_for, session, assistant_message,
):
    """C3 regression: hitting /stream on a message that is already in
    status=streaming must replay + close, NOT start a second backend drive.
    """
    assistant_message.status = "streaming"
    assistant_message.plaintext = "partial response"
    assistant_message.save()

    from unittest.mock import MagicMock
    fake_backend = MagicMock()
    fake_backend.stream_completion = MagicMock(
        side_effect=AssertionError("backend must not be called on reconnect-to-streaming")
    )

    client = client_authenticated_for(session.owner)
    with patch("apps.sessions.streaming._get_backend", return_value=fake_backend):
        resp = client.get(f"/api/messages/{assistant_message.id}/stream")
        body = _consume(resp.streaming_content)

    assert "event: delta" in body
    assert "partial response" in body
    assert "event: done" in body
    fake_backend.stream_completion.assert_not_called()
