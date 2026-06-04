"""Tests for CLIBackend. Subprocess is mocked at the asyncio.create_subprocess_exec
level so the tests do not actually invoke the claude CLI binary."""
import asyncio
from itertools import chain, repeat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError, SessionProcess
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


def _multi_turn_fake_proc(per_turn_fixtures: list[bytes]):
    """Fake proc whose stdout emits one round of events per stdin.write.

    Use for long-lived path tests where the same subprocess serves multiple
    turns. Each call to ``proc.stdin.write`` queues the next fixture's
    stdout lines onto ``proc.stdout``, simulating the CLI processing the
    written user-message envelope and producing the next turn's events.
    Once all per_turn_fixtures are consumed, subsequent reads return b""
    (EOF) so a downstream drain raises CLIBackendError instead of hanging.
    """
    proc = AsyncMock()
    proc.stdout = AsyncMock()
    proc.returncode = None

    pending: list[bytes] = []
    fixture_iter = iter(per_turn_fixtures)

    def _queue_next_turn():
        try:
            data = next(fixture_iter)
        except StopIteration:
            return
        pending.extend(data.splitlines(keepends=True))

    async def _readline():
        if not pending:
            return b""
        return pending.pop(0)
    proc.stdout.readline = _readline

    def _write(data):
        # Each new envelope from the CLIBackend triggers the next turn's
        # output to appear on stdout.
        _queue_next_turn()
    proc.stdin = AsyncMock()
    proc.stdin.write = _write
    proc.stdin.drain = AsyncMock()
    proc.stdin._closed = False
    def _close():
        proc.stdin._closed = True
    proc.stdin.close = _close
    proc.stdin.is_closing = lambda: proc.stdin._closed

    async def _wait():
        proc.returncode = 0
        return 0
    proc.wait = AsyncMock(side_effect=_wait)
    proc.terminate = lambda: None
    proc.kill = lambda: None
    proc.pid = 67890
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


async def test_one_shot_drain_closes_stdin_after_done_event(session):
    """One-shot path (force_fresh_session=True, used by auto-titler):
    --input-format stream-json keeps the CLI reading stdin until EOF; if
    we never close stdin the subprocess hangs forever after the turn finishes.
    The one-shot drain loop must close stdin once it sees the result/DONE
    event so the CLI exits cleanly.

    The long-lived path has the OPPOSITE invariant — see
    test_long_lived_does_not_close_stdin_after_done.
    """
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)
    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(
            session=session, new_user_message="hi", force_fresh_session=True
        ):
            pass

    assert fake.stdin._closed, (
        "stdin was never closed — CLI would hang forever waiting for the next "
        "user message"
    )


async def test_one_shot_yields_events_as_they_arrive_not_buffered(session):
    """Streaming UX requires real-time token delivery, not buffer-and-dump.

    Exercises the one-shot path (force_fresh_session=True) — the long-lived
    path never calls proc.wait() in the happy path (the proc stays alive
    for the next turn) so the wait-vs-yield ordering check doesn't apply
    there. Long-lived ordering is asserted in
    test_long_lived_yields_events_before_returning.
    """
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()

    call_order = []
    fake = _fake_proc(fixture)

    async def tracking_wait(*args, **kwargs):
        call_order.append("wait")
        fake.returncode = 0
        return 0
    fake.wait = AsyncMock(side_effect=tracking_wait)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for e in backend.stream_completion(
            session=session, new_user_message="hi", force_fresh_session=True
        ):
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


async def test_circuit_breaker_isolated_per_owner(django_user_model):
    """User A tripping the breaker must not affect user B. Without the
    per-owner split, a single user's bad credentials open the breaker for
    every other user on the same ECS worker.
    """
    @sync_to_async
    def _setup():
        user_a = django_user_model.objects.create_user(
            email="a@example.com", display_name="a"
        )
        user_b = django_user_model.objects.create_user(
            email="b@example.com", display_name="b"
        )
        session_a = Session.objects.create(owner=user_a, title="a")
        session_b = Session.objects.create(owner=user_b, title="b")
        return session_a, session_b
    session_a, session_b = await _setup()

    backend = CLIBackend(circuit_threshold=2, circuit_cooldown=10)

    def make_failing():
        return _fake_proc(b"", returncode=1)
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()

    # Trip user A's breaker with 2 failures.
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=lambda *a, **kw: make_failing()),
    ):
        for _ in range(2):
            with pytest.raises(CLIBackendError):
                async for _e in backend.stream_completion(
                    session=session_a, new_user_message="x"
                ):
                    pass

    # User A's third call short-circuits with breaker open.
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=lambda *a, **kw: make_failing()),
    ):
        with pytest.raises(CLIBackendError) as exc_info_a:
            async for _e in backend.stream_completion(
                session=session_a, new_user_message="x"
            ):
                pass
    assert "circuit" in str(exc_info_a.value).lower()

    # User B's call should sail through with a healthy proc — its breaker
    # is untouched by user A's failures.
    fake_b = _fake_proc(fixture, returncode=0)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_b)):
        events_b = []
        async for ev in backend.stream_completion(
            session=session_b, new_user_message="ok"
        ):
            events_b.append(ev)
    assert events_b, "user B's call did not produce events — breaker leaked across users"


# ────────────────────────── Phase 1B: long-lived path ──────────────────────────


async def test_session_process_reused_across_turns(session):
    """Two consecutive turns for the same Session must share one subprocess
    — the whole point of Phase 1B is to amortise the ~5–30s MCP-startup
    cost across the conversation.
    """
    init = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    follow_up = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _multi_turn_fake_proc([init, follow_up])

    backend = CLIBackend()
    create = AsyncMock(return_value=fake)
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass
        async for _ in backend.stream_completion(
            session=session, new_user_message="follow up"
        ):
            pass

    assert create.call_count == 1, (
        f"long-lived path spawned a fresh subprocess for the second turn — "
        f"call_count={create.call_count}. Phase 1B requires reuse."
    )


async def test_long_lived_does_not_close_stdin_after_done(session):
    """Long-lived path MUST keep stdin open after DONE — the subprocess
    stays alive for the next turn. Closing stdin would EOF the CLI and
    cause it to exit, breaking Phase 1B's whole reason for existing.
    """
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _multi_turn_fake_proc([fixture])

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

    assert not fake.stdin._closed, (
        "long-lived path closed stdin after DONE — that would exit the "
        "CLI and force a respawn on the next turn, defeating Phase 1B"
    )


async def test_force_fresh_session_does_not_use_long_lived_pool(session):
    """Auto-titler invariant: ``force_fresh_session=True`` must spawn a
    fresh, isolated subprocess and MUST NOT add a SessionProcess to
    ``backend._sessions`` (which would let the title prompt pollute the
    long-lived chat process for this Session).
    """
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(
            session=session, new_user_message="title?", force_fresh_session=True
        ):
            pass

    assert session.slug not in backend._sessions, (
        "force_fresh_session=True added the session to the long-lived pool "
        "— the auto-titler would now pollute the chat process"
    )


async def test_long_lived_evicts_on_subprocess_pipe_death(session):
    """If the subprocess pipe dies mid-turn (BrokenPipeError on stdin
    write), the long-lived path evicts the SessionProcess and surfaces
    a CLIBackendError. Next call should be free to spawn fresh.
    """
    fixture = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    first = _multi_turn_fake_proc([fixture])
    # Simulate pipe death on the second turn's stdin write
    second = _multi_turn_fake_proc([fixture])

    backend = CLIBackend()
    create = AsyncMock(side_effect=[first, second])
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

        # Break the first proc's stdin so the next turn raises BrokenPipeError
        def _broken_write(data):
            raise BrokenPipeError("pipe is gone")
        first.stdin.write = _broken_write

        with pytest.raises(CLIBackendError) as exc_info:
            async for _ in backend.stream_completion(
                session=session, new_user_message="next"
            ):
                pass
        # BrokenPipe on stdin write surfaces as "stdin closed ..." (wrapped
        # at the write call site); BrokenPipe later (during drain) would
        # surface as "subprocess died mid-turn". Either is acceptable —
        # the test's real assertion is about eviction below.
        assert "pipe" in str(exc_info.value).lower() or "died" in str(
            exc_info.value
        ).lower()

        # SP must have been evicted
        assert session.slug not in backend._sessions

        # Third call spawns fresh (call_count = 2)
        async for _ in backend.stream_completion(
            session=session, new_user_message="recover"
        ):
            pass

    assert create.call_count == 2, (
        f"expected 2 spawns (first turn + post-eviction recovery), "
        f"got {create.call_count}"
    )


async def test_pool_lru_evicts_oldest_when_at_cap(django_user_model):
    """When the pool is at ``max_session_pool_size``, admitting a new
    Session must LRU-evict the entry with the oldest ``last_active``.
    Without this cap, a runaway client opening many sessions could pin
    unbounded RAM on the worker.
    """
    @sync_to_async
    def _make(suffix):
        user = django_user_model.objects.create_user(
            email=f"u{suffix}@example.com", display_name=f"u{suffix}"
        )
        return Session.objects.create(owner=user, title=f"s{suffix}")

    s1 = await _make("1")
    s2 = await _make("2")
    s3 = await _make("3")

    fixture = (FIXTURES / "stream_json_session_init.txt").read_bytes()

    # Cap of 2: after s1 and s2, admitting s3 must evict the LRU (s1).
    backend = CLIBackend(max_session_pool_size=2)

    def fresh_fake():
        return _multi_turn_fake_proc([fixture])

    procs = [fresh_fake(), fresh_fake(), fresh_fake()]
    terminated = []
    for i, p in enumerate(procs):
        p.terminate = lambda i=i: terminated.append(i)

    proc_iter = iter(procs)
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=lambda *a, **kw: next(proc_iter)),
    ):
        for s in (s1, s2):
            async for _ in backend.stream_completion(session=s, new_user_message="hi"):
                pass

        # Force s1 to be the LRU by advancing s2's last_active.
        backend._sessions[s2.slug].last_active += 100.0

        async for _ in backend.stream_completion(session=s3, new_user_message="hi"):
            pass

    assert s1.slug not in backend._sessions, "LRU (s1) should have been evicted"
    assert s2.slug in backend._sessions
    assert s3.slug in backend._sessions
    assert len(backend._sessions) == 2
    assert 0 in terminated, "s1's subprocess should have been terminated by LRU eviction"

    # Cleanup
    if backend._idle_reaper_task and not backend._idle_reaper_task.done():
        backend._idle_reaper_task.cancel()


async def test_idle_reaper_evicts_stale_sessions(session):
    """Reaper sweeps SessionProcesses whose last_active is older than
    the configured idle timeout — terminates the proc, persists any
    refreshed OAuth blob, rmtree's the staged HOME, drops the dict
    entry. In production the timeout is 30 min; tests use sub-second
    timeouts so the loop fires quickly.
    """
    fixture = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    fake = _multi_turn_fake_proc([fixture])
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend(
        session_idle_timeout_seconds=0.05,
        session_idle_sweep_interval_seconds=0.02,
    )

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

        assert session.slug in backend._sessions, (
            "session not added to long-lived pool after first turn"
        )

        # Wait long enough for the reaper to wake up (sleep_interval) AND
        # for last_active to be older than the timeout.
        await asyncio.sleep(0.3)

    assert session.slug not in backend._sessions, (
        "idle reaper did not evict stale session from pool"
    )
    assert terminated == ["term"], (
        "idle reaper did not terminate the subprocess"
    )

    # Cancel the reaper so the test loop can shut down cleanly.
    if backend._idle_reaper_task and not backend._idle_reaper_task.done():
        backend._idle_reaper_task.cancel()


async def test_concurrent_turns_serialized_by_per_session_lock(session):
    """Two simultaneous stream_completion calls for the same Session must
    not interleave on stdin — the per-SessionProcess lock serialises
    them. Without it, both turns would write user-message envelopes
    concurrently and the CLI would get confused.
    """
    init = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    follow_up = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _multi_turn_fake_proc([init, follow_up])

    write_order: list[str] = []
    original_write = fake.stdin.write
    def _tracking_write(data):
        # Decode the envelope's content text so we can assert ordering
        import json as _json
        envelope = _json.loads(data.decode("utf-8").strip())
        write_order.append(envelope["message"]["content"])
        original_write(data)
    fake.stdin.write = _tracking_write

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async def _drive(msg):
            async for _ in backend.stream_completion(
                session=session, new_user_message=msg
            ):
                pass

        # Kick off both turns concurrently. The lock must serialise them.
        await asyncio.gather(_drive("turn-A"), _drive("turn-B"))

    # Both turns must have written exactly one envelope each, in some
    # order. The critical assertion is that they did NOT interleave.
    assert len(write_order) == 2
    assert set(write_order) == {"turn-A", "turn-B"}


async def test_long_lived_resume_failure_falls_back_inline(session):
    """First spawn with --resume produces zero events (CLI rejected the
    stale session id) → inline recovery clears cli_session_id and
    respawns fresh with seeded history within the same stream_completion
    call. Mirror of the existing
    test_resume_failure_falls_back_to_full_history but for the
    long-lived path.
    """
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
    succeeding = _multi_turn_fake_proc([
        (FIXTURES / "stream_json_session_init.txt").read_bytes()
    ])

    backend = CLIBackend()
    create = AsyncMock(side_effect=[failing, succeeding])
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(
            session=session, new_user_message="next turn"
        ):
            pass

    assert create.call_count == 2, (
        f"expected 2 spawns (failed --resume + seeded fallback), "
        f"got {create.call_count}"
    )
    second_call_args = create.call_args_list[1][0]
    assert "--resume" not in second_call_args, (
        "second spawn must not use --resume after the first one was rejected"
    )
    # cli_session_id was cleared during inline recovery, then captured
    # fresh from the seeded-fallback spawn's session_init event
    await sync_to_async(session.refresh_from_db)()
    assert session.cli_session_id == "sess_abc123"


async def test_long_lived_double_failure_evicts_and_clears_session_id(session):
    """If both the --resume spawn AND the seeded-history fallback produce
    zero events, the SessionProcess is evicted from the pool and
    cli_session_id is cleared so the next user-initiated retry doesn't
    try --resume again.
    """
    session.cli_session_id = "sess_dead"
    await sync_to_async(session.save)()

    failing = _fake_proc(b"", returncode=1)
    failing_again = _fake_proc(b"", returncode=1)

    backend = CLIBackend()
    create = AsyncMock(side_effect=[failing, failing_again])
    with patch("asyncio.create_subprocess_exec", new=create):
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(
                session=session, new_user_message="hi"
            ):
                pass

    assert create.call_count == 2
    await sync_to_async(session.refresh_from_db)()
    assert session.cli_session_id is None, (
        "cli_session_id should have been cleared during inline recovery"
    )
    assert session.slug not in backend._sessions, (
        "SessionProcess should have been evicted after double failure"
    )


async def test_long_lived_cancel_evicts_session_process(session):
    """Consumer cancel mid-turn (GeneratorExit) evicts the entire
    SessionProcess. Phase 1B can't safely resume mid-stream, so the next
    turn pays one MCP-startup cost.
    """
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _multi_turn_fake_proc([fixture])
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        gen = backend.stream_completion(session=session, new_user_message="hi")
        async for _ in gen:
            break  # cancel after first event
        await gen.aclose()

    assert terminated == ["term"], "consumer cancel didn't terminate the subprocess"
    assert session.slug not in backend._sessions, (
        "consumer cancel didn't drop the SessionProcess from the pool"
    )


async def test_long_lived_break_after_done_does_not_evict(session):
    """REGRESSION (caught live on labs 2026-05-04): production consumers
    `return` from their async-for loop immediately after broadcasting DONE.
    That leaves our long-lived generator suspended at the post-DONE yield;
    when the outer scope closes (gc / explicit aclose), Python injects
    GeneratorExit at the suspended yield. If we treat that as a "consumer
    cancelled mid-turn" event we evict the SessionProcess after EVERY
    successful turn — defeating the entire point of Phase 1B.

    This test simulates the consumer's break-after-DONE-then-aclose
    pattern and asserts the SessionProcess is left intact, ready for the
    next turn to reuse.
    """
    init = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    follow_up = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _multi_turn_fake_proc([init, follow_up])
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend()
    create = AsyncMock(return_value=fake)
    with patch("asyncio.create_subprocess_exec", new=create):
        # Turn 1: drive the generator and break right after DONE — exactly
        # what `_run_turn_driver` does in production.
        gen1 = backend.stream_completion(session=session, new_user_message="hi")
        async for ev in gen1:
            if ev.type is StreamEventType.DONE:
                break
        await gen1.aclose()

        # SP must still be in the pool with the subprocess alive.
        assert session.slug in backend._sessions, (
            "post-DONE aclose evicted the SessionProcess — Phase 1B "
            "regression: every chat turn would force a respawn"
        )
        sp = backend._sessions[session.slug]
        assert sp.proc is not None and sp.proc.returncode is None, (
            "subprocess was terminated despite the turn completing successfully"
        )
        assert terminated == [], (
            f"terminate() was called after a clean DONE — that means the "
            f"GeneratorExit handler wrongly evicted. Calls: {terminated}"
        )

        # Turn 2: must reuse the same subprocess.
        async for _ in backend.stream_completion(
            session=session, new_user_message="follow up"
        ):
            pass

    assert create.call_count == 1, (
        f"second turn spawned a new subprocess instead of reusing — "
        f"call_count={create.call_count}. The break-after-DONE eviction "
        f"regression is back."
    )


async def test_long_lived_evicts_and_clears_session_id_on_terminal_error_event(session):
    """REGRESSION (caught live on labs 2026-05-04 cross-task --resume): when
    the CLI emits a terminal `result/error_*` event (e.g.
    error_during_execution from a stale --resume session id whose origin
    was on a different ECS task), we must:

      1. yield the ERROR event upward so the consumer can broadcast
         chat.stream_error,
      2. evict the SessionProcess (proc is dead at that point),
      3. clear ``Session.cli_session_id`` if --resume was the trigger,
         so the next turn doesn't try the same stale id again,
      4. NOT log it as "consumer cancelled mid-turn" — that misled
         debugging in the original incident.
    """
    session.cli_session_id = "sess_will_fail"
    await sync_to_async(session.save)()

    # Fixture: init event (yields SESSION_ID) + error result. Mirrors what
    # the CLI emits when --resume references a session it doesn't know.
    error_payload = (
        b'{"type":"system","subtype":"init","session_id":"sess_xyz",'
        b'"cwd":"/tmp","tools":[]}\n'
        b'{"type":"result","subtype":"error_during_execution",'
        b'"duration_ms":100}\n'
    )
    fake = _fake_proc(error_payload, returncode=1)
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend()
    create = AsyncMock(return_value=fake)
    with patch("asyncio.create_subprocess_exec", new=create):
        events: list[StreamEventType] = []
        # Consumer broadcasts chat.stream_error and `return`s after seeing
        # ERROR — simulate that with break + aclose (matches production).
        gen = backend.stream_completion(session=session, new_user_message="hi")
        async for ev in gen:
            events.append(ev.type)
            if ev.type is StreamEventType.ERROR:
                break
        await gen.aclose()

    assert StreamEventType.ERROR in events, (
        "ERROR event was not yielded — consumer would never broadcast "
        "chat.stream_error"
    )
    assert session.slug not in backend._sessions, (
        "SessionProcess was not evicted after terminal error event — the "
        "next turn would try to reuse a dead subprocess"
    )
    await sync_to_async(session.refresh_from_db)()
    assert session.cli_session_id is None, (
        "cli_session_id was not cleared after --resume failed with a "
        "terminal error — the next turn would try the same stale id again"
    )
    assert terminated == ["term"], (
        f"subprocess was not terminated. terminate() calls: {terminated}"
    )


def test_session_process_initial_state():
    """SessionProcess starts with no proc, no staged home, no credential
    source — those are all populated by ``_spawn_session_process`` and
    cleaned up by ``_evict_locked``.
    """
    sp = SessionProcess(slug="abc123", session_pk=42)
    assert sp.slug == "abc123"
    assert sp.session_pk == 42
    assert sp.proc is None
    assert sp.staged_home is None
    assert sp.credential_source is None
    assert sp.cli_session_id is None
    assert sp.spawned_with_resume is False
    assert sp.is_alive() is False


async def test_evictable_slugs_skips_session_with_turn_in_progress():
    """The idle reaper must never select a session whose lock is held (a turn
    is in progress) — even when last_active is stale. Long ACE runs are one
    multi-hour turn that never refreshes last_active mid-stream; evicting one
    rmtree's the staged HOME under the live claude -p and kills the run
    (bednet-spot-check runs cancelled ~30-60min in). Regression guard.
    """
    import time as _time

    from apps.common.cli_backend import SessionProcess

    backend = CLIBackend(session_idle_timeout_seconds=1.0)
    stale = _time.monotonic() - 100.0  # well past the 1s timeout

    sp_idle = SessionProcess("idle-slug", 1)
    sp_idle.last_active = stale
    sp_busy = SessionProcess("busy-slug", 2)
    sp_busy.last_active = stale
    backend._sessions["idle-slug"] = sp_idle
    backend._sessions["busy-slug"] = sp_busy

    await sp_busy.lock.acquire()  # simulate an in-flight turn holding the lock
    try:
        slugs = backend._evictable_slugs(_time.monotonic())
    finally:
        sp_busy.lock.release()

    assert "idle-slug" in slugs, "genuinely-idle session should still be reaped"
    assert "busy-slug" not in slugs, "reaper selected a session with a turn in progress"

    # With the lock released, the (still-stale) session becomes evictable.
    assert "busy-slug" in backend._evictable_slugs(_time.monotonic())


async def test_lru_evict_candidate_skips_session_with_turn_in_progress():
    """At pool cap, LRU eviction must not pick a session with a turn in
    progress (lock held) even if it has the oldest last_active — same kill
    class as the idle reaper. If every other session is mid-turn, returns None
    (pool briefly exceeds cap instead of killing a live run).
    """
    import time as _time

    from apps.common.cli_backend import SessionProcess

    backend = CLIBackend()
    sp_old_busy = SessionProcess("old-busy", 1)
    sp_old_busy.last_active = _time.monotonic() - 200.0  # oldest → normal LRU pick
    sp_newer_idle = SessionProcess("newer-idle", 2)
    sp_newer_idle.last_active = _time.monotonic() - 10.0
    backend._sessions["old-busy"] = sp_old_busy
    backend._sessions["newer-idle"] = sp_newer_idle

    await sp_old_busy.lock.acquire()  # the oldest session is mid-turn
    try:
        # Admitting "incoming": must skip the locked oldest, pick the idle one.
        assert backend._lru_evict_candidate("incoming") == "newer-idle"
        # If the only other candidate is also locked → None (don't evict).
        await sp_newer_idle.lock.acquire()
        try:
            assert backend._lru_evict_candidate("incoming") is None
        finally:
            sp_newer_idle.lock.release()
    finally:
        sp_old_busy.lock.release()

    # Nothing locked → normal LRU picks the oldest.
    assert backend._lru_evict_candidate("incoming") == "old-busy"
