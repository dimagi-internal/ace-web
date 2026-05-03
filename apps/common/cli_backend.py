"""CLIBackend — wraps `claude -p --input-format stream-json --output-format stream-json` as a subprocess.

Wire format
-----------
We use stream-json on BOTH stdin and stdout. The user message goes in as one
``{"type":"user","message":{"role":"user","content":"<text>"}}`` JSON line.
The CLI streams response events back on stdout in the same envelope shape.

Why stream-json input (vs. plain ``-p`` text):
  * Canonical multi-turn protocol — claude treats stdin as a stream of user
    messages, not a single one-shot prompt. Future work (long-lived per-session
    process) drops in cleanly without touching the wire format again.
  * No prompt-text injection edge cases — the message body is JSON-quoted, so
    user input that looks like a turn boundary or a control sequence can't
    confuse the CLI.
  * Better auth ergonomics — the CLI never tries to interpret stdin as a shell
    pipe.

Stdin lifecycle (load-bearing)
------------------------------
With ``--input-format stream-json``, the CLI keeps reading stdin until EOF and
will hang if you write a message and never close stdin. BUT — verified live
on 2.1.126 — if stdin EOFs *too early* (before the CLI has fully booted MCPs
+ hooks and read the buffered message), the CLI bails after running just the
SessionStart hooks and produces no result event. We work around this by:

  1. ``_spawn`` writes the JSON user message and **does NOT close stdin**.
  2. ``_drain`` yields events as they arrive. Once it sees the ``result``
     event (StreamEventType.DONE), it closes stdin to signal "no more
     messages." The CLI then exits cleanly.

If the consumer breaks out of the ``async for`` before DONE arrives, the
``finally`` block in ``stream_completion`` calls ``_cleanup(proc)`` which
SIGTERMs the subprocess and stdin closes implicitly.

Hybrid resume strategy
----------------------
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
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path

from asgiref.sync import sync_to_async

from apps.sessions.models import Message, Session

from .auth_flow import get_stored_token
from .chat_backend import StreamEvent, StreamEventType
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .cli_event_parser import parse_stream_json_lines
from .nova_auth_flow import get_fresh_token as get_fresh_nova_token

# Env-var name read by the bundled Nova plugin's .mcp.json (Dockerfile
# rewrites the plugin's headers to ``Bearer ${NOVA_BEARER_TOKEN:-}``).
# Empty string when Nova isn't connected — Claude Code expands the
# default and the MCP server returns 401 at call time, recoverable.
NOVA_BEARER_TOKEN_ENV = "NOVA_BEARER_TOKEN"

logger = logging.getLogger(__name__)

# How many lines of stderr we keep in memory per subprocess. The kernel's
# stderr pipe buffer is ~64 KB; a long-running run can emit far more than
# that (MCP warnings, retries). We log every line at WARNING and keep the
# tail for inclusion in error reports.
STDERR_TAIL_LINES = 400

# Heartbeat cadence for "subprocess still alive" log lines. Anything coarser
# than the ALB idle timeout makes long quiet stretches (e.g. waiting on an
# MCP) hard to distinguish from "frozen" in CloudWatch.
HEARTBEAT_INTERVAL_SECONDS = 30.0

# asyncio.StreamReader's default readline limit is 2**16 (64 KB). A single
# stream-json line from claude can easily blow past that — tool_result blocks
# carry full file contents, large text deltas, etc. Hitting the limit raises
# ValueError("Separator is found, but chunk is longer than limit") and kills
# the whole turn. Set the buffer to 50 MiB which is generous enough for any
# realistic tool output but still bounded so a runaway can't OOM the worker.
STREAM_READER_LIMIT_BYTES = 50 * 1024 * 1024


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
        # ``source`` tells us where the blob came from so we can persist any
        # CLI-refreshed version back to the same storage before teardown.
        staged_env, staged_home, source = await sync_to_async(self._stage_env_for)(
            session
        )
        try:
            # ── attempt 1: resume if we have a CLI session id AND resume is allowed ──
            if session.cli_session_id and not force_fresh_session:
                proc = await self._spawn(
                    args=["--resume", session.cli_session_id],
                    prompt=new_user_message,
                    env=staged_env,
                    session_slug=session.slug,
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
            proc = await self._spawn(
                args=[],
                prompt=history_prompt,
                env=staged_env,
                session_slug=session.slug,
            )
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
                stderr_text = _proc_stderr_tail(proc, char_limit=2000)
                if stderr_text:
                    logger.error("claude CLI stderr tail: %s", stderr_text)
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
            # Persist any CLI-refreshed blob BEFORE teardown. The claude CLI
            # refreshes OAuth tokens in-place by overwriting the staged
            # credentials file; if we rmtree first we throw the refresh away
            # and the next chat tries to refresh using an already-burned
            # refresh token. Wrapped in try/except because cleanup must
            # never raise.
            try:
                await sync_to_async(self._persist_refreshed_blob)(
                    session, source, staged_home
                )
            except Exception:
                logger.warning(
                    "Failed to persist refreshed blob for session=%s",
                    session.slug,
                    exc_info=True,
                )
            self._teardown_staged_home(staged_home)

    # ────────────────────────────── helpers ──────────────────────────────

    async def _spawn(
        self, *, args: list[str], prompt: str, env: dict[str, str], session_slug: str = ""
    ):
        """Spawn the CLI subprocess, write the prompt to stdin, close it.

        Also starts two concurrent background tasks attached to ``proc``:
          * ``_ace_stderr_task`` — drains stderr line-by-line into
            ``_ace_stderr_buf`` (bounded deque) and logs every line at
            WARNING. Without this, a chatty CLI fills the kernel's stderr
            pipe buffer (~64 KB) and the subprocess blocks on its next
            stderr write — fatal for 30-min runs.
          * ``_ace_heartbeat_task`` — logs "subprocess alive" every
            ``HEARTBEAT_INTERVAL_SECONDS`` so quiet stretches (waiting on
            an MCP, slow Anthropic response) are distinguishable from
            "frozen" in CloudWatch.

        Raises CLIBackendError if the subprocess dies before accepting the prompt
        (e.g., binary missing, permission denied, instant crash).
        """
        # --dangerously-skip-permissions lets the assistant actually use Bash,
        # Read, Edit, Write, MCP tools, etc. without per-call permission
        # prompts. Required for non-interactive server use — there's no UI
        # to approve prompts in real time. The blast radius is bounded by the
        # staged per-session HOME (rm-tree'd in the finally block) and by the
        # MCP credentials we explicitly grant (Drive SA key, Connect/OCS
        # session cookies). Without this flag, claude -p answers as a plain
        # chatbot and the entire ACE plugin is unreachable.
        full_args = [
            self._binary, "-p", "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
            *args,
        ]
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=STREAM_READER_LIMIT_BYTES,
        )

        proc._ace_stderr_buf = deque(maxlen=STDERR_TAIL_LINES)
        proc._ace_started_at = time.monotonic()
        proc._ace_session_slug = session_slug
        proc._ace_stderr_task = asyncio.create_task(
            _drain_stderr_into(proc, proc._ace_stderr_buf, session_slug),
            name=f"cli-stderr-{session_slug or id(proc)}",
        )
        proc._ace_heartbeat_task = asyncio.create_task(
            _heartbeat(proc, session_slug),
            name=f"cli-heartbeat-{session_slug or id(proc)}",
        )

        # Stream-json input: one JSON line per user message. We do NOT close
        # stdin here — see module docstring "Stdin lifecycle". _drain closes
        # stdin after observing the result/DONE event so the CLI exits cleanly.
        envelope = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }).encode("utf-8") + b"\n"
        try:
            proc.stdin.write(envelope)
            await proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError) as exc:
            await self._cleanup(proc)
            self._breaker.record_failure()
            raise CLIBackendError(
                f"claude CLI stdin closed before prompt delivered: {exc}"
            ) from exc
        return proc

    def _stage_env_for(
        self, session: Session
    ) -> tuple[dict[str, str], str, str | None]:
        """Resolve the owner's credential blob and stage it in a fresh temp HOME.

        Returns ``(env_dict, staged_home_path, source)`` where ``source`` is
        one of ``"user"``, ``"global"``, ``"env"`` or ``None`` (no token
        resolved). Caller MUST call ``_teardown_staged_home(home)`` in a
        finally block to remove the directory. ``source`` is used by
        ``_persist_refreshed_blob`` to write any CLI-refreshed Claude blob
        back to the right storage layer before teardown.

        Also injects ``NOVA_BEARER_TOKEN`` into the spawn env from the
        stored Nova OAuth blob (refreshing if near expiry). Empty when
        Nova isn't connected; the bundled plugin's ``.mcp.json`` uses
        ``${NOVA_BEARER_TOKEN:-}`` so the empty value just becomes
        ``Bearer `` and the MCP server returns 401 at call time.
        """
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        resolved = get_stored_token(user=session.owner)
        token = resolved[0] if resolved else ""
        source = resolved[1] if resolved else None
        blob_json = self._load_blob_for_token(session.owner, resolved)

        staged_root = (
            Path(tempfile.gettempdir())
            / "ace-cli"
            / f"{session.slug}-{uuid.uuid4().hex[:8]}"
        )
        claude_dir = staged_root / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        # Symlink everything from the real ~/.claude/ EXCEPT .credentials.json
        # into the staged HOME. We need plugins/, settings.json, plugin-data/,
        # etc. visible to the subprocess so slash commands and MCP servers
        # work; we own the credentials file so concurrent sessions can't
        # clobber each other's OAuth refreshes (see _persist_refreshed_blob).
        original_home = os.environ.get("HOME") or ""
        symlinked_names: list[str] = []
        if original_home:
            real_claude_dir = Path(original_home) / ".claude"
            if real_claude_dir.is_dir():
                for entry in real_claude_dir.iterdir():
                    # Skip credentials — we manage that file ourselves.
                    if entry.name == ".credentials.json":
                        continue
                    link = claude_dir / entry.name
                    if link.exists() or link.is_symlink():
                        continue
                    try:
                        link.symlink_to(entry)
                        symlinked_names.append(entry.name)
                    except OSError:
                        # Best-effort — a missing plugin is recoverable but
                        # shouldn't bring the whole turn down.
                        logger.warning(
                            "Could not symlink %s → %s", entry, link, exc_info=True
                        )
            else:
                logger.warning(
                    "stage_env_for: HOME=%r has no ~/.claude/ — claude subprocess "
                    "will run with no plugins / slash commands / MCP servers",
                    original_home,
                )
        else:
            logger.warning(
                "stage_env_for: $HOME is unset — claude subprocess will run with "
                "no plugins / slash commands / MCP servers"
            )
        logger.info(
            "stage_env_for: session=%s staged=%s real_home=%r symlinked=%s",
            session.slug, staged_root, original_home, symlinked_names,
        )

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

        env[NOVA_BEARER_TOKEN_ENV] = self._resolve_nova_bearer()
        return env, str(staged_root), source

    def _resolve_nova_bearer(self) -> str:
        """Mint a fresh Nova access token for ``${NOVA_BEARER_TOKEN}`` expansion.

        ``get_fresh_token`` transparently refreshes if the stored token is
        within the 5-min refresh buffer and persists the rotated blob back
        to ``SystemConfig``. We swallow any exception and return ``""``
        because a Nova outage must NOT take chat down — the worst case is
        Nova MCP calls fail with 401 inside the chat, which is recoverable.
        """
        try:
            return get_fresh_nova_token() or ""
        except Exception:
            logger.warning("nova: get_fresh_nova_token raised", exc_info=True)
            return ""

    def _persist_refreshed_blob(
        self, session: Session, source: str | None, staged_home: str
    ) -> None:
        """Write the (possibly-refreshed) staged credentials file back to the source.

        The claude CLI refreshes OAuth tokens in-place by overwriting
        ``$HOME/.claude/.credentials.json``. If we rmtree the staged HOME
        without reading it back first, we lose the refresh — and since
        Anthropic's refresh tokens are often single-use, the next chat
        attempts a refresh with an already-burned refresh token and fails
        with a 401. This method re-reads the file and writes the new blob
        back to whichever storage layer the resolver picked.

        Idempotent and defensive: if the file is missing, malformed, or the
        access token is obviously junk, this is a no-op. ``source="env"``
        is a dev/test fallback — no DB row exists to write back to.
        """
        if source is None or not staged_home:
            return
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        if not creds_path.exists():
            return
        try:
            current_text = creds_path.read_text()
            blob = json.loads(current_text)
        except (OSError, ValueError):
            logger.warning(
                "Could not re-read staged credentials at %s for persist", creds_path
            )
            return

        access_token = (blob.get("claudeAiOauth") or {}).get("accessToken") or ""
        if not access_token.startswith("sk-ant-oat"):
            return  # don't persist obviously-malformed state

        if source == "user":
            from .models import UserCredential

            UserCredential.objects.filter(user=session.owner).update(
                blob_encrypted=current_text,
                token_prefix=access_token[:15],
            )
            logger.info(
                "CLIBackend: persisted refreshed user blob for user=%s prefix=%s",
                session.owner.pk, access_token[:15],
            )
        elif source == "global":
            from .models import SystemConfig

            SystemConfig.objects.update_or_create(
                key="claude_credentials_blob",
                defaults={"value": current_text},
            )
            logger.info(
                "CLIBackend: persisted refreshed global blob prefix=%s",
                access_token[:15],
            )
        # source="env" is a dev/test fallback — don't persist back to anywhere

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
        """Read stdout line by line and yield parsed StreamEvents.

        Closes ``proc.stdin`` once a DONE event is observed. With
        ``--input-format stream-json``, the CLI keeps reading stdin until EOF,
        so we MUST close stdin once the turn is complete or the process hangs
        forever waiting for the next user message. See the module docstring
        "Stdin lifecycle" section for the full rationale.
        """
        stdin_closed = False
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            for event in parse_stream_json_lines([text]):
                yield event
                if (
                    not stdin_closed
                    and event.type is StreamEventType.DONE
                    and proc.stdin is not None
                    and not proc.stdin.is_closing()
                ):
                    with contextlib.suppress(Exception):
                        proc.stdin.close()
                    stdin_closed = True

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
        """Terminate the subprocess if it's still running, then cancel its
        stderr-drain and heartbeat tasks.

        Runs the SIGTERM → SIGKILL escalation under asyncio.shield so that a
        client-disconnect-triggered cancellation of the enclosing view cannot
        interrupt the cleanup mid-flight and leak the subprocess.
        """
        try:
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                else:
                    try:
                        await asyncio.shield(
                            asyncio.wait_for(proc.wait(), timeout=self._terminate_grace)
                        )
                    except (TimeoutError, asyncio.CancelledError):
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                        else:
                            with contextlib.suppress(
                                asyncio.CancelledError, ProcessLookupError
                            ):
                                await asyncio.shield(proc.wait())
        finally:
            for attr in ("_ace_stderr_task", "_ace_heartbeat_task"):
                task = getattr(proc, attr, None)
                if task is None or task.done():
                    continue
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.shield(asyncio.wait_for(task, timeout=1.0))


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


async def _drain_stderr_into(proc, buf: deque[str], session_slug: str) -> None:
    """Read subprocess stderr line-by-line, log it, keep the tail in ``buf``.

    Runs as a background task started by ``CLIBackend._spawn``. Cancellation
    is handled by ``CLIBackend._cleanup``. Naturally exits on stderr EOF
    (subprocess died or closed stderr).
    """
    if proc.stderr is None:
        return
    try:
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            if not text:
                continue
            buf.append(text)
            logger.warning("claude-cli[%s] stderr: %s", session_slug or "?", text)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("stderr drain failed for session=%s", session_slug or "?")


async def _heartbeat(proc, session_slug: str) -> None:
    """Log a 'subprocess alive' line every ``HEARTBEAT_INTERVAL_SECONDS``.

    Lets CloudWatch tail-watchers distinguish "still working" from "frozen"
    during quiet stretches (waiting on an MCP, slow Anthropic response).
    Naturally exits when the subprocess exits (via cancellation in cleanup).
    """
    started = getattr(proc, "_ace_started_at", time.monotonic())
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if proc.returncode is not None:
                return
            elapsed = time.monotonic() - started
            stderr_lines = len(getattr(proc, "_ace_stderr_buf", ()) or ())
            logger.info(
                "claude-cli[%s] heartbeat: pid=%s elapsed=%.0fs stderr_lines=%d",
                session_slug or "?",
                proc.pid,
                elapsed,
                stderr_lines,
            )
    except asyncio.CancelledError:
        return


def _proc_stderr_tail(proc, *, char_limit: int = 2000) -> str:
    """Return the buffered stderr tail, joined and clipped to ``char_limit``."""
    buf = getattr(proc, "_ace_stderr_buf", None)
    if not buf:
        return ""
    text = "\n".join(buf)
    if len(text) > char_limit:
        return text[-char_limit:]
    return text
