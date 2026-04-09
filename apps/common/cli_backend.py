"""CLIBackend — wraps `claude -p --output-format stream-json` as a subprocess.

Hybrid resume strategy:
  1. If session.cli_session_id is set, try `--resume <id>` with only the new
     user message as the prompt. Yield events as they arrive.
  2. After the resume subprocess exits, if it produced no events OR exited
     non-zero, restart without --resume and seed the prompt with the full
     conversation history from Django. Yield those events as they arrive.
  3. Capture the fresh session_id from the first SESSION_ID event of the new
     CLI session and persist it on session.cli_session_id.

Cleanup: the async generator's `finally` block terminates the subprocess via
SIGTERM → SIGKILL after a 2-second grace. This fires automatically when the
consumer breaks out of the `async for` (Python calls `aclose()`).
"""
from __future__ import annotations

import asyncio
import contextlib
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

    async def stream_completion(
        self,
        *,
        session: Session,
        new_user_message: str,
        force_fresh_session: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one assistant turn.

        Yields events as they arrive. On consumer cancellation (break out of
        the async for), Python calls aclose() which triggers the finally
        blocks below, terminating the subprocess cleanly.

        When force_fresh_session=True, the resume path is skipped entirely and
        the returned CLI session id is NOT persisted on Session.cli_session_id.
        This is used by the auto-titler to avoid polluting conversation history.
        """
        try:
            self._breaker.check()
        except CircuitOpenError as exc:
            raise CLIBackendError(str(exc)) from exc

        # ── attempt 1: resume if we have a CLI session id AND resume is allowed ──
        if session.cli_session_id and not force_fresh_session:
            proc = await self._spawn(
                args=["--resume", session.cli_session_id],
                prompt=new_user_message,
            )
            had_events = False
            try:
                async for event in self._drain(proc):
                    had_events = True
                    yield event
                    if event.type is StreamEventType.SESSION_ID and event.session_id:
                        await self._persist_session_id(session, event.session_id)
                await proc.wait()
            finally:
                await self._cleanup(proc)

            if had_events and proc.returncode == 0:
                self._breaker.record_success()
                return

            logger.warning(
                "CLI --resume %s failed (rc=%s, events=%s) — falling back to seeded history",
                session.cli_session_id,
                proc.returncode,
                had_events,
            )
            # fallthrough to seeded-history path

        # ── attempt 2: fresh session with seeded history ──
        history_prompt = await self._build_seeded_prompt(session, new_user_message)
        proc = await self._spawn(args=[], prompt=history_prompt)
        had_events = False
        try:
            async for event in self._drain(proc):
                had_events = True
                yield event
                if (
                    event.type is StreamEventType.SESSION_ID
                    and event.session_id
                    and not force_fresh_session
                ):
                    await self._persist_session_id(session, event.session_id)
            await proc.wait()
        finally:
            await self._cleanup(proc)

        if proc.returncode != 0 or not had_events:
            self._breaker.record_failure()
            raise CLIBackendError(
                f"claude CLI failed (rc={proc.returncode}, events={had_events})"
            )
        self._breaker.record_success()

    # ────────────────────────────── helpers ──────────────────────────────

    async def _spawn(self, *, args: list[str], prompt: str):
        """Spawn the CLI subprocess, write the prompt to stdin, close it.

        Raises CLIBackendError if the subprocess dies before accepting the prompt
        (e.g., binary missing, permission denied, instant crash).
        """
        full_args = [self._binary, "-p", "--output-format", "stream-json", *args]
        env = self._build_env()
        # stderr=DEVNULL avoids a deadlock where a chatty CLI fills the stderr pipe
        # buffer (~64KB) and blocks before we can drain it. A future task should
        # capture stderr in a concurrent background task so error logs are available
        # without risking the deadlock.
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        except (ConnectionResetError, BrokenPipeError) as exc:
            await self._cleanup(proc)
            self._breaker.record_failure()
            raise CLIBackendError(
                f"claude CLI stdin closed before prompt delivered: {exc}"
            ) from exc
        return proc

    def _build_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        claude_home = getattr(settings, "ACE_CLAUDE_HOME", None)
        if claude_home:
            env["HOME"] = claude_home
        return env

    async def _drain(self, proc) -> AsyncIterator[StreamEvent]:
        """Read stdout line by line and yield parsed StreamEvents."""
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            for event in parse_stream_json_lines([text]):
                yield event

    async def _build_seeded_prompt(self, session: Session, new_user_message: str) -> str:
        """Format the full message history as a fallback prompt.

        WARNING: this is a lossy, injection-prone representation used only when
        CLI --resume fails and we need to re-seed a fresh CLI session from
        Django's durable history. It drops tool_use / tool_result blocks and
        escapes any user text that looks like a turn boundary. Not a
        substitute for native conversation replay.
        """
        @sync_to_async
        def _load_history():
            return list(
                Message.objects.filter(session=session, role__in=("user", "assistant"))
                .order_by("turn_index")
                .values("role", "plaintext")
            )

        history = await _load_history()
        lines = []
        for row in history:
            role_label = "User" if row["role"] == "user" else "Assistant"
            safe_text = _escape_turn_boundaries(row["plaintext"] or "")
            lines.append(f"{role_label}: {safe_text}")
        lines.append(f"User: {new_user_message}")
        return "\n\n".join(lines)

    async def _persist_session_id(self, session: Session, cli_session_id: str) -> None:
        @sync_to_async
        def _save():
            Session.objects.filter(pk=session.pk).update(cli_session_id=cli_session_id)
            session.cli_session_id = cli_session_id

        await _save()

    async def _cleanup(self, proc) -> None:
        """Terminate the subprocess if it's still running.

        Runs the SIGTERM → SIGKILL escalation under asyncio.shield so that a
        client-disconnect-triggered cancellation of the enclosing view cannot
        interrupt the cleanup mid-flight and leak the subprocess.
        """
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return

        try:
            await asyncio.shield(
                asyncio.wait_for(proc.wait(), timeout=self._terminate_grace)
            )
        except (TimeoutError, asyncio.CancelledError):
            try:
                proc.kill()
            except ProcessLookupError:
                return
            with contextlib.suppress(asyncio.CancelledError, ProcessLookupError):
                await asyncio.shield(proc.wait())


def _escape_turn_boundaries(text: str) -> str:
    """Prevent user text from forging `User:` / `Assistant:` turn markers.

    Any line in the user's plaintext that begins with one of those tokens
    gets a zero-width space prefix so the CLI won't parse it as a turn.
    """
    lines = text.splitlines()
    escaped = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("User:", "Assistant:")):
            escaped.append("\u200b" + line)
        else:
            escaped.append(line)
    return "\n".join(escaped)
