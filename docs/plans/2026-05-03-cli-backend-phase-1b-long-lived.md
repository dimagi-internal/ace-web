# Plan: long-lived per-session `claude` subprocess (Phase 1B)

**Status**: HISTORICAL — shipped in commit `a02093e`. Source of truth for the
live design is the `apps/common/cli_backend.py` module docstring's
"Two execution paths" section. Keep this file as the original design
record but do not treat it as forward-looking.
**Date**: 2026-05-03
**Prereq**: PR #198 (Phase 1A — `--input-format stream-json` wire format), already merged + live on task def :159.

## Goal

Replace the spawn-per-turn model in `apps/common/cli_backend.py` with one
long-lived `claude -p --input-format stream-json --output-format stream-json`
subprocess per Django Session. Subsequent turns write user-message envelopes
to the existing stdin instead of respawning, eliminating the per-turn
MCP-startup cost (~5–30s).

This is the foundation for autonomous `/ace:run` on the web. It does **not**
fully solve autonomous orchestration on its own — see § Out of scope.

## Why

### Cost today (spawn-per-turn)

Every chat turn:
1. Stages a fresh `~/.claude` HOME under `/tmp/ace-cli/<slug>-<uuid>/`
2. Spawns `claude -p --resume <cli_session_id>` (with stream-json input now)
3. Boots all five MCP servers (`ace-gdrive`, `ace-ocs`, `ace-connect`,
   `ace-mobile`, `nova`) — each one runs `npx tsx <plugin>/mcp/<server>.ts`,
   loads its `.env`, opens auth contexts. Verified live: `claude mcp list`
   typically takes 25–30 s for all five to reach `connected`.
4. Drains response events
5. Tears down staged HOME (rm-tree), persists any refreshed OAuth blob

Most of that cost is fixed-per-spawn overhead, paid for every "continue" or
follow-up turn. For a 30-min `/ace:run` session, the rewarm cost dominates.

### What Phase 1B unlocks

- One MCP-startup cost per session, not per turn
- Multi-turn within one process — natural fit for Claude Code's stream-json
  protocol
- Cleaner state: no more `--resume <id>` respawn-with-seeded-history fallback
  on the happy path
- Foundation for autonomous orchestration (auto-continue can just write the
  next user-message envelope to the open stdin)

## Design

### `SessionProcess` class

Holds per-Django-Session state. Lives in `apps/common/cli_backend.py`.

```python
class SessionProcess:
    __slots__ = (
        "slug", "proc", "staged_home", "credential_source",
        "lock", "last_active", "cli_session_id",
    )

    def __init__(self, slug: str): ...
    def is_alive(self) -> bool: ...
```

Fields:

- `slug` — `Session.slug`, the dict key in `CLIBackend._sessions`
- `proc` — the `asyncio.subprocess.Process`, or `None` before first spawn /
  after eviction
- `staged_home` — path to `/tmp/ace-cli/<slug>-<uuid>/`. Created on first
  spawn, rm-treed on eviction
- `credential_source` — `"user"` / `"global"` / `"env"` / `None`. Used by
  `_persist_refreshed_blob` on eviction so the (possibly-rotated) OAuth
  blob lands back in the right storage layer
- `lock` — `asyncio.Lock()`. Serializes turns within one session — without
  this, two concurrent turn-driver invocations would interleave on stdin
- `last_active` — `time.monotonic()` at the end of the last turn. Read by
  the idle reaper
- `cli_session_id` — captured from the CLI's first `init` event. Used to
  pass `--resume` if we ever need to respawn (after idle eviction or worker
  bounce)

### `CLIBackend` changes

```python
class CLIBackend:
    def __init__(self, ...):
        # existing fields
        self._sessions: dict[str, SessionProcess] = {}
        self._sessions_dict_lock = asyncio.Lock()
        self._idle_reaper_task: asyncio.Task | None = None

    async def stream_completion(self, *, session, new_user_message, force_fresh_session=False):
        if force_fresh_session:
            async for ev in self._stream_one_shot(session, new_user_message):
                yield ev
            return
        await self._ensure_idle_reaper()
        sp = await self._get_or_create_session_process(session)
        async with sp.lock:
            if not sp.is_alive():
                await self._spawn_session_process(sp, session)
            try:
                async for ev in self._send_and_drain_persistent(sp, new_user_message):
                    yield ev
                    if ev.type is StreamEventType.SESSION_ID and ev.session_id:
                        sp.cli_session_id = ev.session_id
                        await self._persist_session_id(session, ev.session_id)
                sp.last_active = time.monotonic()
            except (BrokenPipeError, ConnectionResetError, CLIBackendError) as exc:
                await self._evict_session(sp.slug, persist_blob_for=session)
                self._breaker.record_failure()
                raise CLIBackendError(f"claude CLI subprocess died mid-turn: {exc}") from exc
```

### Three paths

1. **`force_fresh_session=True`** (auto-titler) → `_stream_one_shot` —
   today's existing logic, unchanged. Spawns a brand-new subprocess, runs
   one prompt, tears down. Doesn't touch `_sessions` dict. Preserves the
   "don't pollute conversation history" invariant.

2. **First turn for a Session** (or first after eviction) → `_spawn_session_process`
   spawns the long-lived subprocess. Two cases:
   - `session.cli_session_id` is set (returning user, evicted/bounced):
     spawn with `--resume <id>`, send just the new user-message envelope.
   - Not set (genuinely first turn): spawn fresh. The first user-message
     envelope is just the new message — no seeded history needed because
     there isn't any.

3. **Subsequent turn within a live subprocess** → `_send_and_drain_persistent`
   writes the new user-message envelope to existing stdin, drains events
   until DONE. **Does not close stdin** (so the subprocess waits for the
   next turn). Updates `last_active`.

### Idle reaper

```python
async def _idle_reaper(self):
    while True:
        await asyncio.sleep(SESSION_IDLE_SWEEP_INTERVAL_SECONDS)  # 5 min
        now = time.monotonic()
        async with self._sessions_dict_lock:
            stale = [
                slug for slug, sp in self._sessions.items()
                if now - sp.last_active > SESSION_IDLE_TIMEOUT_SECONDS  # 30 min
            ]
        for slug in stale:
            try:
                await self._evict_session(slug, persist_blob_for=None)
            except Exception:
                logger.exception("idle-reaper: evict failed for %s", slug)
```

Eviction:
- Acquire `sp.lock` so we don't kill a turn in flight
- `_cleanup(proc)` — SIGTERM → SIGKILL with 2 s grace
- Re-read `staged_home/.claude/.credentials.json`, persist via
  `_persist_refreshed_blob` (need the original `Session` ref OR re-fetch
  from DB — see § Open questions)
- `shutil.rmtree(staged_home)`
- `del self._sessions[slug]`

### Resume-failure recovery

On subprocess death after a `--resume` spawn (idle-evicted user came back,
their CLI session has expired in claude's local store):

- `_send_and_drain_persistent` sees the proc emit an error event and exit
- Catch the resulting `CLIBackendError`
- Clear `session.cli_session_id` (DB write)
- Evict from `_sessions`
- Surface a "please retry" error to the consumer

Next turn from the user re-spawns fresh with seeded history (same fallback
path that exists today via `_build_seeded_prompt`).

**Trade-off considered:** auto-retry inline so the user doesn't see a
failure. Rejected — too easy to get stuck in retry loops, and the user-
facing "retry" UX is well-understood.

### Worker shutdown

Register an asyncio shutdown hook (or use Channels' `shutdown` event) that:
1. Iterates `_sessions`
2. For each, persists refreshed blob + SIGTERM/grace/SIGKILL
3. rm-tree all staged HOMEs

If the worker is killed without grace (OOM, hard kill), the staged HOMEs
in `/tmp` are leaked but that's recoverable — `/tmp` clears on container
restart.

## Tests

New tests in `apps/common/tests/test_cli_backend.py`:

| Test | Verifies |
|---|---|
| `test_session_process_reused_across_turns` | Two `stream_completion` calls for the same session call `create_subprocess_exec` once |
| `test_session_process_evicted_on_subprocess_death` | If proc dies mid-turn, next turn spawns fresh |
| `test_idle_reaper_evicts_stale_sessions` | Patch `time.monotonic` to advance past idle threshold; reaper kills proc + rms HOME |
| `test_concurrent_turns_serialized_by_lock` | Two simultaneous turn calls don't interleave on stdin |
| `test_force_fresh_session_does_not_use_long_lived_pool` | `force_fresh_session=True` always spawns fresh (auto-titler invariant) |
| `test_resume_failure_evicts_and_clears_session_id` | If `--resume` spawn dies with no events, evict + clear `Session.cli_session_id` |

Existing tests stay (they test the inner mechanics — stage_env_for, drain,
etc.) but `test_resume_uses_existing_cli_session_id` and similar may need
adjustment to account for the long-lived path.

## Out of scope (explicitly)

The following are deliberately NOT part of Phase 1B:

- **Cross-worker session affinity.** Same Django Session bouncing between
  ECS tasks gets a fresh `SessionProcess` on each. Worse than ideal but
  not broken (each respawns with `--resume`). Sticky session at the ALB
  would solve this — separate work.
- **Per-process memory tracking / limits.** A long-running session with a
  big context could accumulate. Mitigated by 30-min idle eviction; out of
  scope to enforce harder limits.
- **Auto-continue trigger for autonomous `/ace:run`.** Phase 1B makes each
  "continue" cheap; somebody (server-side state.yaml polling, or a
  user-driven "continue" button, or a model-side self-prompt) still has
  to send the next user-message envelope. Separate doc.
- **Splitting seeded-history concatenation into one envelope per historical
  message.** Possible incremental win for the "evicted-user-comes-back"
  fallback path but not necessary for Phase 1B.

## Open questions to resolve before coding

1. **Token persistence cadence.** Today the credential blob is re-read and
   persisted after every turn. Long-lived: do the same (read on every
   turn end), or only on eviction? Per-turn read is cheap (~ms) and
   simplest; eviction-only saves a tiny amount of work but loses any
   refresh that happened between turns if the worker dies hard.
   **Suggested:** persist on every turn end, same as today.

2. **`Session` reference on idle reaper.** The reaper has the slug but
   not the live `Session` model — needs a DB fetch to call
   `_persist_refreshed_blob` correctly (which expects a `Session` arg).
   Either fetch via `Session.objects.get(slug=...)` or persist via slug
   directly. **Suggested:** add a slug-keyed `_persist_refreshed_blob`
   variant that fetches the `Session` itself; cheap, called rarely.

3. **What if the consumer cancels mid-turn (browser closes during long
   tool call)?** Today: `_cleanup` SIGTERMs the proc, HOME rm-treed, done.
   With long-lived: the proc is shared with other tabs / future turns of
   the same session. **Suggested:** on consumer cancel, write a
   `cancellation` JSON event to stdin if the CLI supports one (check
   `--help`); otherwise terminate + evict the whole `SessionProcess`.
   Better than today: the user's "cancel" doesn't kill an in-progress
   tool call from another tab, but it does cause that other tab to lose
   its session and respawn.
   **Verify:** does `claude --help` document a stdin "cancel current
   turn" message in stream-json mode? If yes, use it. If no, fall back
   to terminate.

4. **`auth_flow.cli_is_ready` interaction.** `backend_selector` calls this
   on every turn to decide CLI vs API backend. With long-lived processes,
   does that probe spawn a separate `claude` to validate? If yes, that's
   a different code path that doesn't share the long-lived pool. Verify
   it's still a one-shot validation, not coupled to the chat path.

## Implementation order (suggested)

1. Branch off `main`. Read this doc, confirm design.
2. Write `SessionProcess` + `_get_or_create_session_process` +
   `_spawn_session_process` + `_send_and_drain_persistent`. Skip idle
   reaper for now — set `SESSION_IDLE_TIMEOUT_SECONDS` to a very small
   value in tests instead.
3. Refactor `stream_completion` to route through the new path. Keep the
   one-shot path for `force_fresh_session=True`.
4. Update + expand tests.
5. Local validation against `docker compose up`.
6. PR review against this doc.
7. Add idle reaper, eviction, error recovery. Tests.
8. Deploy to staging task def, smoke-test with `cli-diag` (one prompt
   completes, second prompt with same session reuses subprocess).
9. Deploy to prod task def. Watch CloudWatch for `subprocess died` /
   `idle-reaper: evict failed` logs over 24 h.
10. Iterate on token persistence cadence + cross-worker affinity if data
    suggests it's needed.

## What I learned in 2026-05-03 session that's load-bearing for this work

These are findings from the Phase 1A session (already shipped) that any
Phase 1B implementer needs in their head:

- **Wire format**: `{"type":"user","message":{"role":"user","content":"<text>"}}\n`
  with `content` as a STRING. List-of-blocks form (`content: [{type:"text",...}]`)
  also accepted but verbose. Current code uses string form.
- **Stdin lifecycle**: with `--input-format stream-json`, the CLI hangs
  forever if you don't close stdin. But it ALSO hangs if you close stdin
  *before* it has finished booting MCPs and reading the buffered message.
  The Phase 1A drain closes stdin on DONE. Phase 1B drain MUST NOT close
  stdin (it's the persistent process); only `_evict_session` closes it
  (via `terminate()`).
- **MCP startup cost is the real prize.** ~5–30 s per spawn for the five
  MCPs to reach `connected`. Verified live in Phase 1A cli-diag — even
  with `tsx` global (PR #186), connect is the only MCP routinely
  `connected` within 30 s; gdrive/ocs/mobile usually `pending` at init
  snapshot but reachable via `ToolSearch` later in the same session.
- **MCP log location**: `~/.cache/claude-cli-nodejs/-app/mcp-logs-plugin-<name>/<ts>.jsonl`.
  Per-spawn, recreated each subprocess. Phase 1B's per-session
  subprocess will have one log file per session lifetime — useful for
  debugging.
- **Don't trust the `init` payload's `mcp_servers[].status`.** It's a
  snapshot from before all servers have connected. The model has access
  to MCP tools as soon as the corresponding server's `tools/list` event
  lands, regardless of what `init` reported. (This was the source of the
  "ace-gdrive missing" red herring on 2026-05-02 — it was actually a
  startup crash from the SA-key path bug, fixed in PR #192.)

## Risk assessment

- **Hot path**: this is the chat backend for ALL users. Bug here breaks
  chat for everyone. Tests must cover reuse, eviction, concurrent turns,
  subprocess death.
- **Memory**: a process per session × N sessions × MCP working sets.
  Need to measure post-deploy. Idle reaper at 30 min mitigates.
- **OAuth refresh races**: persisting on every turn end (suggested) plus
  multiple workers serving the same user could race. Mitigated by
  Anthropic accepting any non-burned refresh token; worst case is a
  retry. Already happens today with multiple browser tabs.

## Estimated effort

5–6 hours of focused work (one ~half-day session) for a production-ready
PR. Breakdown:

- 0:30 — design review + open-question answers
- 1:30 — `SessionProcess` + spawn/send/drain methods
- 0:45 — eviction + idle reaper + worker shutdown
- 0:45 — `--resume` integration + resume-failure handling
- 1:30 — tests
- 0:60 — local validation, deploy, CloudWatch watching
