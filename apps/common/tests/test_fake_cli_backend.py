"""Unit tests for FakeCLIBackend."""
import pytest

from apps.common.chat_backend import StreamEventType
from apps.common.fake_cli_backend import FakeCLIBackend


@pytest.mark.asyncio
async def test_fake_backend_yields_deltas_then_done():
    backend = FakeCLIBackend()
    events = []
    async for event in backend.stream_completion(
        session=None, new_user_message="hi"
    ):
        events.append(event)

    # Last event is DONE
    assert events[-1].type is StreamEventType.DONE
    # All preceding events are DELTA
    assert all(
        e.type is StreamEventType.DELTA for e in events[:-1]
    )
    # Concatenated delta text equals the scripted echo response
    combined = "".join(
        e.text for e in events[:-1] if e.text is not None
    )
    assert combined == "Echo: hi"


@pytest.mark.asyncio
async def test_fake_backend_accepts_keyword_args_like_cli_backend():
    """Ensure the signature matches CLIBackend.stream_completion so
    turn_driver can swap them without a type error."""
    backend = FakeCLIBackend()
    events = []
    async for event in backend.stream_completion(
        session=None,
        new_user_message="test",
        force_fresh_session=True,
    ):
        events.append(event)
    assert len(events) >= 2  # at least one delta + done
