"""CLIBackend — wraps `claude -p --output-format stream-json` as a subprocess.

Hybrid resume strategy:
  1. If session.cli_session_id is set, try `--resume <id>` with only the new
     user message as the prompt.
  2. If that subprocess exits non-zero with no events, restart without --resume
     and seed the prompt with the full conversation history from Django.
  3. Capture the fresh session_id from the first SESSION_ID event of the new
     CLI session and persist it on session.cli_session_id.

The single subprocess is killed on consumer cancellation (the async iterator
is abandoned), via SIGTERM then SIGKILL after a 2-second grace.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

from asgiref.sync import sync_to_async
from django.conf import settings

from apps.sessions.models import Message, Session

from .chat_backend import StreamEvent, StreamEventType
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .cli_event_parser import parse_stream_json_lines

logger = logging.getLogger(__name__)


class CLIBackendError(RuntimeError):
    """Raised when the CLI subprocess fails in a way the consumer should know about."""


class CLIBackend:
    """Async chat backend that wraps the Claude CLI."""

    def __init__(
        self,
        *,
        binary: str = "claude",
        circuit_threshold: int = 5,
        circuit_cooldown: float = 30.0,
        terminate_grace_seconds: float = 2.0,
    ):
        self._binary = binary
        self._breaker = CircuitBreaker(
            threshold=circuit_threshold, cooldown_seconds=circuit_cooldown
        )
        self._terminate_grace = terminate_grace_seconds

    def stream_completion(
        self,
        *,
        session: Session,
        new_user_message: str,
    ) -> AsyncIterator[StreamEvent]:
        """Return an async iterator of StreamEvents for one assistant turn.

        The iterator performs all I/O lazily (on the first __anext__ call).
        If the consumer abandons the iterator (break / early exit), the
        subprocess is terminated synchronously via __del__ — which in CPython
        fires immediately when the anonymous temporary's refcount drops to zero.
        """
        return _CompletionIter(
            backend=self,
            session=session,
            new_user_message=new_user_message,
        )

    # ────────────────────────────── helpers ──────────────────────────────

    async def _spawn(self, *, args: list[str], prompt: str):
        """Spawn the CLI subprocess, write the prompt to stdin, close it."""
        full_args = [self._binary, "-p", "--output-format", "stream-json", *args]
        env = self._build_env()
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        return proc

    def _build_env(self) -> dict[str, str]:
        # Strip ANTHROPIC_API_KEY so the CLI uses subscription auth via the
        # OAuth token loaded into CLAUDE_CODE_OAUTH_TOKEN by token_loader.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        claude_home = getattr(settings, "ACE_CLAUDE_HOME", None)
        if claude_home:
            env["HOME"] = claude_home
        return env

    async def _build_seeded_prompt(self, session: Session, new_user_message: str) -> str:
        @sync_to_async
        def _load_history():
            return list(
                Message.objects.filter(session=session)
                .order_by("turn_index")
                .values("role", "plaintext")
            )

        history = await _load_history()
        lines = []
        for row in history:
            role = row["role"].capitalize()
            lines.append(f"{role}: {row['plaintext']}")
        lines.append(f"User: {new_user_message}")
        return "\n\n".join(lines)


class _CompletionIter:
    """Async iterator returned by CLIBackend.stream_completion.

    All I/O is deferred to __anext__. If the consumer abandons the iterator
    (break / early exit), __del__ terminates the subprocess synchronously.

    Design note: the inner generator (_run) is a module-level function that
    receives a mutable ``_proc_ref`` list instead of holding a reference to
    ``self``.  This breaks the reference cycle that would otherwise prevent
    CPython's refcount GC from collecting the iterator immediately on abandon.
    """

    def __init__(self, *, backend: CLIBackend, session: Session, new_user_message: str):
        self._backend = backend
        self._session = session
        self._new_user_message = new_user_message
        # Shared mutable slot for the active subprocess.  The inner generator
        # writes to it so __del__ can terminate the process without holding a
        # direct reference back to this object (which would create a cycle).
        self._proc_ref: list = []  # 0 or 1 elements; empty when proc is done
        self._inner = None
        self._done = False

    # ── async iterator protocol ──

    def __aiter__(self) -> _CompletionIter:
        return self

    async def __anext__(self) -> StreamEvent:
        if self._inner is None:
            self._inner = _run(
                backend=self._backend,
                session=self._session,
                new_user_message=self._new_user_message,
                proc_ref=self._proc_ref,
            )
        try:
            return await self._inner.__anext__()
        except StopAsyncIteration:
            self._done = True
            raise

    # ── synchronous cleanup on GC ──

    def __del__(self) -> None:
        """Terminate the active subprocess synchronously if abandoned."""
        if not self._done and self._proc_ref:
            proc = self._proc_ref[0]
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                pass


async def _run(
    *,
    backend: CLIBackend,
    session: Session,
    new_user_message: str,
    proc_ref: list,
) -> AsyncIterator[StreamEvent]:
    """Module-level async generator that drives one chat turn.

    Uses ``proc_ref`` (a shared mutable list) instead of a reference to the
    owning _CompletionIter, so there is no reference cycle between the iterator
    and its inner generator.
    """
    try:
        backend._breaker.check()
    except CircuitOpenError as exc:
        raise CLIBackendError(str(exc)) from exc

    # ── attempt 1: resume ──
    if session.cli_session_id:
        proc = await backend._spawn(
            args=["--resume", session.cli_session_id], prompt=new_user_message
        )
        proc_ref.append(proc)

        had_events = False
        buffered: list[StreamEvent] = []
        async for event in _drain(proc):
            had_events = True
            buffered.append(event)
            if event.type is StreamEventType.SESSION_ID and event.session_id:
                await _persist_session_id(session, event.session_id)

        await proc.wait()
        proc_ref.clear()

        if had_events and proc.returncode == 0:
            backend._breaker.record_success()
            for event in buffered:
                yield event
            return

        logger.warning(
            "CLI --resume %s failed (rc=%s, events=%s) — falling back to seeded history",
            session.cli_session_id,
            proc.returncode,
            had_events,
        )
        # fallthrough to seeded-history path

    # ── attempt 2: fresh session with seeded history ──
    history_prompt = await backend._build_seeded_prompt(session, new_user_message)
    proc = await backend._spawn(args=[], prompt=history_prompt)
    proc_ref.append(proc)

    had_events = False
    async for event in _drain(proc):
        had_events = True
        if event.type is StreamEventType.SESSION_ID and event.session_id:
            await _persist_session_id(session, event.session_id)
        yield event

    await proc.wait()
    proc_ref.clear()  # process is done; suppress __del__ terminate

    if proc.returncode != 0 or not had_events:
        backend._breaker.record_failure()
        raise CLIBackendError(
            f"claude CLI failed (rc={proc.returncode}, events={had_events})"
        )
    backend._breaker.record_success()


async def _drain(proc) -> AsyncIterator[StreamEvent]:
    """Read stdout line by line and yield parsed StreamEvents."""
    while True:
        try:
            line = await proc.stdout.readline()
        except RuntimeError:
            # StopIteration escaped a coroutine (PEP 479) — treat as EOF.
            break
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        for event in parse_stream_json_lines([text]):
            yield event


async def _persist_session_id(session: Session, cli_session_id: str) -> None:
    @sync_to_async
    def _save():
        Session.objects.filter(pk=session.pk).update(cli_session_id=cli_session_id)
        session.cli_session_id = cli_session_id

    await _save()
