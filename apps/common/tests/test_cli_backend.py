"""Tests for CLIBackend. Subprocess is mocked at the asyncio.create_subprocess_exec
level so the tests do not actually invoke the claude CLI binary."""
from itertools import chain, repeat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError
from apps.sessions.models import Message, Session

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def session(django_user_model):
    """Sync fixture that creates a session. Tests that mutate it from async
    context must do so via sync_to_async wrappers."""
    user = django_user_model.objects.create_user(
        email="test@example.com", display_name="test"
    )
    return Session.objects.create(owner=user, title="test")


def _fake_proc(stdout_bytes: bytes, returncode: int = 0):
    """Build a mock that quacks like asyncio.subprocess.Process."""
    proc = AsyncMock()
    proc.stdout = AsyncMock()
    # Real StreamReader.readline() returns b"" forever at EOF — simulate that
    # with chain(lines, repeat(b"")) so we never raise StopIteration.
    lines = list(stdout_bytes.splitlines(keepends=True))
    iterator = chain(lines, repeat(b""))
    proc.stdout.readline = AsyncMock(side_effect=lambda: next(iterator))
    # Start as None (not yet exited) — just like a real asyncio.subprocess.Process.
    # wait() sets returncode to mirror real behaviour so _cleanup can detect
    # a still-running process (returncode is None) vs. one that already exited.
    proc.returncode = None

    async def _wait():
        proc.returncode = returncode
        return returncode

    proc.wait = AsyncMock(side_effect=_wait)
    proc.terminate = lambda: None
    proc.kill = lambda: None
    proc.pid = 12345
    # stdin mock — _spawn writes the user-message envelope + drains.
    # _drain closes stdin after observing DONE (see "Stdin lifecycle" in
    # cli_backend.py); is_closing() is a regular bool, not awaitable.
    proc.stdin = AsyncMock()
    proc.stdin.write = lambda data: None
    proc.stdin.drain = AsyncMock()
    proc.stdin._closed = False
    def _close():
        proc.stdin._closed = True
    proc.stdin.close = _close
    proc.stdin.is_closing = lambda: proc.stdin._closed
    return proc


async def test_fresh_session_captures_session_id(session):
    fixture = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    backend = CLIBackend()

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_fake_proc(fixture)),
    ):
        events = []
        async for e in backend.stream_completion(session=session, new_user_message="hi"):
            events.append(e)

    types = [e.type for e in events]
    assert StreamEventType.SESSION_ID in types
    assert StreamEventType.DONE in types

    # Session row should have the captured cli_session_id persisted
    await sync_to_async(session.refresh_from_db)()
    assert session.cli_session_id == "sess_abc123"


async def test_resume_uses_existing_cli_session_id(session):
    session.cli_session_id = "sess_existing"
    await sync_to_async(session.save)()
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()

    create = AsyncMock(return_value=_fake_proc(fixture))
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

    args = create.call_args[0]
    assert "--resume" in args
    assert "sess_existing" in args


async def test_spawn_passes_dangerously_skip_permissions(session):
    """Without --dangerously-skip-permissions, claude -p answers as a
    plain chatbot and the entire ACE plugin is unreachable. Regression
    guard for that flag landing in every subprocess invocation."""
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()
    create = AsyncMock(return_value=_fake_proc(fixture))
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass
    args = create.call_args[0]
    assert "--dangerously-skip-permissions" in args, (
        f"missing --dangerously-skip-permissions in spawn args: {args!r}"
    )


async def test_spawn_uses_stream_json_input_format(session):
    """Stream-json input is the canonical multi-turn wire format. Without
    --input-format stream-json the CLI treats stdin as raw text, which means
    no JSON-quoting of the user message and no clean path to multi-turn."""
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()
    create = AsyncMock(return_value=_fake_proc(fixture))
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass
    args = create.call_args[0]
    assert "--input-format" in args, f"missing --input-format: {args!r}"
    assert "stream-json" in args
    # input-format and output-format both pass stream-json; assert the input
    # one is paired correctly by index
    idx = args.index("--input-format")
    assert args[idx + 1] == "stream-json"


async def test_spawn_writes_user_message_as_json_envelope(session):
    """On the resume path, the new user message goes onto stdin wrapped in a
    stream-json envelope: {"type":"user","message":{"role":"user","content":"<text>"}}\\n
    The seeded-history path concatenates history into one prompt string and
    wraps the whole concatenation in the same envelope (covered by the
    existing test_resume_failure_falls_back_to_full_history which exercises
    that path)."""
    import json as _json

    session.cli_session_id = "sess_resume"
    await sync_to_async(session.save)()
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)
    written: list[bytes] = []
    fake.stdin.write = lambda data: written.append(data)

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(
            session=session, new_user_message="hello world"
        ):
            pass

    assert written, "nothing was written to stdin"
    payload = b"".join(written).decode("utf-8").strip()
    parsed = _json.loads(payload)
    assert parsed["type"] == "user"
    assert parsed["message"]["role"] == "user"
    assert parsed["message"]["content"] == "hello world"


async def test_drain_closes_stdin_after_done_event(session):
    """--input-format stream-json keeps the CLI reading stdin until EOF; if
    we never close stdin the subprocess hangs forever after the turn finishes.
    The drain loop must close stdin once it sees the result/DONE event so
    the CLI exits cleanly."""
    # stream_json_simple.txt ends with a result event → produces a DONE.
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)
    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

    assert fake.stdin._closed, (
        "stdin was never closed — CLI would hang forever waiting for the next "
        "user message"
    )


async def test_resume_yields_events_as_they_arrive_not_buffered(session):
    """Critical: streaming UX requires real-time token delivery, not buffer-and-dump.

    This test ensures the resume path yields events while the subprocess is
    still running, not after proc.wait() completes.
    """
    session.cli_session_id = "sess_hot"
    await sync_to_async(session.save)()
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()

    call_order = []
    fake = _fake_proc(fixture)

    # Record when proc.wait is called relative to when events are yielded.
    async def tracking_wait(*args, **kwargs):
        call_order.append("wait")
        fake.returncode = 0
        return 0
    fake.wait = AsyncMock(side_effect=tracking_wait)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for e in backend.stream_completion(session=session, new_user_message="hi"):
            call_order.append(f"yield:{e.type.value}")

    # Events must be yielded BEFORE proc.wait is called (streaming, not buffering)
    first_wait_index = call_order.index("wait")
    assert any(
        item.startswith("yield:") for item in call_order[:first_wait_index]
    ), f"No events yielded before proc.wait — path is buffering! Order: {call_order}"


async def test_resume_failure_falls_back_to_full_history(session):
    """If --resume returns non-zero with no events, restart fresh and seed history."""
    session.cli_session_id = "sess_dead"
    await sync_to_async(session.save)()
    await sync_to_async(Message.objects.create)(
        session=session,
        turn_index=1,
        role="user",
        content={"text": "first turn from yesterday"},
        plaintext="first turn from yesterday",
        status="complete",
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
    # Session id should be replaced with the freshly captured one
    await sync_to_async(session.refresh_from_db)()
    assert session.cli_session_id == "sess_abc123"


async def test_cancellation_terminates_subprocess(session):
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        gen = backend.stream_completion(session=session, new_user_message="hi")
        async for _ in gen:
            break  # cancel after first event
        # Explicitly close the async generator so the finally block runs and
        # subprocess cleanup happens before we assert. (Python schedules
        # aclose() lazily for async generators, so explicit close is needed
        # in tests — in production the event loop shutdown handles it.)
        await gen.aclose()

    assert terminated == ["term"]


async def test_circuit_breaker_opens_after_repeated_failures(session):
    backend = CLIBackend(circuit_threshold=2, circuit_cooldown=10)
    # Each call gets its own fresh mock proc because the readline iterator
    # is stateful — circuit breaker test calls the backend 3 times.

    def make_failing():
        return _fake_proc(b"", returncode=1)

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=lambda *a, **kw: make_failing()),
    ):
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
        # Third call should fail-fast on circuit breaker, never invoking subprocess
        with pytest.raises(CLIBackendError) as exc_info:
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
    assert "circuit" in str(exc_info.value).lower()
