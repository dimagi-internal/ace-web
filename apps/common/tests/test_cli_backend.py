"""Tests for CLIBackend. Subprocess is mocked at the asyncio.create_subprocess_exec
level so the tests do not actually invoke the claude CLI binary."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError
from apps.sessions.models import Message, Session

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="test@example.com", display_name="test"
    )
    return Session.objects.create(owner=user, title="test")


def _fake_proc(stdout_bytes: bytes, returncode: int = 0):
    """Build a mock that quacks like asyncio.subprocess.Process."""
    proc = AsyncMock()
    proc.stdout = AsyncMock()
    # Simulate readline() draining the buffer line by line
    lines = list(stdout_bytes.splitlines(keepends=True)) + [b""]
    iterator = iter(lines)
    proc.stdout.readline = AsyncMock(side_effect=lambda: next(iterator))
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.terminate = lambda: None
    proc.kill = lambda: None
    proc.pid = 12345
    # stdin mock — _spawn writes to it
    proc.stdin = AsyncMock()
    proc.stdin.write = lambda data: None
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = lambda: None
    return proc


async def test_fresh_session_captures_session_id(session):
    fixture = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    backend = CLIBackend()

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_proc(fixture))):
        events = []
        async for e in backend.stream_completion(session=session, new_user_message="hi"):
            events.append(e)

    types = [e.type for e in events]
    assert StreamEventType.SESSION_ID in types
    assert StreamEventType.DONE in types

    session.refresh_from_db()
    assert session.cli_session_id == "sess_abc123"


async def test_resume_uses_existing_cli_session_id(session):
    session.cli_session_id = "sess_existing"
    session.save()
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()

    create = AsyncMock(return_value=_fake_proc(fixture))
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

    args = create.call_args[0]
    assert "--resume" in args
    assert "sess_existing" in args


async def test_resume_failure_falls_back_to_full_history(session):
    """If --resume returns non-zero with no events, restart fresh and seed history."""
    session.cli_session_id = "sess_dead"
    session.save()
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "first turn from yesterday"},
        plaintext="first turn from yesterday", status="complete",
    )

    failing = _fake_proc(b"", returncode=1)
    succeeding = _fake_proc((FIXTURES / "stream_json_session_init.txt").read_bytes())

    backend = CLIBackend()
    create = AsyncMock(side_effect=[failing, succeeding])
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="next turn"):
            pass

    assert create.call_count == 2
    second_call_args = create.call_args_list[1][0]
    # Second call must NOT have --resume
    assert "--resume" not in second_call_args
    # And the session id should be replaced with the freshly captured one
    session.refresh_from_db()
    assert session.cli_session_id == "sess_abc123"


async def test_cancellation_terminates_subprocess(session):
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            break  # cancel after first event

    assert terminated == ["term"]


async def test_circuit_breaker_opens_after_repeated_failures(session):
    backend = CLIBackend(circuit_threshold=2, circuit_cooldown=10)
    failing = _fake_proc(b"", returncode=1)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=failing)):
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
        # Third call should fail-fast on circuit breaker
        with pytest.raises(CLIBackendError) as exc_info:
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
    assert "circuit" in str(exc_info.value).lower()
