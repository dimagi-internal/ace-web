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
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from asgiref.sync import sync_to_async

from apps.sessions.models import Message, Session

from .auth_flow import get_stored_token
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

        # Stage the session owner's credential blob into a fresh per-invocation
        # HOME so two concurrent chats from different users can't clobber each
        # other's ~/.claude/.credentials.json. Torn down in the outer finally.
        staged_env, staged_home = await sync_to_async(self._stage_env_for)(session)
        try:
            # ── attempt 1: resume if we have a CLI session id AND resume is allowed ──
            if session.cli_session_id and not force_fresh_session:
                proc = await self._spawn(
                    args=["--resume", session.cli_session_id],
                    prompt=new_user_message,
                    env=staged_env,
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

                if had_events:
                    if proc.returncode != 0:
                        logger.warning(
                            "claude CLI --resume exited %s but produced events"
                            " — treating as success",
                            proc.returncode,
                        )
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
            proc = await self._spawn(args=[], prompt=history_prompt, env=staged_env)
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

            if not had_events:
                stderr_text = ""
                if proc.stderr:
                    try:
                        stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=2)
                        stderr_text = stderr_bytes.decode("utf-8", errors="replace")[:2000]
                    except Exception:
                        pass
                if stderr_text:
                    logger.error("claude CLI stderr: %s", stderr_text)
                self._breaker.record_failure()
                raise CLIBackendError(
                    f"claude CLI failed (rc={proc.returncode}, events={had_events})"
                    + (f" stderr: {stderr_text[:500]}" if stderr_text else "")
                )
            if proc.returncode != 0:
                logger.warning(
                    "claude CLI exited %s but produced events — treating as success",
                    proc.returncode,
                )
            self._breaker.record_success()
        finally:
            self._teardown_staged_home(staged_home)

    # ────────────────────────────── helpers ──────────────────────────────

    async def _spawn(self, *, args: list[str], prompt: str, env: dict[str, str]):
        """Spawn the CLI subprocess, write the prompt to stdin, close it.

        Raises CLIBackendError if the subprocess dies before accepting the prompt
        (e.g., binary missing, permission denied, instant crash).
        """
        full_args = [self._binary, "-p", "--verbose", "--output-format", "stream-json", *args]
        # stderr=DEVNULL avoids a deadlock where a chatty CLI fills the stderr pipe
        # buffer (~64KB) and blocks before we can drain it. A future task should
        # capture stderr in a concurrent background task so error logs are available
        # without risking the deadlock.
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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

    def _stage_env_for(self, session: Session) -> tuple[dict[str, str], str]:
        """Resolve the owner's credential blob and stage it in a fresh temp HOME.

        Returns ``(env_dict, staged_home_path)``. Caller MUST call
        ``_teardown_staged_home(home)`` in a finally block to remove the
        directory — per-invocation UUIDs keep concurrent chats isolated.
        """
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        resolved = get_stored_token(user=session.owner)
        token = resolved[0] if resolved else ""
        blob_json = self._load_blob_for_token(session.owner, resolved)

        staged_root = (
            Path(tempfile.gettempdir())
            / "ace-cli"
            / f"{session.slug}-{uuid.uuid4().hex[:8]}"
        )
        claude_dir = staged_root / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        if blob_json:
            creds_path = claude_dir / ".credentials.json"
            creds_path.write_text(blob_json)
            try:
                creds_path.chmod(0o600)
            except OSError:
                pass

        env["HOME"] = str(staged_root)
        # Unconditionally drop any inherited CLAUDE_CODE_OAUTH_TOKEN so the only path
        # that sets it is our own resolved token. Defends against a race where another
        # concurrent _stage_env_for call mutated os.environ via load_stored_token's
        # side-effect write before we built our env snapshot.
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        return env, str(staged_root)

    def _load_blob_for_token(self, owner, resolved) -> str:
        """Pick the full blob JSON matching the resolver's source."""
        if resolved is None:
            return ""
        _, source = resolved
        if source == "user":
            from .models import UserCredential

            cred = UserCredential.objects.filter(user=owner).first()
            return cred.blob_encrypted if cred else ""
        if source == "global":
            from .models import SystemConfig

            row = SystemConfig.objects.filter(key="claude_credentials_blob").first()
            return row.value if row else ""
        # env-only source: reconstruct the minimal blob shape so the CLI's
        # credentials file has the structure it expects.
        return json.dumps({"claudeAiOauth": {"accessToken": resolved[0]}})

    def _teardown_staged_home(self, staged_home: str) -> None:
        try:
            shutil.rmtree(staged_home, ignore_errors=True)
        except Exception:
            logger.warning("Failed to clean staged CLI home %s", staged_home)

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
