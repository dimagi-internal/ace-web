# Learning: Stream-resume hazards (and what to lift from vercel-labs/open-agents)

**Date**: 2026-05-05
**Context**: ace-web's Phase 2/3 chat path (`apps/sessions/consumers.py`, `apps/sessions/turn_driver.py`, `frontend/src/hooks/useSessionSocket.ts`) has unresolved hazards around what happens when the user disconnects, navigates, or hits "stop" while a stream is in flight. Vercel just open-sourced [vercel-labs/open-agents](https://github.com/vercel-labs/open-agents), whose `docs/agents/lessons-learned.md` documents the same class of bugs in detail. This file captures the relevant findings and where ace-web has matching exposure, so the next person to touch streaming code does not re-learn them.
**Status**: Partial — Hazard 1 (stop-during-reconnect) being addressed via `docs/plans/2026-05-05-stream-reconnect-resilience.md`. Hazard 2 (reconnect-during-stream gap) is **documented but deferred**: a proper fix requires Redis live-mirror state + delta sequence numbers + client-side dedupe, which is a multi-day architectural change, not a port. Revisit when the 250 ms character-loss gap is observed in real user reports.

## Two distinct hazards

### Hazard 1 — "stop is silently dropped while reconnecting"

`useSessionSocket.stopChat` ([frontend/src/hooks/useSessionSocket.ts:375](../../frontend/src/hooks/useSessionSocket.ts)) calls `send()`, which is a no-op when `socketRef.current.readyState !== WebSocket.OPEN`. If the user clicks "stop" while the socket is reconnecting (after a transient drop, page focus change, or backend restart), the stop frame is dropped on the floor. The server-side turn driver keeps running until it completes naturally, racking up CLI cost the user thought they had aborted.

Open-agents hits the same shape with HTTP fetch + `chat.stop()`:
> **For resumed chat streams, `chat.stop()` alone is insufficient because reconnect fetches are not wired to the active abort signal; always pair stop with aborting the managed transport tied to that chat instance.**
> — [vercel-labs/open-agents `lessons-learned.md`](https://github.com/vercel-labs/open-agents/blob/main/docs/agents/lessons-learned.md), "Chat / Streaming UI"

Their fix is `AbortableChatTransport` — a single swappable `AbortController` that is injected into every fetch (incl. resume/reconnect) so a single `chat.stop()` tears them all down. Our equivalent is simpler: queue WS frames sent while not OPEN and flush them on the next `onopen`. See plan Task 1.

### Hazard 2 — "reconnect during stream loses characters"

`turn_driver.drive_assistant_turn` ([apps/sessions/turn_driver.py:171-178](../../apps/sessions/turn_driver.py)) accumulates deltas in memory and writes the full accumulated plaintext to Postgres every 250 ms. The DB row therefore lags the in-memory accumulator by up to 250 ms. The Channels broadcast carries only the new chunk (`event.text`), not the cumulative plaintext.

When the WebSocket disconnects:
- The turn task keeps running (no consumer-side cancel in `disconnect()`; broadcasts go to the channel-layer group regardless of listener count — by design).
- The DB row's plaintext is the snapshot from the last 250 ms tick.
- Any deltas broadcast in the gap between the last DB tick and the disconnect are **lost from the perspective of a future reconnect**: the channel layer does not retain them for new subscribers.

On reconnect, `_sync_build_state` ([apps/sessions/consumers.py:585-600](../../apps/sessions/consumers.py)) reads `messages.plaintext` from Postgres. The next `chat.delta` arrives over the group, and `applyEvent` ([useSessionSocket.ts:91-99](../../frontend/src/hooks/useSessionSocket.ts)) appends to whatever the snapshot had. Result: the assistant response is missing 0–250 ms of characters at the disconnect boundary, with no gap indicator visible to the user.

Open-agents hits the same shape and fixes it with two complementary mechanisms:
> **For client-side tool flows (`ask_user_question`), `onFinish`-only assistant persistence is insufficient across route switches: persist the latest incoming message snapshot at API request start (upsert by message id) so answered/declined tool state survives teardown/resume and does not rehydrate stale `input-available` UI.**

> **Request-start assistant snapshot persistence must be scoped and ownership-guarded: only upsert assistant messages when the request still owns the chat stream token, and refuse upserts on message-id scope conflict (different chat/role) to prevent stale writes and cross-chat overwrites.**

> **Keep `activeStreamId` resumable at all times: do not publish pre-registration ownership placeholders to `activeStreamId` (resume probes can clear them as stale), and gate `onFinish` writes on the atomic compare-and-set result that clears the currently owned token.**

Our analogue, scaled to the WS/Channels architecture: maintain a **live plaintext mirror in Redis** keyed by message id, written on every delta (cheap), and read by `_sync_build_state` to overlay the DB snapshot for streaming-status messages. Pair it with a per-message `seq` on every chat.delta and a `live_seq` on the snapshot, so the client can deduplicate any delta that arrives on the group but is already covered by the snapshot. See plan Tasks 2–5.

## What does NOT apply from open-agents

Their lessons-learned has ~50 items; most don't map to us:

- **Sandbox lifecycle** (~25 items): we have no sandbox — `claude -p` runs as a subprocess on the same Django host. The whole "snapshot/hibernate/restore/reconnect" matrix is irrelevant.
- **Vercel Workflow SDK lease tokens / `lifecycleRunId`**: we have no durable workflow runtime; turn tasks are plain `asyncio.create_task` with strong-ref pinning in `_turn_tasks`. The lease-token pattern is elegant but presumes Workflow SDK or Celery beat — not justified for our scale.
- **GitHub App install / OAuth callback flows**: irrelevant — we use CommCare Connect OAuth, see `apps/auth/oauth_views.py` and `docs/learnings/connect-oauth-openid-email.md`.
- **AI SDK `UIMessage` chunks / `Streamdown`**: we have our own `StreamEvent` discriminated union (`apps/common/chat_backend.py`) and the frontend renders messages via custom React components. No port path.
- **Next.js `after()` semantics**: irrelevant — Django views + Channels consumers handle their own teardown via `finally` and `asyncio.shield`.
- **Auto-commit / auto-PR from server completion path**: already correct on our side. `turn_driver` runs auto-title server-side via `_schedule_auto_title`, not via a client-side `status === "ready"` effect.

## Lessons that match what we already do (validated)

These are confirmations that our existing design is on the right side of an open-agents lesson — worth knowing so we don't accidentally regress:

- **"Both `submitted` and `streaming` are in-flight"** — `useSessionSocket` treats messages with `status === "streaming"` and the placeholder created by `draft.committed` (effectively pending) as in-flight. Tool-use rendering does not key off completion alone.
- **"Auto-commit / post-turn automations on the server completion path, not client `status === ready`"** — `turn_driver._schedule_auto_title` and `_broadcast_opp_updated_if_needed` run server-side, inside the turn task's terminal branch, before the consumer's broadcast. They survive client disconnects mid-stream.
- **"Per-task GC-safe pinning of background tasks"** — `_bg_tasks` and `_turn_tasks` keep strong references to spawned tasks with self-removing `add_done_callback` cleanup, exactly the pattern they recommend.

## Pointers

- Their full file: <https://github.com/vercel-labs/open-agents/blob/main/docs/agents/lessons-learned.md>
- Companion skills repo (parallel to ours): <https://github.com/vercel-labs/skills>
- Concrete ports tracked in: `docs/plans/2026-05-05-stream-reconnect-resilience.md`
