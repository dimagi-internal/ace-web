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


async def test_mark_complete_runs_even_if_caller_early_returns_on_done(
    session, user_and_assistant_messages
):
    """Regression test for the Phase 3 bug where _mark_complete was
    called AFTER yield and was therefore never reached when the
    consumer (_run_turn_driver) early-returned on DONE."""
    _user, asst = user_and_assistant_messages
    events = [
        StreamEvent.delta(text="complete"),
        StreamEvent.done(),
    ]
    stop_event = asyncio.Event()

    # Simulate the consumer's early-return pattern: break out of the
    # async for as soon as we see DONE, without waiting for the
    # generator to finish its own cleanup.
    async def early_return_consumer():
        collected = []
        with patch(
            "apps.sessions.turn_driver._get_backend",
            return_value=FakeBackend(events),
        ):
            agen = turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
            async for event in agen:
                collected.append(event)
                if event.type is StreamEventType.DONE:
                    return collected  # triggers GeneratorExit on agen
            return collected

    await early_return_consumer()

    from asgiref.sync import sync_to_async
    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "complete"
    assert refreshed.plaintext == "complete"


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


async def test_stop_event_cancels_while_backend_blocks(
    session, user_and_assistant_messages
):
    """Exercises the _iter_until_stop race path: the backend never yields
    once, so the only way for cancellation to fire is via asyncio.wait
    picking stop_event.wait() over agen.__anext__().
    """
    _user, asst = user_and_assistant_messages

    class BlockingBackend:
        def __init__(self):
            self.entered = asyncio.Event()

        async def stream_completion(self, **kwargs):
            self.entered.set()
            await asyncio.sleep(3600)
            yield StreamEvent.done()  # unreachable

    backend = BlockingBackend()
    stop_event = asyncio.Event()

    async def driver():
        out = []
        agen = turn_driver.drive_assistant_turn(
            assistant_message_id=asst.id, stop_event=stop_event
        )
        async for event in agen:
            out.append(event)
        return out

    with patch("apps.sessions.turn_driver._get_backend", return_value=backend):
        task = asyncio.create_task(driver())
        await backend.entered.wait()
        await asyncio.sleep(0.05)  # ensure driver is inside asyncio.wait
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

    from asgiref.sync import sync_to_async
    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "error"
    assert "cancelled" in refreshed.error_detail


def test_get_backend_returns_fake_when_setting_enabled(settings):
    """When ACE_USE_FAKE_CLI_BACKEND is True, _get_backend() must
    return a FakeCLIBackend instance instead of the real CLIBackend."""
    from apps.common.fake_cli_backend import FakeCLIBackend
    from apps.sessions import turn_driver

    settings.ACE_USE_FAKE_CLI_BACKEND = True
    backend = turn_driver._get_backend()
    assert isinstance(backend, FakeCLIBackend)


def test_get_backend_returns_real_when_setting_disabled(settings):
    """Default (setting False) must return the real CLIBackend."""
    from apps.common.cli_backend import CLIBackend
    from apps.sessions import turn_driver

    settings.ACE_USE_FAKE_CLI_BACKEND = False
    # With no CLI token and no API key, the selector picks CLIBackend as
    # the dead-end fallback so the user sees a clear CLI error.
    settings.ANTHROPIC_API_KEY = ""
    backend = turn_driver._get_backend()
    assert isinstance(backend, CLIBackend)


class _StubChannelLayer:
    """Records group_send calls so a test can assert broadcasts without redis."""

    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


async def test_drive_and_broadcast_drives_to_completion_and_broadcasts(
    session, user_and_assistant_messages
):
    """consumers.drive_and_broadcast drives the SAME turn-driver state machine
    as a WS turn (DB → complete) AND broadcasts stream_start + stream_complete
    to the session group — so a programmatically-launched run is a normal,
    openable, live session. This is the path the seeded-run action uses via the
    drive_turn management command (ace-web#585)."""
    from apps.sessions.consumers import drive_and_broadcast

    _user, asst = user_and_assistant_messages
    events = [StreamEvent.delta(text="done"), StreamEvent.done()]
    stub = _StubChannelLayer()
    with patch(
        "apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)
    ), patch("channels.layers.get_channel_layer", return_value=stub):
        await drive_and_broadcast(asst.id)

    from asgiref.sync import sync_to_async

    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "complete"
    assert refreshed.plaintext == "done"
    kinds = [m["type"] for _g, m in stub.sent]
    assert "chat.stream_start" in kinds
    assert "chat.stream_complete" in kinds
    assert all(g == f"session.{session.slug}" for g, _m in stub.sent)


class RawSinkBackend:
    """Backend that fills raw_sink with JSONL (like the real CLIBackend), so the
    turn driver computes a cost breakdown for the web-source session."""

    async def stream_completion(self, *, session, new_user_message, raw_sink=None, **kwargs):
        if raw_sink is not None:
            raw_sink.append('{"type":"system","subtype":"init","session_id":"x"}\n')
            raw_sink.append(
                '{"type":"assistant","timestamp":"2026-01-01T00:00:00.000Z",'
                '"message":{"role":"assistant","model":"claude-sonnet-4-6",'
                '"content":[{"type":"text","text":"hi"}],'
                '"usage":{"input_tokens":3,"output_tokens":9,'
                '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
            )
        yield StreamEvent.delta(text="hi")
        yield StreamEvent.done()


async def test_persists_cost_breakdown_from_captured_transcript(
    session, user_and_assistant_messages
):
    """End-to-end: a turn through a backend that streams JSONL ends with the
    session's cost_breakdown populated (web-source analyzer parity)."""
    _user, asst = user_and_assistant_messages
    stop_event = asyncio.Event()
    with patch(
        "apps.sessions.turn_driver._get_backend", return_value=RawSinkBackend()
    ):
        await _drain(
            turn_driver.drive_assistant_turn(
                assistant_message_id=asst.id, stop_event=stop_event
            )
        )

    from asgiref.sync import sync_to_async
    refreshed = await sync_to_async(Session.objects.get)(pk=session.pk)
    assert refreshed.cost_breakdown.get("totals", {}).get("output_tokens") == 9


async def test_post_done_cancel_does_not_overwrite_complete(
    session, user_and_assistant_messages
):
    """The headless path's failure mode: the consumer returns the instant it
    gets DONE, leaving drive_assistant_turn suspended at the post-DONE yield.
    asyncio.run's shutdown then cancels that suspended generator. The
    CancelledError handler must NOT overwrite the already-persisted 'complete'
    status with 'cancelled' — that spurious mislabel was the "runs cancelled
    mid-flight ~Nmin in" symptom (no signal, no real error, variable timing).
    """
    import contextlib

    from asgiref.sync import sync_to_async

    _user, asst = user_and_assistant_messages
    events = [StreamEvent.delta(text="done-text"), StreamEvent.done()]
    stop_event = asyncio.Event()

    with patch(
        "apps.sessions.turn_driver._get_backend", return_value=FakeBackend(events)
    ):
        agen = turn_driver.drive_assistant_turn(
            assistant_message_id=asst.id, stop_event=stop_event
        )
        # Pull until DONE, then break — leaving the generator suspended at the
        # post-DONE yield (it has already marked the message 'complete').
        async for event in agen:
            if event.type is StreamEventType.DONE:
                break
        mid = await sync_to_async(Message.objects.get)(pk=asst.id)
        assert mid.status == "complete"  # terminal status persisted

        # Simulate asyncio.run shutdown cancelling the suspended generator.
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await agen.athrow(asyncio.CancelledError())

    refreshed = await sync_to_async(Message.objects.get)(pk=asst.id)
    assert refreshed.status == "complete", (
        "shutdown cancel overwrote a finished turn's status with 'cancelled'"
    )
