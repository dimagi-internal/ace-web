# Stop-During-Reconnect Queue (Phase A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the targeted piece of vercel-labs/open-agents' `AbortableChatTransport` pattern into our WS chat hook: when the user clicks "stop" while the WebSocket is reconnecting, queue the frame and flush on next OPEN instead of silently dropping it.

**Scope:** This is the small lift only. The related "reconnect during stream loses up to 250 ms of characters" hazard is documented in `docs/learnings/stream-resume-vercel-open-agents.md` but is **deferred** — fixing it properly requires Redis live-mirror state + delta sequence numbers + client dedupe, which is a multi-day architectural change, not a port. Address it as a separate decision when the gap is observed in real use.

**Tech Stack:** React 19 + TypeScript (existing). No backend changes. No tests (frontend has no test rig today; validated via typecheck + build + manual smoke).

**Pre-read:** `docs/learnings/stream-resume-vercel-open-agents.md` — the why.

---

## File Structure

**Modify:**
- `frontend/src/hooks/useSessionSocket.ts` — add a `pendingFramesRef` queue, route `chat.stop` through it when WS is not OPEN, flush in `onopen`.

That's the entire change. ~10 lines.

---

## Task 1: useSessionSocket queues chat.stop frames when WS is not OPEN

**Files:**
- Modify: `frontend/src/hooks/useSessionSocket.ts:45-62` (refs + the `send` callback) and `:299-308` (the `onopen` handler).

- [ ] **Step 1: Add the pending-frames ref**

In `frontend/src/hooks/useSessionSocket.ts`, after the existing refs (around line 51, just after `closedByUserRef`), add:

```typescript
const pendingFramesRef = useRef<{ action: string; data: unknown }[]>([]);
```

- [ ] **Step 2: Queue control frames in `send`**

Replace the `send` callback (currently lines 57-62):

```typescript
const send = useCallback((frame: { action: string; data: unknown }) => {
  const ws = socketRef.current;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(frame));
    return;
  }
  // Queue control frames that must not be lost across a reconnect.
  // Currently only chat.stop — the WS analogue of open-agents'
  // AbortableChatTransport. Draft updates are intentionally NOT queued:
  // they have a version guard and the user's keystrokes will refresh
  // the body anyway.
  if (frame.action === "chat.stop") {
    pendingFramesRef.current.push(frame);
  }
}, []);
```

- [ ] **Step 3: Flush the queue on `onopen`**

In the `connect` callback's `ws.onopen` handler (currently lines 299-308), insert the flush right after `setConnected(true)` and `reconnectAttemptRef.current = 0`, before the heartbeat timer setup:

```typescript
ws.onopen = () => {
  setConnected(true);
  reconnectAttemptRef.current = 0;
  // Flush any control frames that were queued while the socket was
  // closed. See `send` above.
  const queued = pendingFramesRef.current;
  pendingFramesRef.current = [];
  for (const frame of queued) {
    ws.send(JSON.stringify(frame));
  }
  if (heartbeatTimerRef.current != null) {
    window.clearInterval(heartbeatTimerRef.current);
  }
  heartbeatTimerRef.current = window.setInterval(() => {
    send({ action: "presence.heartbeat", data: {} });
  }, HEARTBEAT_INTERVAL_MS);
};
```

- [ ] **Step 4: Verify typecheck + build**

Run: `cd frontend && bun run typecheck && bun run build`
Expected: both green.

- [ ] **Step 5: Manual smoke**

In the dev container (`docker compose up`):

1. Log in, open a session, send a long prompt that takes 5+ seconds to stream.
2. In DevTools Network tab, toggle "Offline" mid-stream.
3. Click the Stop button while offline.
4. Toggle back to Online.
5. Verify: the assistant message flips to error state with `cancelled (partial: …)` detail. (Without the queue, the cancel was silently dropped and the turn would have completed normally — observable in Postgres as a `complete`-status assistant row.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useSessionSocket.ts
git commit -m "fix(chat): queue chat.stop while WS reconnecting

Stop frames sent while the WebSocket is not OPEN are now buffered and
flushed on the next onopen, instead of being silently dropped. WS-world
analogue of vercel-labs/open-agents' AbortableChatTransport.

See docs/learnings/stream-resume-vercel-open-agents.md."
```

---

## Verification checklist (run before opening the PR)

- [ ] `cd frontend && bun run typecheck && bun run build` — both green.
- [ ] Manual smoke (as in Step 5) — verify that stop-during-offline cancels the server-side turn after reconnect.
- [ ] PR description links `docs/learnings/stream-resume-vercel-open-agents.md` for context.
