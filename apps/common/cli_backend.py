"""CLIBackend — wraps the Claude CLI in stream-json input/output mode.

Wire format
-----------
We use stream-json on BOTH stdin and stdout. The user message goes in as one
``{"type":"user","message":{"role":"user","content":"<text>"}}`` JSON line.
The CLI streams response events back on stdout in the same envelope shape.

Why stream-json input (vs. plain ``-p`` text):
  * Canonical multi-turn protocol — claude treats stdin as a stream of user
    messages, not a single one-shot prompt. The long-lived per-session path
    relies on this: subsequent turns just write another envelope onto the
    existing stdin instead of respawning the CLI (and rebooting all MCPs).
  * No prompt-text injection edge cases — the message body is JSON-quoted, so
    user input that looks like a turn boundary or a control sequence can't
    confuse the CLI.
  * Better auth ergonomics — the CLI never tries to interpret stdin as a shell
    pipe.

Two execution paths
-------------------

1. ``_stream_one_shot`` — used when ``force_fresh_session=True`` (auto-titler).
   Spawns a brand-new subprocess, writes the user message, drains until DONE,
   closes stdin, tears down the staged HOME. Mirrors the old spawn-per-turn
   model exactly. Does NOT touch the long-lived ``_sessions`` pool.

2. Long-lived per-Session subprocess (default). ``CLIBackend._sessions`` holds
   one ``SessionProcess`` per Django ``Session.slug``. The subprocess boots
   once (paying the ~5–30s MCP-startup cost), then each turn writes one
   user-message envelope onto its stdin. The 30-min idle reaper evicts
   processes whose last turn finished long enough ago that we no longer
   want to keep their MCP working sets resident.

Stdin lifecycle (load-bearing)
------------------------------
With ``--input-format stream-json``, the CLI keeps reading stdin until EOF and
will hang if you write a message and never close stdin. BUT — verified live
on 2.1.126 — if stdin EOFs *too early* (before the CLI has fully booted MCPs
+ hooks and read the buffered message), the CLI bails after running just the
SessionStart hooks and produces no result event.

  * One-shot path (``_drain``): closes stdin once a ``result`` event
    (StreamEventType.DONE) is observed, so the CLI exits cleanly.
  * Long-lived path (``_drain_persistent``): MUST NOT close stdin on DONE.
    The subprocess stays alive for the next turn. Stdin is only closed by
    ``_evict_session`` (via ``terminate()``).

Resume + recovery
-----------------
  * First spawn for a Session with a stored ``cli_session_id`` uses
    ``--resume <id>``. If that spawn produces zero events (the CLI's local
    session store rotated out the id), we fall back inline to a fresh spawn
    with the full conversation history seeded from Django — same recovery
    that existed in the spawn-per-turn model.
  * Mid-turn subprocess death (after at least one event was yielded) clears
    ``Session.cli_session_id``, evicts the ``SessionProcess``, and surfaces
    a ``CLIBackendError`` to the consumer. The user retries; the next call
    spawns a fresh long-lived process.

Cancellation
------------
On consumer cancel mid-turn (browser closes, ``stop_event`` fires), the
async generator's ``aclose()`` runs the long-lived path's outer ``except
GeneratorExit`` and evicts the ``SessionProcess`` — the in-flight turn
cannot be safely resumed because the CLI is mid-stream and there is no
documented stdin "cancel current turn" envelope on the 2.1.x stream-json
protocol. The next turn for this Session pays one MCP-startup cost to
respawn, which is acceptable for the rare cancel-mid-turn case.
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

# How long a long-lived SessionProcess can sit idle (no turn finished) before
# the reaper evicts it. 30 minutes balances:
#   * memory pressure (each process holds the MCP working set: ~hundreds of MB
#     once gdrive/ocs/mobile/connect/nova have all initialised), and
#   * UX cost of respawning (paying the ~5–30s MCP-startup cost again on the
#     next turn after eviction).
# A user who came back after lunch will pay one rewarm; an active conversation
# rolls forward without ever evicting.
SESSION_IDLE_TIMEOUT_SECONDS = 30 * 60

# How often the reaper scans for stale sessions. Coarse on purpose — there is
# no SLA on eviction precision, and we don't want to waste cycles polling a
# typically-empty dict every few seconds.
SESSION_IDLE_SWEEP_INTERVAL_SECONDS = 5 * 60


class CLIBackendError(RuntimeError):
    """Raised when the CLI subprocess fails in a way the consumer should know about."""


class SessionProcess:
    """Per-Django-Session long-lived subprocess state.

    Lives in ``CLIBackend._sessions`` keyed by ``Session.slug``. Each
    ``SessionProcess`` owns:
      * one ``asyncio.subprocess.Process`` (claude CLI), staged into a fresh
        ``/tmp/ace-cli/<slug>-<uuid>/`` HOME so concurrent sessions can't
        clobber each other's ``~/.claude/.credentials.json``,
      * the credential ``source`` ("user" / "global" / "env") so we can
        persist any CLI-refreshed OAuth blob back to the right storage layer
        on eviction,
      * an ``asyncio.Lock`` that serialises turns within this Session — without
        it, two concurrent ``stream_completion`` calls would interleave on
        the same stdin and corrupt both turns,
      * ``last_active`` (monotonic) so the idle reaper can decide eviction.

    ``session_pk`` is stored so the reaper (which only has the slug from the
    dict) can fetch the ``Session`` row to call ``_persist_refreshed_blob``
    correctly. Slug-keyed dict + pk-keyed DB lookup is the cleanest split
    given Django's async-ORM constraints.
    """

    __slots__ = (
        "slug", "session_pk", "proc", "staged_home", "staged_env",
        "credential_source", "lock", "last_active", "cli_session_id",
        "spawned_with_resume",
    )

    def __init__(self, slug: str, session_pk: int):
        self.slug = slug
        self.session_pk = session_pk
        self.proc = None
        self.staged_home: str | None = None
        self.staged_env: dict[str, str] | None = None
        self.credential_source: str | None = None
        self.lock = asyncio.Lock()
        self.last_active = time.monotonic()
        self.cli_session_id: str | None = None
        # True when the most recent spawn used --resume <cli_session_id>.
        # Read by the resume-failure recovery path — only fall back to a
        # fresh seeded-history spawn if the failed spawn was a --resume
        # one. Cleared on successful first event.
        self.spawned_with_resume = False

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None


class CLIBackend:
    """Async chat backend that wraps the Claude CLI.

    Maintains one long-lived ``SessionProcess`` per Django ``Session.slug``
    in ``self._sessions`` so subsequent turns of the same conversation
    avoid the per-spawn MCP-startup cost. ``force_fresh_session=True``
    bypasses the pool and uses the one-shot path (auto-titler invariant).

    Concurrency: ``self._sessions_dict_lock`` guards dict mutations.
    Each ``SessionProcess.lock`` serialises turns within one Session.
    """

    def __init__(
        self,
        *,
        binary: str = "claude",
        circuit_threshold: int = 5,
        circuit_cooldown: float = 30.0,
        terminate_grace_seconds: float = 2.0,
        session_idle_timeout_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS,
        session_idle_sweep_interval_seconds: float = SESSION_IDLE_SWEEP_INTERVAL_SECONDS,
    ):
        self._binary = binary
        self._breaker = CircuitBreaker(
            threshold=circuit_threshold, cooldown_seconds=circuit_cooldown
        )
        self._terminate_grace = terminate_grace_seconds
        self._sessions: dict[str, SessionProcess] = {}
        self._sessions_dict_lock = asyncio.Lock()
        self._idle_reaper_task: asyncio.Task | None = None
        self._idle_timeout_seconds = session_idle_timeout_seconds
        self._idle_sweep_interval_seconds = session_idle_sweep_interval_seconds

    async def stream_completion(
        self,
        *,
        session: Session,
        new_user_message: str,
        force_fresh_session: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one assistant turn.

        Routes to the one-shot path when ``force_fresh_session=True`` (used
        by the auto-titler so its prompt doesn't pollute conversation
        history). Otherwise routes to the long-lived path that keeps one
        ``claude`` subprocess per Session alive across turns, paying the
        MCP-startup cost only on first contact + after eviction.

        Yields events as they arrive. On consumer cancellation (break out
        of the ``async for``), Python calls ``aclose()`` which triggers
        cleanup — for the one-shot path that terminates the proc; for the
        long-lived path that evicts the entire ``SessionProcess`` (the
        in-flight turn cannot be safely resumed mid-stream).
        """
        try:
            self._breaker.check()
        except CircuitOpenError as exc:
            raise CLIBackendError(str(exc)) from exc

        # Explicit aclose is REQUIRED. ``async for ... yield`` does not
        # propagate GeneratorExit to the inner generator: when the consumer
        # aclose()s the outer generator, Python tears down the outer frame
        # and the inner generator (a local in that frame) becomes
        # unreachable, which schedules its aclose via gc — asynchronously
        # with respect to our outer aclose. The inner's ``except
        # GeneratorExit`` handler then runs whenever the loop next services
        # it, by which point the test (or production cancel-cleanup
        # sequencing) has already moved on. Wrap each in a finally that
        # explicitly aclose()s the inner so its cleanup runs synchronously
        # with ours — which for the long-lived path means evicting the
        # SessionProcess before the consumer's cancel handler returns.
        if force_fresh_session:
            agen = self._stream_one_shot(session, new_user_message)
        else:
            agen = self._stream_long_lived(session, new_user_message)
        try:
            async for event in agen:
                yield event
        finally:
            await agen.aclose()

    # ──────────────────────────── one-shot path ────────────────────────────

    async def _stream_one_shot(
        self, session: Session, new_user_message: str
    ) -> AsyncIterator[StreamEvent]:
        """Spawn a one-shot subprocess, drain it, tear down. Used by the
        auto-titler (``force_fresh_session=True``) — bypasses ``_sessions``
        so the title prompt doesn't show up in the conversation transcript.

        Mirrors the pre-Phase-1B spawn-per-turn semantics exactly: stage
        env, spawn with optional --resume, drain (closes stdin on DONE),
        fall back to seeded history if --resume produces zero events,
        persist refreshed blob, rmtree HOME.
        """
        staged_env, staged_home, source = await sync_to_async(self._stage_env_for)(
            session
        )
        try:
            # The auto-titler always passes force_fresh_session=True. By design
            # we DO NOT pass --resume here — the titler should run as a
            # standalone CLI session so it can't pollute the chat's history.
            # (cli_session_id is only ever read in the long-lived path.)
            proc = await self._spawn(
                args=[],
                prompt=new_user_message,
                env=staged_env,
                session_slug=session.slug,
            )
            had_events = False
            try:
                async for event in self._drain(proc):
                    had_events = True
                    yield event
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

    # ─────────────────────────── long-lived path ───────────────────────────

    async def _stream_long_lived(
        self, session: Session, new_user_message: str
    ) -> AsyncIterator[StreamEvent]:
        """Drive one turn through the per-Session long-lived subprocess.

        Boots the subprocess on first contact (paying the ~5–30s MCP-startup
        cost once per Session), then writes the new user-message envelope to
        the existing stdin for every subsequent turn. The 30-min idle reaper
        evicts processes whose last turn finished long enough ago.

        Recovery:
          * First spawn with --resume produces zero events → inline fallback
            to fresh spawn with seeded history (preserves the user-perceived
            UX of the spawn-per-turn model).
          * Mid-turn proc death (after at least one event) → clear
            ``Session.cli_session_id``, evict, surface ``CLIBackendError``.
          * Consumer cancel mid-turn (``GeneratorExit`` /
            ``asyncio.CancelledError``) → evict + propagate.
        """
        await self._ensure_idle_reaper()
        sp = await self._get_or_create_session_process(session)

        async with sp.lock:
            spawn_attempted = False
            had_any_event = False
            try:
                if not sp.is_alive():
                    await self._spawn_session_process(sp, session)
                    spawn_attempted = True

                try:
                    async for event in self._send_and_drain_persistent(
                        sp, new_user_message
                    ):
                        had_any_event = True
                        if (
                            event.type is StreamEventType.SESSION_ID
                            and event.session_id
                        ):
                            sp.cli_session_id = event.session_id
                            await self._persist_session_id(
                                session, event.session_id
                            )
                        yield event
                except CLIBackendError:
                    # Resume-failure recovery: if the spawn we just did used
                    # --resume and produced zero events, the CLI's local
                    # session store has rotated out our id. Fall back inline
                    # to a fresh spawn seeded with Django history so the
                    # user doesn't see a spurious failure on their first
                    # turn back after an idle eviction.
                    if (
                        spawn_attempted
                        and sp.spawned_with_resume
                        and not had_any_event
                    ):
                        logger.warning(
                            "long-lived: --resume %s produced no events for "
                            "session=%s — clearing cli_session_id and "
                            "respawning with seeded history",
                            sp.cli_session_id or session.cli_session_id,
                            session.slug,
                        )
                        await self._clear_cli_session_id(session)
                        sp.cli_session_id = None
                        await self._terminate_proc(sp)
                        # Respawn fresh (cli_session_id is now cleared so no
                        # --resume will be added). Reuse the staged env from
                        # the dead proc to avoid re-staging credentials.
                        await self._spawn_session_process(sp, session)
                        history_prompt = await self._build_seeded_prompt(
                            session, new_user_message
                        )
                        async for event in self._send_and_drain_persistent(
                            sp, history_prompt
                        ):
                            had_any_event = True
                            if (
                                event.type is StreamEventType.SESSION_ID
                                and event.session_id
                            ):
                                sp.cli_session_id = event.session_id
                                await self._persist_session_id(
                                    session, event.session_id
                                )
                            yield event
                    else:
                        raise

                sp.last_active = time.monotonic()
                # Persist any OAuth refresh that landed during this turn.
                # Same rationale as the one-shot path's finally block: the
                # claude CLI refreshes tokens in-place by overwriting
                # ``$HOME/.claude/.credentials.json``; if we let the worker
                # die without reading it back, the next call uses an
                # already-burned refresh token and 401s.
                try:
                    await sync_to_async(self._persist_refreshed_blob)(
                        session, sp.credential_source, sp.staged_home
                    )
                except Exception:
                    logger.warning(
                        "long-lived: failed to persist refreshed blob "
                        "for session=%s",
                        session.slug,
                        exc_info=True,
                    )
                self._breaker.record_success()

            except (GeneratorExit, asyncio.CancelledError):
                # Consumer cancelled mid-turn (browser closed, stop_event
                # fired). The CLI is mid-stream and there is no documented
                # cancel envelope on the 2.1.x stream-json input protocol,
                # so the only safe recovery is to terminate the whole
                # subprocess and evict. Next turn pays one MCP-startup cost.
                logger.info(
                    "long-lived: consumer cancelled mid-turn for session=%s "
                    "— evicting subprocess",
                    session.slug,
                )
                await self._evict_locked(sp, persist_for_session=session)
                await self._drop_session_from_pool(sp.slug)
                # Don't record_failure — cancel is not a CLI failure.
                raise
            except (BrokenPipeError, ConnectionResetError) as exc:
                logger.warning(
                    "long-lived: subprocess pipe died for session=%s: %s",
                    session.slug,
                    exc,
                )
                await self._evict_locked(sp, persist_for_session=session)
                await self._drop_session_from_pool(sp.slug)
                self._breaker.record_failure()
                raise CLIBackendError(
                    f"claude CLI subprocess died mid-turn: {exc}"
                ) from exc
            except CLIBackendError:
                # Either the original CLIBackendError (re-raised above when
                # not eligible for resume-fallback) or the seeded-history
                # fallback also failed. Evict + clear cli_session_id so the
                # next turn doesn't try --resume again.
                logger.warning(
                    "long-lived: CLI failure for session=%s — evicting "
                    "and clearing cli_session_id",
                    session.slug,
                )
                if sp.spawned_with_resume:
                    await self._clear_cli_session_id(session)
                await self._evict_locked(sp, persist_for_session=session)
                await self._drop_session_from_pool(sp.slug)
                self._breaker.record_failure()
                raise
            except Exception:
                # Unknown failure — evict to avoid leaking a half-broken
                # process. Don't suppress; let the caller see what blew up.
                logger.exception(
                    "long-lived: unexpected error for session=%s — evicting",
                    session.slug,
                )
                await self._evict_locked(sp, persist_for_session=session)
                await self._drop_session_from_pool(sp.slug)
                self._breaker.record_failure()
                raise

    async def _get_or_create_session_process(
        self, session: Session
    ) -> SessionProcess:
        async with self._sessions_dict_lock:
            sp = self._sessions.get(session.slug)
            if sp is None:
                sp = SessionProcess(slug=session.slug, session_pk=session.pk)
                self._sessions[session.slug] = sp
            return sp

    async def _spawn_session_process(
        self, sp: SessionProcess, session: Session
    ) -> None:
        """Stage credentials, boot the subprocess, attach to ``sp``.

        Does NOT write the user-message envelope — that happens in
        ``_send_and_drain_persistent`` per turn. Spawns with ``--resume
        <cli_session_id>`` if one is set on the Session; otherwise spawns
        fresh and the first SESSION_ID event captures the new id.

        Stages a fresh per-Session HOME under ``/tmp/ace-cli/<slug>-<uuid>/``
        and stores the path on ``sp.staged_home`` so eviction can rmtree it.
        Re-staging on every spawn (rather than reusing a dead proc's HOME)
        keeps eviction cleanup symmetric.
        """
        # If we're respawning into an existing sp (resume-failure recovery),
        # rmtree the previous staged HOME first to avoid leaking it.
        if sp.staged_home:
            self._teardown_staged_home(sp.staged_home)
            sp.staged_home = None

        staged_env, staged_home, source = await sync_to_async(self._stage_env_for)(
            session
        )
        sp.staged_env = staged_env
        sp.staged_home = staged_home
        sp.credential_source = source

        if session.cli_session_id:
            args = ["--resume", session.cli_session_id]
            sp.spawned_with_resume = True
            sp.cli_session_id = session.cli_session_id
        else:
            args = []
            sp.spawned_with_resume = False

        sp.proc = await self._spawn(
            args=args,
            prompt=None,  # long-lived: don't write the user message at boot
            env=staged_env,
            session_slug=session.slug,
        )

    async def _send_and_drain_persistent(
        self, sp: SessionProcess, message_text: str
    ) -> AsyncIterator[StreamEvent]:
        """Write one user-message envelope to the live stdin, drain one turn.

        Differs from ``_drain`` in two ways:
          1. Writes the user-message envelope BEFORE draining (the long-lived
             spawn doesn't pre-write at boot time the way the one-shot path
             does).
          2. Stops at DONE without closing stdin — the subprocess stays alive
             for the next turn. Stdin is only closed by ``_terminate_proc``
             via ``proc.terminate()``.

        Raises ``CLIBackendError`` if the proc dies before producing any
        events (the resume-failure-recovery path uses this signal to fall
        back to a fresh seeded-history spawn).
        """
        proc = sp.proc
        if proc is None:
            raise CLIBackendError(
                f"_send_and_drain_persistent called with no live proc "
                f"for session={sp.slug}"
            )

        envelope = (
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": message_text},
            }).encode("utf-8")
            + b"\n"
        )
        try:
            proc.stdin.write(envelope)
            await proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError) as exc:
            raise CLIBackendError(
                f"claude CLI stdin closed before user message delivered: {exc}"
            ) from exc

        had_events = False
        async for event in self._drain_persistent(proc):
            had_events = True
            yield event

        if not had_events:
            stderr_text = _proc_stderr_tail(proc, char_limit=2000)
            if stderr_text:
                logger.error(
                    "long-lived[%s] CLI stderr tail: %s", sp.slug, stderr_text
                )
            raise CLIBackendError(
                f"claude CLI produced no events (rc={proc.returncode})"
                + (f" stderr: {stderr_text[:500]}" if stderr_text else "")
            )
        # First successful turn — clear the resume marker so subsequent
        # turn failures don't attempt the seeded-history fallback (which
        # is only correct for the very first --resume attempt).
        sp.spawned_with_resume = False

    async def _drain_persistent(self, proc) -> AsyncIterator[StreamEvent]:
        """Read stdout line by line until DONE, WITHOUT closing stdin.

        Mirror of ``_drain`` minus the stdin-close-on-DONE behaviour. The
        subprocess stays open for subsequent turns; only ``_terminate_proc``
        (via ``proc.terminate()``) closes stdin.
        """
        while True:
            line = await proc.stdout.readline()
            if not line:
                # EOF — the subprocess died. Caller raises CLIBackendError
                # on zero-events; mid-turn EOF after at least one event is
                # picked up by the outer error path which evicts.
                return
            text = line.decode("utf-8", errors="replace")
            for event in parse_stream_json_lines([text]):
                yield event
                if event.type is StreamEventType.DONE:
                    return

    async def _terminate_proc(self, sp: SessionProcess) -> None:
        """SIGTERM → SIGKILL the SessionProcess's subprocess + cancel its
        background tasks. Leaves ``sp.staged_home`` and ``sp`` itself in
        place — eviction handles those. Used by resume-failure recovery
        to kill the dead-spawn proc before spawning a fresh one onto the
        same ``sp``.
        """
        if sp.proc is None:
            return
        await self._cleanup(sp.proc)
        sp.proc = None

    async def _evict_session(
        self,
        slug: str,
        *,
        persist_for_session: Session | None = None,
    ) -> None:
        """Remove a SessionProcess from the pool: terminate proc, persist any
        refreshed OAuth blob, rmtree staged HOME, drop dict entry.

        Acquires ``sp.lock`` so we don't kill a turn in flight. Idempotent
        — calling twice is safe.

        ``persist_for_session`` is the live ``Session`` ref (when the caller
        already has it, e.g. the idle reaper passes ``None`` and we fetch
        via ``sp.session_pk``).

        **Do not call this from inside the long-lived path's
        ``async with sp.lock:`` block** — asyncio.Lock is non-reentrant.
        Use ``_evict_locked`` from there instead, then drop the dict entry
        directly.
        """
        async with self._sessions_dict_lock:
            sp = self._sessions.get(slug)
            if sp is None:
                return

        async with sp.lock:
            await self._evict_locked(sp, persist_for_session=persist_for_session)

        async with self._sessions_dict_lock:
            self._sessions.pop(slug, None)

    async def _evict_locked(
        self,
        sp: SessionProcess,
        *,
        persist_for_session: Session | None = None,
    ) -> None:
        """Eviction body — caller MUST hold ``sp.lock`` already.

        Does the proc cleanup, OAuth blob persistence, and HOME rmtree, but
        does NOT touch ``self._sessions`` (the caller is responsible for
        the dict mutation under ``self._sessions_dict_lock``). Split out
        from ``_evict_session`` so the long-lived path's error handlers can
        evict without re-acquiring the lock they already hold.
        """
        if sp.proc is not None:
            try:
                await self._cleanup(sp.proc)
            except Exception:
                logger.warning(
                    "_evict_locked: cleanup failed for %s",
                    sp.slug,
                    exc_info=True,
                )
            sp.proc = None

        if sp.staged_home and sp.credential_source:
            try:
                if persist_for_session is not None:
                    await sync_to_async(self._persist_refreshed_blob)(
                        persist_for_session,
                        sp.credential_source,
                        sp.staged_home,
                    )
                else:
                    await sync_to_async(self._persist_refreshed_blob_for_pk)(
                        sp.session_pk,
                        sp.credential_source,
                        sp.staged_home,
                    )
            except Exception:
                logger.warning(
                    "_evict_locked: persist_refreshed_blob failed for %s",
                    sp.slug,
                    exc_info=True,
                )

        if sp.staged_home:
            self._teardown_staged_home(sp.staged_home)
            sp.staged_home = None

    async def _drop_session_from_pool(self, slug: str) -> None:
        """Remove a slug from the dict under ``_sessions_dict_lock``.
        Called by the long-lived error handlers after ``_evict_locked``.
        """
        async with self._sessions_dict_lock:
            self._sessions.pop(slug, None)

    def _persist_refreshed_blob_for_pk(
        self, session_pk: int, source: str | None, staged_home: str
    ) -> None:
        """Slug-less variant of ``_persist_refreshed_blob`` — fetches the
        ``Session`` row by pk first. Used by the idle reaper, which only has
        the slug and the session_pk it stashed at SessionProcess creation.
        Returns silently if the Session has been deleted (the credential
        blob has nowhere to go).
        """
        try:
            session = Session.objects.get(pk=session_pk)
        except Session.DoesNotExist:
            return
        self._persist_refreshed_blob(session, source, staged_home)

    async def _clear_cli_session_id(self, session: Session) -> None:
        @sync_to_async
        def _clear():
            Session.objects.filter(pk=session.pk).update(cli_session_id=None)
            session.cli_session_id = None

        await _clear()

    # ───────────────────────── idle reaper ─────────────────────────

    async def _ensure_idle_reaper(self) -> None:
        """Lazily start the idle-reaper background task. Idempotent —
        called from every ``stream_completion`` invocation; no-op once the
        task is running. Started on first stream_completion rather than at
        ``__init__`` so the task is bound to the running event loop.
        """
        if self._idle_reaper_task is not None and not self._idle_reaper_task.done():
            return
        self._idle_reaper_task = asyncio.create_task(
            self._idle_reaper(), name="cli-backend-idle-reaper"
        )

    async def _idle_reaper(self) -> None:
        """Sweep ``_sessions`` for SessionProcesses idle longer than the
        timeout and evict them. Runs forever (cancelled at worker
        shutdown). Per-eviction errors are swallowed so one bad eviction
        can't take down the reaper.
        """
        while True:
            try:
                await asyncio.sleep(self._idle_sweep_interval_seconds)
            except asyncio.CancelledError:
                return
            try:
                now = time.monotonic()
                async with self._sessions_dict_lock:
                    stale = [
                        slug
                        for slug, sp in self._sessions.items()
                        if now - sp.last_active > self._idle_timeout_seconds
                    ]
                for slug in stale:
                    try:
                        logger.info(
                            "idle-reaper: evicting session=%s "
                            "(idle for >%ds)",
                            slug,
                            int(self._idle_timeout_seconds),
                        )
                        await self._evict_session(slug)
                    except Exception:
                        logger.exception(
                            "idle-reaper: evict failed for %s", slug
                        )
            except Exception:
                logger.exception("idle-reaper: sweep failed")

    # ────────────────────────────── helpers ──────────────────────────────

    async def _spawn(
        self,
        *,
        args: list[str],
        prompt: str | None,
        env: dict[str, str],
        session_slug: str = "",
    ):
        """Spawn the CLI subprocess. Optionally write a user-message envelope
        to stdin.

        ``prompt`` semantics:
          * ``str`` — write the user-message envelope to stdin immediately
            (one-shot path: this is the single turn the spawn will serve).
            Stdin is left OPEN; ``_drain`` closes it on DONE.
          * ``None`` — skip the write (long-lived path: the subprocess is
            booting, the actual user message gets written per-turn by
            ``_send_and_drain_persistent``).

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

        Raises CLIBackendError if the subprocess dies before accepting the
        prompt (e.g., binary missing, permission denied, instant crash).
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
        # stdin here — see module docstring "Stdin lifecycle". On the one-shot
        # path, _drain closes stdin after observing the result/DONE event so
        # the CLI exits cleanly. On the long-lived path, prompt is None — the
        # per-turn user-message envelope goes in via _send_and_drain_persistent.
        if prompt is not None:
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
