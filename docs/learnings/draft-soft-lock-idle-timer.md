# Learning: Wall-clock UI transitions need explicit setTimeout re-renders in React

**Date**: 2026-04-09
**Context**: Phase 3 multi-player drafts show a soft lock indicator that is supposed to flip to "idle — another user can take over" after 2 s of inactivity.
**Status**: Active

## Problem

The draft lock UX is: while Alice is actively typing, Bob's `SendBox` shows
a disabled input with "Alice is editing". If Alice stops typing for 2 s,
Bob's input should unlock with a "take over" CTA — no server push, no
explicit transition event, just a wall-clock threshold on the last known
`last_edit_at` timestamp.

The naive implementation computes `isIdle` inline on every render:

```ts
const holderIsIdle = Date.now() - lastEditAt > IDLE_THRESHOLD_MS;
```

This is correct whenever the component actually re-renders — but React
does not re-render on wall-clock time. It re-renders when state or props
change. If nothing else changes between T and T+2s, `holderIsIdle` is
never recomputed, and Bob's UI stays locked indefinitely.

## Symptom

Alice types in her SendBox, stops. Bob watches his UI. The lock stays in
place. No error, no console warning, no "take over" button. Two minutes
later, an unrelated event (a heartbeat-triggered `presence.joined`, a new
chat message arriving) causes a re-render, Bob's UI finally recomputes
`holderIsIdle`, and the lock releases. The visible behaviour is "the UI is
broken and then fixes itself when you click something unrelated."

This is harder to debug than it sounds, because any exploratory interaction
(opening devtools, resizing the window, refocusing the tab) might trigger
a re-render and make the bug appear to go away.

## Fix

Schedule an explicit `setTimeout` that forces a re-render at exactly the
idle transition point:

```ts
const [forceTick, setForceTick] = useState(0);

useEffect(() => {
  if (!lastEditAt || holderUserId === currentUserId) return;

  const wait = msUntilDraftIdle(lastEditAt, Date.now(), IDLE_THRESHOLD_MS);
  if (wait <= 0) return;  // already idle, render handled it

  const id = setTimeout(() => setForceTick((t) => t + 1), wait);
  return () => clearTimeout(id);
}, [lastEditAt, holderUserId, currentUserId]);
```

The `forceTick` state is a counter whose only job is to change, forcing
React to re-run the render function and recompute `holderIsIdle` against
the current `Date.now()`. The cleanup in the effect cancels a pending
timer whenever `lastEditAt` changes (a new keystroke) — we don't want to
accumulate one timer per keystroke.

The shared helper `msUntilDraftIdle(lastEditAt, now, threshold)` lives in
`frontend/src/lib/drafts.ts` and returns `Math.max(0, threshold - (now - lastEditAt))`.
Centralizing it means the timer math and the render-time comparison can't
drift apart, and it is trivially unit-testable (pure function, no React).

## Generalization

Any React UI that shows a wall-clock-driven transition needs this pattern:

- "N seconds ago" / "just now" / "a minute ago" relative timestamps
- Session idle warnings ("you'll be logged out in 30 s")
- Optimistic UI that reverts if the server doesn't respond within X ms
- Rate-limit UIs that re-enable a button after a cooldown

The common thread is "the transition is caused by time passing, not by an
event." React's render model is event-driven. If you want time-driven
transitions, you have to turn time into an event with a `setTimeout` or a
`setInterval`, and make sure cleanup happens on unmount and on dependency
changes.

## Key files

- `frontend/src/lib/drafts.ts` — `msUntilDraftIdle` pure helper, unit tested.
- `frontend/src/components/SendBox.tsx` — the `useEffect` + `setTimeout` +
  `forceTick` pattern; computes `holderIsIdle` at render time against the
  latest `Date.now()`.
- `frontend/src/pages/ChatPage.tsx` — passes `lastEditAt`, `holderUserId`,
  and `currentUserId` down from the `useSessionSocket` hook.
