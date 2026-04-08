"""Tests for the ChatBackend Protocol and StreamEvent record types."""
import pytest

from apps.common.chat_backend import ChatBackend, StreamEvent, StreamEventType


def test_stream_event_type_enum_values():
    assert StreamEventType.DELTA.value == "delta"
    assert StreamEventType.TOOL_USE.value == "tool_use"
    assert StreamEventType.TOOL_RESULT.value == "tool_result"
    assert StreamEventType.SESSION_ID.value == "session_id"
    assert StreamEventType.DONE.value == "done"
    assert StreamEventType.ERROR.value == "error"


def test_delta_event_construction():
    e = StreamEvent.delta(text="hello")
    assert e.type is StreamEventType.DELTA
    assert e.text == "hello"
    assert e.tool_block is None
    assert e.session_id is None
    assert e.error is None


def test_tool_use_event_construction():
    block = {"id": "toolu_01", "name": "Read", "input": {"file_path": "/x"}}
    e = StreamEvent.tool_use(block=block)
    assert e.type is StreamEventType.TOOL_USE
    assert e.tool_block == block
    assert e.text is None


def test_tool_result_event_construction():
    block = {"tool_use_id": "toolu_01", "content": "file contents"}
    e = StreamEvent.tool_result(block=block)
    assert e.type is StreamEventType.TOOL_RESULT
    assert e.tool_block == block


def test_session_id_event_construction():
    e = StreamEvent.for_session_id(session_id="sess_abc123")
    assert e.type is StreamEventType.SESSION_ID
    assert e.session_id == "sess_abc123"


def test_done_event_construction():
    e = StreamEvent.done()
    assert e.type is StreamEventType.DONE


def test_error_event_construction():
    e = StreamEvent.for_error(message="model failed")
    assert e.type is StreamEventType.ERROR
    assert e.error == "model failed"


def test_chat_backend_is_protocol():
    """ChatBackend is a runtime-checkable Protocol with one method."""
    assert hasattr(ChatBackend, "stream_completion")
    # Protocols cannot be instantiated directly
    with pytest.raises(TypeError):
        ChatBackend()


def test_stream_event_is_frozen():
    from dataclasses import FrozenInstanceError
    e = StreamEvent.delta(text="hello")
    with pytest.raises(FrozenInstanceError):
        e.text = "mutated"  # type: ignore[misc]


def test_chat_backend_runtime_isinstance_check():
    """A concrete implementation satisfying the Protocol should pass isinstance,
    and its stream_completion should be an async iterator (not a plain coroutine)."""
    from collections.abc import AsyncIterator

    from apps.sessions.models import Session

    class _FakeBackend:
        async def stream_completion(
            self, *, session: Session, new_user_message: str
        ) -> AsyncIterator[StreamEvent]:
            yield StreamEvent.delta(text="ok")
            yield StreamEvent.done()

    fake = _FakeBackend()
    assert isinstance(fake, ChatBackend)
