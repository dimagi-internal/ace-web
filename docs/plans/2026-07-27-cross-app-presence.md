# Cross-App Viewer Presence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Google-Docs-style "who else is viewing this page" badge on every page of ace-web and canopy-web — a compressed avatar cluster that expands into a live, named viewer list.

**Architecture:** One shared React module (`canopy-ui/presence`) authored in canopy-web and consumed by both apps, plus one thin Channels WebSocket backend per app writing to that app's own Redis. Rosters are per-app and independent. Grouping is by normalized logical resource (an opp run, not a step), so people on different sub-pages of the same resource see each other.

**Tech Stack:** React 19 + TypeScript + vitest (frontend); Django 5 + Channels 4 + channels-redis + `redis.asyncio` + pytest/fakeredis (both backends).

**Spec:** `docs/specs/2026-07-27-cross-app-presence-design.md`

## Global Constraints

- Python: `line-length=100`, `target=py311`, ruff rules `E,F,W,I,UP,B`.
- ace-web tests: `.venv/bin/pytest` (provision once per worktree: `uv venv --python=3.11 .venv && uv pip install --python .venv/bin/python -e ".[dev]"`).
- canopy-web tests: `uv run pytest`.
- ace-web frontend tests: `bun run test` from `frontend/`. canopy-web frontend tests: `npm run test` from `frontend/`.
- Heartbeat interval **20s**; Redis field TTL **60s**; Redis key TTL **120s**. These three are load-bearing (3× slack ratio) — do not tune them independently.
- Presence must never break a page: every failure path degrades to "badge renders nothing". No toasts, no error boundaries, no retry storms.
- Visibility (`show_presence=False`) is enforced **server-side only**. Never filter an opted-out user on the client.
- `fakeredis` tests MUST import the module, not the function: `from apps.common import redis_client` then `redis_client.get_redis()`. The direct-function import binds at import time and silently defeats `monkeypatch`, sending tests at a real Redis. (`docs/learnings/redis-presence-hash.md`)
- Channels group names allow only ASCII alphanumerics, hyphens, periods, underscores (max 100 chars) — page keys contain `:` and `/` and MUST be hashed before use as a group name.

## Deviation from the spec (deliberate)

The spec says the preference is "a boolean on the user model in each app". That works in ace-web (custom `ace_auth.User`) but **not** in canopy-web, which uses Django's stock `auth.User`. To keep the two backends symmetric, both apps get an identical `PresencePreference` model (`OneToOneField` to the user, `show_presence` boolean, default `True`) instead. No user table is touched in either app.

## File Structure

**canopy-web — shared frontend** (`frontend/packages/canopy-ui/src/presence/`)

| File | Responsibility |
| --- | --- |
| `pageKey.ts` | `pageKeyFor()` — pure route → `{pageKey, subLocation}`. The grouping brain. |
| `pageKey.test.ts` | Route-table tests for both apps' shapes. |
| `avatar.ts` | `avatarFor()` — initials + deterministic color from email. |
| `usePresence.ts` | One socket per tab, re-keys on navigation, heartbeats, idle detection. |
| `PresenceBadge.tsx` | Collapsed avatar cluster + expand popover. |
| `PresenceBadge.test.tsx` | Empty / overflow / expand / idle rendering. |
| `index.ts` | Public exports for the `canopy-ui/presence` subpath. |

**canopy-web — backend** (`apps/realtime/`, alongside the existing consumers)

| File | Responsibility |
| --- | --- |
| `presence_keys.py` | `parse_page_key()`, `group_name()`. Pure. |
| `presence_store.py` | Redis HASH read/write/sweep. Async. |
| `presence_consumer.py` | `PresenceConsumer`. |
| `models.py` (modify) | `PresencePreference`. |

**ace-web — backend** (new app `apps/presence/`)

| File | Responsibility |
| --- | --- |
| `keys.py`, `store.py`, `consumers.py`, `routing.py`, `models.py`, `api.py` | Same responsibilities as canopy's, app-local. |

The Redis store is intentionally duplicated across the two repos rather than extracted into a shared Python package. It is ~120 lines, and the approved architecture is "two independent backends" — a shared package would add a second cross-repo version pin (like the existing `canopy-agent-runs` git-tag dependency) and make a backend hotfix in one app require a tag bump in the other. If the store grows materially, `packages/canopy_presence` is the escape hatch.

## Task Order

- **Tasks 1–8** — one canopy-web PR (shared frontend + canopy backend + mount).
- **Task 9** — publish `canopy-ui@0.6.0`. Blocks on Task 8 merging.
- **Tasks 10–12** — one ace-web PR. Tasks 10 and 11 (the ace-web backend) have
  no dependency on Tasks 1–9 and may be built in parallel with the canopy work;
  only Task 12 (the mount) blocks on Task 9.
- **Task 13** — deploy verification.

---

### Task 1: `pageKeyFor()` — the grouping brain

**Files:**
- Create: `frontend/packages/canopy-ui/src/presence/pageKey.ts`
- Test: `frontend/packages/canopy-ui/src/presence/pageKey.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```ts
  export interface PageLocation { pageKey: string; subLocation: string }
  export interface RouteRule {
    pattern: RegExp
    build: (m: RegExpMatchArray) => { workspace: string; resource: string; subLocation: string }
  }
  export function pageKeyFor(app: string, pathname: string, rules: RouteRule[]): PageLocation | null
  ```
  Returns `null` when no rule matches — callers render no badge rather than grouping strangers under a catch-all key.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/packages/canopy-ui/src/presence/pageKey.test.ts
import { describe, expect, it } from 'vitest'
import { pageKeyFor, type RouteRule } from './pageKey'

const ACE_RULES: RouteRule[] = [
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)\/runs\/([^/]+)\/steps\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `opp:${m[2]}/${m[3]}`, subLocation: m[4] }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)\/runs\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `opp:${m[2]}/${m[3]}`, subLocation: 'run overview' }),
  },
  {
    pattern: /^\/w\/([^/]+)\/activity/,
    build: (m) => ({ workspace: m[1], resource: 'activity', subLocation: 'Activity' }),
  },
]

describe('pageKeyFor', () => {
  it('collapses every step of a run onto one key, keeping the step as sub-location', () => {
    const a = pageKeyFor('ace', '/w/dimagi-team/opps/bednet/runs/run-001/steps/idea-to-pdd', ACE_RULES)
    const b = pageKeyFor('ace', '/w/dimagi-team/opps/bednet/runs/run-001', ACE_RULES)
    expect(a?.pageKey).toBe('ace:dimagi-team:opp:bednet/run-001')
    expect(b?.pageKey).toBe(a?.pageKey)
    expect(a?.subLocation).toBe('idea-to-pdd')
    expect(b?.subLocation).toBe('run overview')
  })

  it('keeps different runs of the same opp on different keys', () => {
    const a = pageKeyFor('ace', '/w/dimagi-team/opps/bednet/runs/run-001', ACE_RULES)
    const b = pageKeyFor('ace', '/w/dimagi-team/opps/bednet/runs/run-002', ACE_RULES)
    expect(a?.pageKey).not.toBe(b?.pageKey)
  })

  it('namespaces by app so two apps never collide', () => {
    const ace = pageKeyFor('ace', '/w/dimagi-team/activity', ACE_RULES)
    const canopy = pageKeyFor('canopy', '/w/dimagi-team/activity', ACE_RULES)
    expect(ace?.pageKey).toBe('ace:dimagi-team:activity')
    expect(canopy?.pageKey).toBe('canopy:dimagi-team:activity')
  })

  it('returns null for unmatched routes rather than a catch-all key', () => {
    expect(pageKeyFor('ace', '/totally/unknown', ACE_RULES)).toBeNull()
  })

  it('is order-sensitive: the first matching rule wins', () => {
    const loose: RouteRule[] = [
      { pattern: /^\/w\/([^/]+)\/opps/, build: (m) => ({ workspace: m[1], resource: 'opps', subLocation: 'Opps' }) },
      ...ACE_RULES,
    ]
    expect(pageKeyFor('ace', '/w/x/opps/bednet/runs/run-001', loose)?.pageKey).toBe('ace:x:opps')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/pageKey.test.ts`
Expected: FAIL — cannot resolve `./pageKey`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/packages/canopy-ui/src/presence/pageKey.ts

/** A resolved presence location: which roster to join, and where in it you are. */
export interface PageLocation {
  /** `<app>:<workspace|global>:<resource>` — the roster identity. */
  pageKey: string
  /** Human-readable position within the resource, for the expanded panel. */
  subLocation: string
}

export interface RouteRule {
  pattern: RegExp
  build: (m: RegExpMatchArray) => { workspace: string; resource: string; subLocation: string }
}

/**
 * Resolve a pathname to a presence location. Pure — the single place
 * grouping correctness lives.
 *
 * Rules are evaluated in order and the first match wins, so more specific
 * patterns must be listed before looser ones.
 *
 * Returns null when nothing matches. Callers render no badge in that case;
 * grouping every unrecognised route under one catch-all key would put
 * unrelated strangers in the same roster.
 */
export function pageKeyFor(
  app: string,
  pathname: string,
  rules: RouteRule[],
): PageLocation | null {
  for (const rule of rules) {
    const m = pathname.match(rule.pattern)
    if (!m) continue
    const { workspace, resource, subLocation } = rule.build(m)
    return { pageKey: `${app}:${workspace}:${resource}`, subLocation }
  }
  return null
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/pageKey.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/packages/canopy-ui/src/presence/pageKey.ts frontend/packages/canopy-ui/src/presence/pageKey.test.ts
git commit -m "feat(presence): pageKeyFor route-to-roster resolution"
```

---

### Task 2: Avatar identity

**Files:**
- Create: `frontend/packages/canopy-ui/src/presence/avatar.ts`
- Test: `frontend/packages/canopy-ui/src/presence/avatar.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `export function avatarFor(email: string, name: string): { initials: string; colorClass: string }`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/packages/canopy-ui/src/presence/avatar.test.ts
import { describe, expect, it } from 'vitest'
import { avatarFor } from './avatar'

describe('avatarFor', () => {
  it('takes initials from a two-part display name', () => {
    expect(avatarFor('alice@x.com', 'Alice Chen').initials).toBe('AC')
  })

  it('falls back to the email local-part when there is no name', () => {
    expect(avatarFor('bob.ali@x.com', '').initials).toBe('BA')
  })

  it('produces a single initial for a one-word identity', () => {
    expect(avatarFor('ace@x.com', 'ACE').initials).toBe('A')
  })

  it('is deterministic: the same email is always the same color', () => {
    expect(avatarFor('alice@x.com', 'Alice Chen').colorClass)
      .toBe(avatarFor('alice@x.com', 'Different Name').colorClass)
  })

  it('keys color on email, not name, so a rename does not recolor someone', () => {
    const a = avatarFor('alice@x.com', 'Alice Chen')
    const b = avatarFor('zoe@x.com', 'Alice Chen')
    expect(a.colorClass).not.toBe(b.colorClass)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/avatar.test.ts`
Expected: FAIL — cannot resolve `./avatar`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/packages/canopy-ui/src/presence/avatar.ts

// Fixed palette. Chosen for legibility against white text in both themes;
// index is picked by a stable hash of the email so a person keeps one color
// everywhere, in every app, across sessions.
const COLORS = [
  'bg-sky-600',
  'bg-emerald-600',
  'bg-violet-600',
  'bg-amber-600',
  'bg-rose-600',
  'bg-teal-600',
  'bg-indigo-600',
  'bg-fuchsia-600',
]

function hash(value: string): number {
  // djb2. Not cryptographic — we only need stable bucketing.
  let h = 5381
  for (let i = 0; i < value.length; i++) h = ((h << 5) + h + value.charCodeAt(i)) | 0
  return Math.abs(h)
}

/**
 * Initials + a stable color class for one person.
 *
 * Color keys on email rather than display name so changing your name does
 * not change your color out from under people who have learned it.
 */
export function avatarFor(email: string, name: string): { initials: string; colorClass: string } {
  const source = (name || email.split('@')[0] || '?').trim()
  const words = source.split(/[\s._-]+/).filter(Boolean)
  const initials =
    words.length >= 2
      ? (words[0][0] + words[1][0]).toUpperCase()
      : (words[0]?.[0] ?? '?').toUpperCase()
  return { initials, colorClass: COLORS[hash(email) % COLORS.length] }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/avatar.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/packages/canopy-ui/src/presence/avatar.ts frontend/packages/canopy-ui/src/presence/avatar.test.ts
git commit -m "feat(presence): deterministic avatar initials and colors"
```

---

### Task 3: `usePresence()` hook

**Files:**
- Create: `frontend/packages/canopy-ui/src/presence/usePresence.ts`
- Test: `frontend/packages/canopy-ui/src/presence/usePresence.test.ts`

**Interfaces:**
- Consumes: `PageLocation` from `./pageKey` (Task 1).
- Produces:
  ```ts
  export interface Viewer {
    email: string; name: string; subLocation: string; idle: boolean; self: boolean
  }
  export interface UsePresenceOptions {
    url: string                  // absolute ws:// or wss:// URL
    location: PageLocation | null
  }
  export function usePresence(opts: UsePresenceOptions): { viewers: Viewer[] }
  ```

Wire protocol (must match the backend in Tasks 5 and 10 exactly):

```jsonc
// client -> server
{"type": "presence.enter", "page_key": "...", "sub_location": "..."}
{"type": "presence.heartbeat", "idle": false}
// server -> client
{"event": "presence.roster",
 "data": {"page_key": "...", "viewers": [
    {"email": "...", "name": "...", "sub_location": "...", "idle": false, "self": true}]}}
```

- [ ] **Step 1: Write the failing test**

```ts
// frontend/packages/canopy-ui/src/presence/usePresence.test.ts
// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePresence } from './usePresence'

class FakeSocket {
  static last: FakeSocket | null = null
  static OPEN = 1
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  constructor(public url: string) {
    FakeSocket.last = this
  }
  send(frame: string) {
    this.sent.push(frame)
  }
  close() {
    this.readyState = 3
  }
  open() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.()
  }
  deliver(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeSocket as unknown as typeof WebSocket)
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  FakeSocket.last = null
})

const LOC = { pageKey: 'ace:ws:opp:a/run-001', subLocation: 'run overview' }

describe('usePresence', () => {
  it('sends presence.enter once the socket opens', () => {
    renderHook(() => usePresence({ url: 'ws://x/ws/presence/', location: LOC }))
    act(() => FakeSocket.last!.open())
    expect(JSON.parse(FakeSocket.last!.sent[0])).toEqual({
      type: 'presence.enter',
      page_key: LOC.pageKey,
      sub_location: LOC.subLocation,
    })
  })

  it('exposes the roster the server broadcasts', () => {
    const { result } = renderHook(() => usePresence({ url: 'ws://x/ws/presence/', location: LOC }))
    act(() => FakeSocket.last!.open())
    act(() =>
      FakeSocket.last!.deliver({
        event: 'presence.roster',
        data: {
          page_key: LOC.pageKey,
          viewers: [{ email: 'a@x.com', name: 'A', sub_location: 'idea-to-pdd', idle: false, self: true }],
        },
      }),
    )
    expect(result.current.viewers).toEqual([
      { email: 'a@x.com', name: 'A', subLocation: 'idea-to-pdd', idle: false, self: true },
    ])
  })

  it('ignores a roster for a page key it is no longer on', () => {
    const { result } = renderHook(() => usePresence({ url: 'ws://x/ws/presence/', location: LOC }))
    act(() => FakeSocket.last!.open())
    act(() =>
      FakeSocket.last!.deliver({
        event: 'presence.roster',
        data: { page_key: 'ace:ws:opp:STALE/run-999', viewers: [
          { email: 'z@x.com', name: 'Z', sub_location: '', idle: false, self: false }] },
      }),
    )
    expect(result.current.viewers).toEqual([])
  })

  it('re-enters without reconnecting when the location changes', () => {
    const { rerender } = renderHook(
      ({ location }) => usePresence({ url: 'ws://x/ws/presence/', location }),
      { initialProps: { location: LOC } },
    )
    act(() => FakeSocket.last!.open())
    const socket = FakeSocket.last!
    rerender({ location: { pageKey: 'ace:ws:activity', subLocation: 'Activity' } })
    expect(FakeSocket.last).toBe(socket) // same socket, no reconnect
    expect(JSON.parse(socket.sent[socket.sent.length - 1])).toEqual({
      type: 'presence.enter',
      page_key: 'ace:ws:activity',
      sub_location: 'Activity',
    })
  })

  it('heartbeats every 20 seconds', () => {
    renderHook(() => usePresence({ url: 'ws://x/ws/presence/', location: LOC }))
    act(() => FakeSocket.last!.open())
    act(() => void vi.advanceTimersByTime(20_000))
    expect(JSON.parse(FakeSocket.last!.sent[1])).toEqual({ type: 'presence.heartbeat', idle: false })
  })

  it('clears the roster and sends nothing when there is no location', () => {
    const { result } = renderHook(() =>
      usePresence({ url: 'ws://x/ws/presence/', location: null }),
    )
    expect(result.current.viewers).toEqual([])
    expect(FakeSocket.last).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/usePresence.test.ts`
Expected: FAIL — cannot resolve `./usePresence`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/packages/canopy-ui/src/presence/usePresence.ts
import { useEffect, useRef, useState } from 'react'
import type { PageLocation } from './pageKey'

export interface Viewer {
  email: string
  name: string
  subLocation: string
  idle: boolean
  self: boolean
}

export interface UsePresenceOptions {
  url: string
  location: PageLocation | null
}

const HEARTBEAT_MS = 20_000
const IDLE_AFTER_MS = 120_000
const RECONNECT_MS = 2_000

/**
 * One presence socket per tab.
 *
 * Navigation re-keys the existing connection with a fresh `presence.enter`
 * rather than reconnecting — a socket per page would churn handshakes on
 * every click.
 *
 * Every failure path degrades to an empty roster. Presence is an
 * enhancement; it must never surface an error to the user.
 */
export function usePresence({ url, location }: UsePresenceOptions): { viewers: Viewer[] } {
  const [viewers, setViewers] = useState<Viewer[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const locationRef = useRef(location)
  const idleRef = useRef(false)
  locationRef.current = location

  // Socket lifecycle. Deliberately NOT keyed on `location` — the socket
  // outlives navigation.
  useEffect(() => {
    if (!location) {
      setViewers([])
      return
    }
    let closedByCleanup = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let heartbeat: ReturnType<typeof setInterval> | null = null

    const send = (frame: unknown) => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(frame))
    }

    const enter = () => {
      const loc = locationRef.current
      if (loc) send({ type: 'presence.enter', page_key: loc.pageKey, sub_location: loc.subLocation })
    }

    function open() {
      const sock = new WebSocket(url)
      wsRef.current = sock
      sock.onopen = () => {
        enter()
        heartbeat = setInterval(
          () => send({ type: 'presence.heartbeat', idle: idleRef.current }),
          HEARTBEAT_MS,
        )
      }
      sock.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.event !== 'presence.roster') return
          // Drop rosters for a page we have already navigated away from —
          // an in-flight broadcast can land after the re-key.
          if (msg.data?.page_key !== locationRef.current?.pageKey) return
          setViewers(
            (msg.data.viewers ?? []).map((v: Record<string, unknown>) => ({
              email: String(v.email ?? ''),
              name: String(v.name ?? ''),
              subLocation: String(v.sub_location ?? ''),
              idle: Boolean(v.idle),
              self: Boolean(v.self),
            })),
          )
        } catch {
          // Malformed frame: ignore. Never surface.
        }
      }
      sock.onclose = () => {
        if (wsRef.current === sock) wsRef.current = null
        if (heartbeat) clearInterval(heartbeat)
        setViewers([])
        if (closedByCleanup) return
        reconnectTimer = setTimeout(open, RECONNECT_MS)
      }
    }
    open()

    return () => {
      closedByCleanup = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (heartbeat) clearInterval(heartbeat)
      wsRef.current?.close()
      wsRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, location === null])

  // Re-key on navigation.
  useEffect(() => {
    const ws = wsRef.current
    if (!location || !ws || ws.readyState !== WebSocket.OPEN) return
    setViewers([])
    ws.send(
      JSON.stringify({
        type: 'presence.enter',
        page_key: location.pageKey,
        sub_location: location.subLocation,
      }),
    )
  }, [location?.pageKey, location?.subLocation])

  // Idle tracking: hidden for longer than IDLE_AFTER_MS. Reports an
  // observable fact (the tab is not frontmost), never an attention claim.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null
    const flush = () => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'presence.heartbeat', idle: idleRef.current }))
      }
    }
    const onVisibility = () => {
      if (document.hidden) {
        timer = setTimeout(() => {
          idleRef.current = true
          flush()
        }, IDLE_AFTER_MS)
      } else {
        if (timer) clearTimeout(timer)
        if (idleRef.current) {
          idleRef.current = false
          flush()
        }
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return { viewers }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/usePresence.test.ts`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/packages/canopy-ui/src/presence/usePresence.ts frontend/packages/canopy-ui/src/presence/usePresence.test.ts
git commit -m "feat(presence): usePresence socket hook with re-key on navigation"
```

---

### Task 4: `<PresenceBadge />`

**Files:**
- Create: `frontend/packages/canopy-ui/src/presence/PresenceBadge.tsx`
- Create: `frontend/packages/canopy-ui/src/presence/index.ts`
- Test: `frontend/packages/canopy-ui/src/presence/PresenceBadge.test.tsx`
- Modify: `frontend/packages/canopy-ui/package.json` (add the `./presence` export)

**Interfaces:**
- Consumes: `Viewer` from `./usePresence` (Task 3), `avatarFor` from `./avatar` (Task 2).
- Produces: `export function PresenceBadge({ viewers }: { viewers: Viewer[] }): JSX.Element | null`, plus the `canopy-ui/presence` public surface: `PresenceBadge`, `usePresence`, `pageKeyFor`, `avatarFor`, and the types `Viewer`, `PageLocation`, `RouteRule`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/packages/canopy-ui/src/presence/PresenceBadge.test.tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PresenceBadge } from './PresenceBadge'
import type { Viewer } from './usePresence'

// NOTE ON CONVENTION: canopy-web has no @testing-library/jest-dom and no
// user-event package. Assertions use toBeTruthy(), interactions use
// fireEvent, and every DOM test carries the `@vitest-environment jsdom`
// docblock above — the vitest config sets no global environment. Do not
// introduce toBeInTheDocument() here; it will not exist.

const viewer = (n: number, over: Partial<Viewer> = {}): Viewer => ({
  email: `u${n}@x.com`,
  name: `User ${n}`,
  subLocation: 'run overview',
  idle: false,
  self: false,
  ...over,
})

describe('PresenceBadge', () => {
  afterEach(cleanup)

  it('renders nothing when you are the only viewer', () => {
    const { container } = render(<PresenceBadge viewers={[viewer(1, { self: true })]} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when the roster is empty', () => {
    const { container } = render(<PresenceBadge viewers={[]} />)
    expect(container.innerHTML).toBe('')
  })

  it('shows at most three avatars and collapses the rest into +N', () => {
    render(<PresenceBadge viewers={[viewer(1), viewer(2), viewer(3), viewer(4), viewer(5)]} />)
    expect(screen.getByText('+2')).toBeTruthy()
  })

  it('labels the control with the viewer count for screen readers', () => {
    render(<PresenceBadge viewers={[viewer(1), viewer(2)]} />)
    expect(screen.getByRole('button', { name: /2 people viewing this page/i })).toBeTruthy()
  })

  it('expands to a named list on click, listing you first and marked', () => {
    render(<PresenceBadge viewers={[viewer(1), viewer(2, { self: true, name: 'Me' })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/Me/)).toBeTruthy()
    expect(screen.getByText('(you)')).toBeTruthy()
    expect(screen.getByText('User 1')).toBeTruthy()
  })

  it('marks idle viewers in the expanded list', () => {
    render(<PresenceBadge viewers={[viewer(1, { idle: true }), viewer(2)]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('idle')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/PresenceBadge.test.tsx`
Expected: FAIL — cannot resolve `./PresenceBadge`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/packages/canopy-ui/src/presence/PresenceBadge.tsx
import { useEffect, useRef, useState } from 'react'
import { avatarFor } from './avatar'
import type { Viewer } from './usePresence'

const MAX_AVATARS = 3

/**
 * Collapsed viewer cluster that expands into a named list.
 *
 * Renders nothing when you are alone — a badge that permanently reads "1"
 * is noise, and the account menu already tells you who you are.
 */
export function PresenceBadge({ viewers }: { viewers: Viewer[] }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (viewers.length < 2) return null

  // You first, then everyone else in roster order.
  const ordered = [...viewers].sort((a, b) => Number(b.self) - Number(a.self))
  const shown = ordered.slice(0, MAX_AVATARS)
  const overflow = ordered.length - shown.length

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${viewers.length} people viewing this page`}
        className="flex items-center -space-x-2 rounded-full p-0.5 hover:opacity-90"
      >
        {shown.map((v) => {
          const { initials, colorClass } = avatarFor(v.email, v.name)
          return (
            <span
              key={v.email}
              className={`inline-flex h-6 w-6 items-center justify-center rounded-full
                ring-2 ring-card text-[10px] font-semibold text-white ${colorClass}
                ${v.idle ? 'opacity-45' : ''}`}
            >
              {initials}
            </span>
          )
        })}
        {overflow > 0 && (
          <span
            className="inline-flex h-6 w-6 items-center justify-center rounded-full
              bg-muted ring-2 ring-card text-[10px] font-semibold text-muted-foreground"
          >
            +{overflow}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 z-50 mt-2 w-64 rounded-md border border-border
            bg-card p-1 shadow-md"
        >
          {ordered.map((v) => {
            const { initials, colorClass } = avatarFor(v.email, v.name)
            return (
              <div key={v.email} className="flex items-center gap-2 rounded px-2 py-1.5">
                <span
                  className={`inline-flex h-6 w-6 shrink-0 items-center justify-center
                    rounded-full text-[10px] font-semibold text-white ${colorClass}
                    ${v.idle ? 'opacity-45' : ''}`}
                >
                  {initials}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-foreground">
                    {v.name || v.email}
                    {v.self && <span className="ml-1 text-muted-foreground">(you)</span>}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {v.subLocation}
                  </span>
                </span>
                {v.idle && <span className="text-[10px] text-muted-foreground">idle</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

```ts
// frontend/packages/canopy-ui/src/presence/index.ts
export { PresenceBadge } from './PresenceBadge'
export { usePresence, type Viewer, type UsePresenceOptions } from './usePresence'
export { pageKeyFor, type PageLocation, type RouteRule } from './pageKey'
export { avatarFor } from './avatar'
```

- [ ] **Step 4: Add the subpath export**

In `frontend/packages/canopy-ui/package.json`, add to `"exports"` (after the `"./chat"` line):

```json
    "./presence": "./src/presence/index.ts",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run packages/canopy-ui/src/presence/`
Expected: PASS — all four test files (pageKey, avatar, usePresence, PresenceBadge).

- [ ] **Step 6: Commit**

```bash
git add frontend/packages/canopy-ui/src/presence/ frontend/packages/canopy-ui/package.json
git commit -m "feat(presence): PresenceBadge and canopy-ui/presence export"
```

---

### Task 5: canopy-web — Redis presence store

**Files:**
- Create: `apps/realtime/presence_keys.py`
- Create: `apps/realtime/presence_store.py`
- Test: `tests/test_presence_store.py`

**Interfaces:**
- Consumes: `apps.common.redis_client.get_redis` (async `redis.asyncio.Redis`).
- Produces:
  ```python
  # presence_keys.py
  def parse_page_key(page_key: str) -> tuple[str, str, str] | None   # (app, workspace, resource)
  def group_name(page_key: str) -> str                               # "presence.<sha1[:32]>"
  # presence_store.py
  FIELD_TTL_SECONDS: int = 60
  KEY_TTL_SECONDS: int = 120
  async def touch(page_key, *, user_id, connection_id, name, email, sub_location, idle) -> None
  async def forget(page_key, *, user_id, connection_id) -> None
  async def roster(page_key) -> list[dict]   # deduped by user_id, sorted by name
  ```
  Each roster entry: `{"user_id": int, "email": str, "name": str, "sub_location": str, "idle": bool}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presence_store.py
import json
import time

import fakeredis.aioredis
import pytest

from apps.realtime import presence_keys, presence_store


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_redis():
        return client

    # Patch the MODULE attribute, not an imported function — presence_store
    # does `from apps.common import redis_client` precisely so this works.
    monkeypatch.setattr("apps.common.redis_client.get_redis", _get_redis)
    return client


def test_parse_page_key_splits_app_workspace_resource():
    assert presence_keys.parse_page_key("ace:dimagi-team:opp:bednet/run-001") == (
        "ace",
        "dimagi-team",
        "opp:bednet/run-001",
    )


def test_parse_page_key_rejects_malformed():
    assert presence_keys.parse_page_key("garbage") is None
    assert presence_keys.parse_page_key("") is None
    assert presence_keys.parse_page_key("ace:only-two") is None


def test_group_name_is_channels_safe():
    name = presence_keys.group_name("ace:ws:opp:a/run-001")
    assert name.startswith("presence.")
    assert len(name) <= 100
    assert all(c.isalnum() or c in "-._" for c in name)


def test_group_name_is_stable_and_distinct():
    assert presence_keys.group_name("ace:ws:a") == presence_keys.group_name("ace:ws:a")
    assert presence_keys.group_name("ace:ws:a") != presence_keys.group_name("ace:ws:b")


@pytest.mark.asyncio
async def test_touch_then_roster_returns_the_viewer(fake_redis):
    await presence_store.touch(
        "ace:ws:opp:a/run-001",
        user_id=7,
        connection_id="c1",
        name="Alice Chen",
        email="alice@x.com",
        sub_location="idea-to-pdd",
        idle=False,
    )
    assert await presence_store.roster("ace:ws:opp:a/run-001") == [
        {
            "user_id": 7,
            "email": "alice@x.com",
            "name": "Alice Chen",
            "sub_location": "idea-to-pdd",
            "idle": False,
        }
    ]


@pytest.mark.asyncio
async def test_two_tabs_same_user_appear_once(fake_redis):
    for conn in ("c1", "c2"):
        await presence_store.touch(
            "ace:ws:p", user_id=7, connection_id=conn, name="A", email="a@x.com",
            sub_location="", idle=False,
        )
    assert len(await presence_store.roster("ace:ws:p")) == 1


@pytest.mark.asyncio
async def test_closing_one_of_two_tabs_keeps_the_user_present(fake_redis):
    """The reason fields are per-connection: this must not evict the user."""
    for conn in ("c1", "c2"):
        await presence_store.touch(
            "ace:ws:p", user_id=7, connection_id=conn, name="A", email="a@x.com",
            sub_location="", idle=False,
        )
    await presence_store.forget("ace:ws:p", user_id=7, connection_id="c1")
    assert len(await presence_store.roster("ace:ws:p")) == 1


@pytest.mark.asyncio
async def test_forgetting_the_last_connection_empties_the_roster(fake_redis):
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=False,
    )
    await presence_store.forget("ace:ws:p", user_id=7, connection_id="c1")
    assert await presence_store.roster("ace:ws:p") == []


@pytest.mark.asyncio
async def test_expired_fields_are_swept_on_read(fake_redis):
    key = "presence:ace:ws:p"
    await fake_redis.hset(
        key,
        "9.dead",
        json.dumps({
            "exp": int(time.time()) - 5, "name": "Ghost", "email": "g@x.com",
            "loc": "", "idle": False,
        }),
    )
    assert await presence_store.roster("ace:ws:p") == []
    assert await fake_redis.hget(key, "9.dead") is None


@pytest.mark.asyncio
async def test_touch_sets_a_key_level_ttl(fake_redis):
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=False,
    )
    assert 0 < await fake_redis.ttl("presence:ace:ws:p") <= presence_store.KEY_TTL_SECONDS


@pytest.mark.asyncio
async def test_idle_flag_round_trips(fake_redis):
    await presence_store.touch(
        "ace:ws:p", user_id=7, connection_id="c1", name="A", email="a@x.com",
        sub_location="", idle=True,
    )
    assert (await presence_store.roster("ace:ws:p"))[0]["idle"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_presence_store.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.realtime.presence_keys`.

- [ ] **Step 3: Write the implementations**

```python
# apps/realtime/presence_keys.py
"""Page-key parsing and Channels group naming for presence.

Pure functions — no Redis, no async — so they unit-test without any
infrastructure. Page keys arrive from the client and are therefore parsed
defensively: anything that is not exactly `<app>:<workspace>:<resource>`
is rejected rather than coerced.
"""
from __future__ import annotations

import hashlib


def parse_page_key(page_key: str) -> tuple[str, str, str] | None:
    """Split `<app>:<workspace>:<resource>` into its three parts.

    The resource may itself contain colons (`opp:bednet/run-001`), so the
    split is bounded to 2. Returns None for anything malformed — callers
    MUST treat None as "reject this frame", never as "use a default".
    """
    if not page_key:
        return None
    parts = page_key.split(":", 2)
    if len(parts) != 3:
        return None
    app, workspace, resource = (p.strip() for p in parts)
    if not app or not workspace or not resource:
        return None
    return app, workspace, resource


def group_name(page_key: str) -> str:
    """A Channels-legal group name for a page key.

    Channels group names permit only ASCII alphanumerics, hyphens, periods
    and underscores (max 100 chars). Page keys contain ':' and '/', so the
    key is hashed rather than sanitised — sanitising would let two distinct
    keys collide onto one group.
    """
    digest = hashlib.sha1(page_key.encode("utf-8")).hexdigest()[:32]
    return f"presence.{digest}"
```

```python
# apps/realtime/presence_store.py
"""Redis-backed viewer presence: one HASH per page key.

Schema
------
    key    presence:<page_key>              key-level TTL 120s
    field  <user_id>.<connection_id>        per-connection, NOT per-user
    value  {"exp": <epoch>, "name", "email", "loc", "idle"}

Fields are per-connection so that a user with two tabs open on the same
page who closes one is not evicted from their own surviving tab's roster.
The reader dedupes by user id.

Values are denormalised (name and email inline) so building a roster costs
zero database queries.

The key-level TTL is leak insurance: if every client disconnects
ungracefully the hash self-destructs within two minutes rather than
lingering forever.
"""
from __future__ import annotations

import json
import time

from apps.common import redis_client  # module import — keeps monkeypatch working

FIELD_TTL_SECONDS = 60
KEY_TTL_SECONDS = 120


def _key(page_key: str) -> str:
    return f"presence:{page_key}"


def _field(user_id: int, connection_id: str) -> str:
    return f"{user_id}.{connection_id}"


async def touch(
    page_key: str,
    *,
    user_id: int,
    connection_id: str,
    name: str,
    email: str,
    sub_location: str,
    idle: bool,
) -> None:
    """Write/refresh this connection's presence on a page."""
    redis = await redis_client.get_redis()
    payload = json.dumps({
        "exp": int(time.time()) + FIELD_TTL_SECONDS,
        "name": name,
        "email": email,
        "loc": sub_location,
        "idle": bool(idle),
    })
    pipe = redis.pipeline()
    pipe.hset(_key(page_key), _field(user_id, connection_id), payload)
    pipe.expire(_key(page_key), KEY_TTL_SECONDS)
    await pipe.execute()


async def forget(page_key: str, *, user_id: int, connection_id: str) -> None:
    """Remove exactly one connection. Other tabs of the same user survive."""
    redis = await redis_client.get_redis()
    await redis.hdel(_key(page_key), _field(user_id, connection_id))


async def roster(page_key: str) -> list[dict]:
    """Current viewers, deduped by user, with a lazy sweep of expired fields.

    Known race (carried over from docs/learnings/redis-presence-hash.md): a
    concurrent touch during the read-then-HDEL window can evict a freshly
    refreshed entry. Self-heals on the next heartbeat; accepted.
    """
    redis = await redis_client.get_redis()
    raw = await redis.hgetall(_key(page_key))
    now = int(time.time())

    stale: list[str] = []
    by_user: dict[int, dict] = {}
    for field, value in (raw or {}).items():
        try:
            data = json.loads(value)
            user_id = int(str(field).split(".", 1)[0])
        except (ValueError, TypeError):
            stale.append(field)
            continue
        if int(data.get("exp", 0)) <= now:
            stale.append(field)
            continue
        entry = {
            "user_id": user_id,
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "sub_location": data.get("loc", ""),
            "idle": bool(data.get("idle")),
        }
        existing = by_user.get(user_id)
        # A user is idle only when EVERY one of their connections is idle:
        # one active tab means they are here.
        if existing is None:
            by_user[user_id] = entry
        elif not entry["idle"]:
            by_user[user_id] = entry

    if stale:
        await redis.hdel(_key(page_key), *stale)

    return sorted(by_user.values(), key=lambda e: (e["name"] or e["email"]).lower())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_presence_store.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check apps/realtime/ tests/test_presence_store.py
git add apps/realtime/presence_keys.py apps/realtime/presence_store.py tests/test_presence_store.py
git commit -m "feat(presence): Redis presence store and page-key parsing"
```

---

### Task 6: canopy-web — `PresencePreference` model

**Files:**
- Modify: `apps/realtime/models.py` (create the file if the app has none)
- Create: `apps/realtime/migrations/` (if absent) + the generated migration
- Test: `tests/test_presence_preference.py`

**Interfaces:**
- Consumes: `settings.AUTH_USER_MODEL`.
- Produces:
  ```python
  class PresencePreference(models.Model):
      user: OneToOneField          # related_name="presence_preference"
      show_presence: BooleanField  # default True
  def show_presence_for(user) -> bool   # module-level helper, defaults True
  ```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presence_preference.py
import pytest
from django.contrib.auth import get_user_model

from apps.realtime.models import PresencePreference, show_presence_for

pytestmark = pytest.mark.django_db


def _user(email="a@x.com"):
    return get_user_model().objects.create_user(username=email, email=email)


def test_defaults_to_visible_when_no_row_exists():
    assert show_presence_for(_user()) is True


def test_honours_an_explicit_opt_out():
    user = _user()
    PresencePreference.objects.create(user=user, show_presence=False)
    assert show_presence_for(user) is False


def test_a_user_has_at_most_one_preference_row():
    user = _user()
    PresencePreference.objects.create(user=user, show_presence=False)
    with pytest.raises(Exception):
        PresencePreference.objects.create(user=user, show_presence=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_presence_preference.py -v`
Expected: FAIL — `ImportError: cannot import name 'PresencePreference'`.

- [ ] **Step 3: Write the model**

```python
# apps/realtime/models.py
"""Per-user presence preference.

A dedicated model rather than a field on the user: canopy-web uses Django's
stock auth.User, which we do not extend. ace-web mirrors this model exactly
so the two backends stay symmetric.

Absence of a row means visible — the feature is on by default, and we do not
want a backfill migration to be load-bearing for correctness.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class PresencePreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="presence_preference",
    )
    show_presence = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "presence_preferences"

    def __str__(self):
        return f"{self.user_id}: show_presence={self.show_presence}"


def show_presence_for(user) -> bool:
    """Whether this user should be written into rosters. Defaults to True."""
    pref = PresencePreference.objects.filter(user=user).first()
    return True if pref is None else pref.show_presence
```

- [ ] **Step 4: Generate and run the migration**

```bash
uv run python manage.py makemigrations realtime
uv run pytest tests/test_presence_preference.py -v
```

Expected: migration created; 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/realtime/models.py apps/realtime/migrations/ tests/test_presence_preference.py
git commit -m "feat(presence): PresencePreference model, visible by default"
```

---

### Task 7: canopy-web — `PresenceConsumer` + routing

**Files:**
- Create: `apps/realtime/presence_consumer.py`
- Modify: `apps/realtime/routing.py`
- Test: `tests/test_presence_consumer.py`

**Interfaces:**
- Consumes: `presence_keys.parse_page_key`, `presence_keys.group_name` (Task 5); `presence_store.touch/forget/roster` (Task 5); `models.show_presence_for` (Task 6); `apps.workspaces.services.user_workspace_slugs`.
- Produces: `PresenceConsumer` mounted at `ws/presence/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presence_consumer.py
import fakeredis.aioredis
import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from apps.realtime.presence_consumer import PresenceConsumer

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_redis():
        return client

    monkeypatch.setattr("apps.common.redis_client.get_redis", _get_redis)
    return client


async def _connect(user):
    communicator = WebsocketCommunicator(PresenceConsumer.as_asgi(), "/ws/presence/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    return communicator, connected


@pytest.mark.asyncio
async def test_anonymous_is_rejected():
    from django.contrib.auth.models import AnonymousUser

    communicator, connected = await _connect(AnonymousUser())
    assert connected is False
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_entering_a_page_broadcasts_a_roster_containing_you(member_user):
    communicator, connected = await _connect(member_user)
    assert connected
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "canopy:test-ws:opp:a/run-001",
        "sub_location": "run overview",
    })
    message = await communicator.receive_json_from(timeout=2)
    assert message["event"] == "presence.roster"
    assert message["data"]["page_key"] == "canopy:test-ws:opp:a/run-001"
    assert [v["email"] for v in message["data"]["viewers"]] == [member_user.email]
    assert message["data"]["viewers"][0]["self"] is True
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_a_foreign_workspace_key_is_silently_rejected(member_user):
    """Membership is checked server-side — the page key is client-supplied."""
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "canopy:someone-elses-workspace:opp:secret/run-001",
        "sub_location": "",
    })
    assert await communicator.receive_nothing(timeout=1)
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_a_malformed_page_key_is_silently_rejected(member_user):
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({"type": "presence.enter", "page_key": "junk", "sub_location": ""})
    assert await communicator.receive_nothing(timeout=1)
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_an_opted_out_user_receives_rosters_but_is_absent_from_them(member_user):
    from apps.realtime.models import PresencePreference

    await _acreate_pref(member_user)
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "canopy:test-ws:activity",
        "sub_location": "Activity",
    })
    message = await communicator.receive_json_from(timeout=2)
    assert message["event"] == "presence.roster"
    assert message["data"]["viewers"] == []
    await communicator.disconnect()
    assert PresencePreference.objects.filter(user=member_user).exists()


@pytest.mark.asyncio
async def test_disconnect_removes_the_viewer(member_user, fake_redis):
    communicator, _ = await _connect(member_user)
    await communicator.send_json_to({
        "type": "presence.enter",
        "page_key": "canopy:test-ws:activity",
        "sub_location": "Activity",
    })
    await communicator.receive_json_from(timeout=2)
    await communicator.disconnect()

    from apps.realtime import presence_store

    assert await presence_store.roster("canopy:test-ws:activity") == []
```

Add these fixtures and helper to the same file:

```python
from asgiref.sync import sync_to_async


@pytest.fixture
def member_user(db):
    """A user who is a member of the workspace slug 'test-ws'."""
    from apps.workspaces.models import Workspace

    User = get_user_model()
    user = User.objects.create_user(username="m@x.com", email="m@x.com")
    workspace, _ = Workspace.objects.get_or_create(pk="test-ws", defaults={"name": "Test WS"})
    workspace.members.add(user)
    return user


@sync_to_async
def _acreate_pref(user):
    from apps.realtime.models import PresencePreference

    PresencePreference.objects.create(user=user, show_presence=False)
```

> Before running: confirm the workspace-membership API. Run
> `git grep -n "def user_workspace_slugs" -A 12 -- apps/workspaces/services.py`
> and adjust the `member_user` fixture to whatever `user_workspace_slugs`
> actually reads (an M2M `members`, a through model, or a membership table).
> The fixture must make `user_workspace_slugs(user)` return `{"test-ws"}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_presence_consumer.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.realtime.presence_consumer`.

- [ ] **Step 3: Write the consumer**

```python
# apps/realtime/presence_consumer.py
"""Viewer presence over WebSocket: one socket per browser tab.

Navigation re-keys the connection with a fresh `presence.enter` rather than
reconnecting.

Two rules carry the security weight of this surface:

1. The page key is CLIENT-SUPPLIED. Its workspace segment is checked against
   the user's memberships before any group is joined — otherwise a user
   could observe who is viewing a workspace they cannot access.
2. Visibility is enforced HERE, not on the client. An opted-out user joins
   the group (so they still see others) but is never written to Redis, so
   no client — tampered, stale, or otherwise — can expose them.
"""
from __future__ import annotations

import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.workspaces.services import user_workspace_slugs

from . import presence_keys, presence_store
from .models import show_presence_for

GLOBAL_WORKSPACE = "global"


class PresenceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            await self.close(code=4001)
            return
        self.user = user
        self.connection_id = uuid.uuid4().hex
        self.page_key: str | None = None
        self.group: str | None = None
        self.sub_location = ""
        self.visible = await database_sync_to_async(show_presence_for)(user)
        self.workspaces = await database_sync_to_async(lambda: set(user_workspace_slugs(user)))()
        await self.accept()

    async def disconnect(self, code):
        await self._leave_current()

    async def receive_json(self, content, **kwargs):
        message_type = content.get("type", "")
        if message_type == "presence.enter":
            await self._enter(content)
        elif message_type == "presence.heartbeat":
            await self._heartbeat(content)

    # -- frame handlers --

    async def _enter(self, content):
        page_key = str(content.get("page_key") or "")
        sub_location = str(content.get("sub_location") or "")[:120]

        parsed = presence_keys.parse_page_key(page_key)
        if parsed is None:
            return  # malformed — drop silently, never confirm key shapes
        _app, workspace, _resource = parsed
        if workspace != GLOBAL_WORKSPACE and workspace not in self.workspaces:
            return  # not a member — drop silently, no existence leak

        if page_key != self.page_key:
            await self._leave_current()
            self.page_key = page_key
            self.group = presence_keys.group_name(page_key)
            await self.channel_layer.group_add(self.group, self.channel_name)

        self.sub_location = sub_location
        await self._write()
        await self._broadcast()

    async def _heartbeat(self, content):
        if self.page_key is None:
            return
        self.idle = bool(content.get("idle"))
        await self._write()
        # Only an idle transition changes what others see; a plain keepalive
        # does not need a broadcast.
        if self.idle != getattr(self, "_last_broadcast_idle", None):
            self._last_broadcast_idle = self.idle
            await self._broadcast()

    # -- helpers --

    async def _write(self):
        if not self.visible or self.page_key is None:
            return
        await presence_store.touch(
            self.page_key,
            user_id=self.user.id,
            connection_id=self.connection_id,
            name=getattr(self.user, "get_full_name", lambda: "")() or self.user.username,
            email=self.user.email or "",
            sub_location=self.sub_location,
            idle=bool(getattr(self, "idle", False)),
        )

    async def _leave_current(self):
        if self.group is None or self.page_key is None:
            return
        if self.visible:
            await presence_store.forget(
                self.page_key, user_id=self.user.id, connection_id=self.connection_id
            )
        group, page_key = self.group, self.page_key
        await self.channel_layer.group_discard(group, self.channel_name)
        self.group, self.page_key = None, None
        await self.channel_layer.group_send(
            group, {"type": "presence.roster_changed", "page_key": page_key}
        )

    async def _broadcast(self):
        if self.group is None:
            return
        await self.channel_layer.group_send(
            self.group, {"type": "presence.roster_changed", "page_key": self.page_key}
        )

    async def presence_roster_changed(self, event):
        """Every connection recomputes the roster itself.

        The `self` flag is per-recipient, so a single pre-rendered payload
        cannot be shared across the group. At tens of viewers per page the
        extra Redis reads are cheaper than the bookkeeping to avoid them.
        """
        page_key = event.get("page_key")
        if page_key != self.page_key:
            return
        viewers = await presence_store.roster(page_key)
        await self.send_json({
            "event": "presence.roster",
            "data": {
                "page_key": page_key,
                "viewers": [
                    {
                        "email": v["email"],
                        "name": v["name"],
                        "sub_location": v["sub_location"],
                        "idle": v["idle"],
                        "self": v["user_id"] == self.user.id,
                    }
                    for v in viewers
                ],
            },
        })
```

- [ ] **Step 4: Register the route**

In `apps/realtime/routing.py`, add the import and the pattern:

```python
from .presence_consumer import PresenceConsumer

websocket_urlpatterns = [
    # ... existing turn / supervisor / runner routes unchanged ...
    path("ws/presence/", PresenceConsumer.as_asgi()),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_presence_consumer.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Run the full backend suite for regressions**

Run: `uv run pytest -q && uv run ruff check apps/realtime/ tests/`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add apps/realtime/presence_consumer.py apps/realtime/routing.py tests/test_presence_consumer.py
git commit -m "feat(presence): PresenceConsumer with membership and visibility gates"
```

---

### Task 8: canopy-web — preference API, settings toggle, and mount the badge

**Files:**
- Modify: `apps/common/api.py` (or wherever the `/me` router lives — confirm with the grep in Step 1)
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/components/AppLayout/AppLayout.tsx`
- Create: `frontend/src/presence/routes.ts`
- Test: `tests/test_presence_api.py`

**Interfaces:**
- Consumes: `PresencePreference`, `show_presence_for` (Task 6); `pageKeyFor`, `usePresence`, `PresenceBadge` from `canopy-ui/presence` (Tasks 1–4).
- Produces: `GET/PATCH /api/me/presence-preference` returning `{"show_presence": bool}`; `canopyPresenceRules: RouteRule[]`.

- [ ] **Step 1: Locate the `/me` router**

```bash
git grep -n "\"/me\"\|/me/" -- apps/common/api.py apps/api/ | head
```

Register the two endpoints on that same router so they inherit its auth.

- [ ] **Step 2: Write the failing API test**

```python
# tests/test_presence_api.py
import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(client):
    u = get_user_model().objects.create_user(username="p@x.com", email="p@x.com")
    client.force_login(u)
    return u


def test_defaults_to_visible(client, user):
    response = client.get("/api/me/presence-preference")
    assert response.status_code == 200
    assert response.json() == {"show_presence": True}


def test_opting_out_persists(client, user):
    patch = client.patch(
        "/api/me/presence-preference",
        data={"show_presence": False},
        content_type="application/json",
    )
    assert patch.status_code == 200
    assert patch.json() == {"show_presence": False}
    assert client.get("/api/me/presence-preference").json() == {"show_presence": False}


def test_opting_back_in_persists(client, user):
    client.patch("/api/me/presence-preference", data={"show_presence": False},
                 content_type="application/json")
    client.patch("/api/me/presence-preference", data={"show_presence": True},
                 content_type="application/json")
    assert client.get("/api/me/presence-preference").json() == {"show_presence": True}


def test_requires_authentication(client):
    assert client.get("/api/me/presence-preference").status_code in (401, 403)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_presence_api.py -v`
Expected: FAIL — 404 on the endpoint.

- [ ] **Step 4: Implement the endpoints**

```python
# in the module that owns the /me router
from ninja import Schema

from apps.realtime.models import PresencePreference, show_presence_for


class PresencePreferenceOut(Schema):
    show_presence: bool


class PresencePreferenceIn(Schema):
    show_presence: bool


@router.get("/me/presence-preference", response=PresencePreferenceOut)
def get_presence_preference(request):
    return {"show_presence": show_presence_for(request.user)}


@router.patch("/me/presence-preference", response=PresencePreferenceOut)
def set_presence_preference(request, payload: PresencePreferenceIn):
    PresencePreference.objects.update_or_create(
        user=request.user, defaults={"show_presence": payload.show_presence}
    )
    return {"show_presence": payload.show_presence}
```

- [ ] **Step 5: Run the API test to verify it passes**

Run: `uv run pytest tests/test_presence_api.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Add the canopy route table**

```ts
// frontend/src/presence/routes.ts
import type { RouteRule } from 'canopy-ui/presence'

/**
 * canopy-web's route table for presence grouping.
 *
 * Order matters — the first match wins, so specific patterns come first.
 * Routes with no rule here simply get no badge, which is the safe default.
 */
export const canopyPresenceRules: RouteRule[] = [
  {
    pattern: /^\/w\/([^/]+)\/chat\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `session:${m[2]}`, subLocation: 'Chat' }),
  },
  {
    pattern: /^\/w\/([^/]+)\/agents\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `agent:${m[2]}`, subLocation: 'Agent' }),
  },
  {
    pattern: /^\/w\/([^/]+)\/([a-z-]+)/,
    build: (m) => ({ workspace: m[1], resource: m[2], subLocation: m[2] }),
  },
]
```

> Confirm these against canopy's actual router before committing:
> `git grep -n "path=\"" -- frontend/src/router.tsx | head -40`
> Add a rule for every top-level surface; delete rules whose routes do not exist.

- [ ] **Step 7: Mount the badge in the app shell**

In `frontend/src/components/AppLayout/AppLayout.tsx`, add to the header's right-hand cluster:

```tsx
import { useLocation } from 'react-router-dom'
import { PresenceBadge, pageKeyFor, usePresence } from 'canopy-ui/presence'
import { canopyPresenceRules } from '@/presence/routes'

// inside the component:
const { pathname } = useLocation()
const location = pageKeyFor('canopy', pathname, canopyPresenceRules)
const { viewers } = usePresence({
  url: `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${
    (import.meta.env.BASE_URL ?? '/').replace(/\/$/, '')
  }/ws/presence/`,
  location,
})

// in the header JSX, immediately before the account menu:
<PresenceBadge viewers={viewers} />
```

- [ ] **Step 8: Add the Settings toggle**

In `frontend/src/pages/SettingsPage.tsx`, add a row that `GET`s `/api/me/presence-preference` on mount and `PATCH`es on change:

```tsx
const [showPresence, setShowPresence] = useState(true)

useEffect(() => {
  fetch('/api/me/presence-preference')
    .then((r) => r.json())
    .then((d) => setShowPresence(d.show_presence))
    .catch(() => {})
}, [])

const togglePresence = async (next: boolean) => {
  setShowPresence(next)
  await fetch('/api/me/presence-preference', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ show_presence: next }),
  })
}

// JSX:
<label className="flex items-center gap-2">
  <input type="checkbox" checked={showPresence} onChange={(e) => togglePresence(e.target.checked)} />
  <span>Show me as viewing</span>
  <span className="text-xs text-muted-foreground">
    When off, you can still see who else is viewing a page, but they cannot see you.
  </span>
</label>
```

> Match the existing toggle markup on that page rather than this raw
> checkbox if one exists — `git grep -n "type=\"checkbox\"\|Switch" -- frontend/src/pages/SettingsPage.tsx`.

- [ ] **Step 9: Verify the frontend builds and tests pass**

Run: `cd frontend && npm run test && npm run build`
Expected: all tests pass; `tsc -b` clean.

- [ ] **Step 10: Commit and open the canopy-web PR**

```bash
git add apps/ frontend/src/presence/ frontend/src/components/AppLayout/AppLayout.tsx \
        frontend/src/pages/SettingsPage.tsx tests/test_presence_api.py
git commit -m "feat(presence): preference API, settings toggle, badge in app shell"
```

Open the PR. Do not merge to `main` directly.

---

### Task 9: Publish canopy-ui

**Files:**
- Modify: `frontend/packages/canopy-ui/package.json` (version bump)

Blocked on Task 8's PR merging.

- [ ] **Step 1: Bump the minor version**

In `frontend/packages/canopy-ui/package.json`, change `"version": "0.5.0"` to `"version": "0.6.0"`. A new subpath export is an additive feature, so minor is correct.

- [ ] **Step 2: Verify the package builds standalone**

Run: `cd frontend && npm run build`
Expected: clean.

- [ ] **Step 3: Publish**

```bash
cd frontend/packages/canopy-ui && npm publish --access public
```

- [ ] **Step 4: Confirm the published version resolves**

Run: `npm view canopy-ui@0.6.0 version`
Expected: prints `0.6.0`.

- [ ] **Step 5: Commit the bump**

```bash
git add frontend/packages/canopy-ui/package.json
git commit -m "chore(canopy-ui): 0.6.0 — add presence subpath"
```

---

### Task 10: ace-web — presence app, store, and keys

**Files:**
- Create: `apps/presence/__init__.py`, `apps/presence/apps.py`, `apps/presence/keys.py`, `apps/presence/store.py`
- Modify: `config/settings/base.py:46-58` (INSTALLED_APPS)
- Test: `apps/presence/tests/__init__.py`, `apps/presence/tests/test_store.py`

**Interfaces:**
- Consumes: `apps.common.redis_client.get_redis`.
- Produces: identical surface to canopy's Task 5 — `keys.parse_page_key`, `keys.group_name`, `store.touch/forget/roster`, `store.FIELD_TTL_SECONDS`, `store.KEY_TTL_SECONDS`.

- [ ] **Step 1: Provision the venv if this worktree has none**

```bash
uv venv --python=3.11 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

- [ ] **Step 2: Create the app skeleton**

```python
# apps/presence/__init__.py
```

```python
# apps/presence/apps.py
from django.apps import AppConfig


class PresenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.presence"
    label = "presence"
```

Add to `INSTALLED_APPS` in `config/settings/base.py`, after `"apps.canopy",`:

```python
    "apps.presence.apps.PresenceConfig",
```

- [ ] **Step 3: Write the failing test**

Copy `tests/test_presence_store.py` from canopy Task 5 verbatim into
`apps/presence/tests/test_store.py`, changing only the imports:

```python
from apps.presence import keys as presence_keys
from apps.presence import store as presence_store
```

and the page-key fixtures from `canopy:` to `ace:` prefixes. Also create an
empty `apps/presence/tests/__init__.py`.

- [ ] **Step 4: Run it to verify it fails**

Run: `.venv/bin/pytest apps/presence/tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.presence.keys`.

- [ ] **Step 5: Write the implementations**

Copy `apps/realtime/presence_keys.py` → `apps/presence/keys.py` and
`apps/realtime/presence_store.py` → `apps/presence/store.py` from canopy Task 5
verbatim. Both files are app-agnostic: they import only `apps.common.redis_client`,
which exists in ace-web with the identical `get_redis()` signature.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/presence/tests/test_store.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check apps/presence/
git add apps/presence/ config/settings/base.py
git commit -m "feat(presence): ace-web presence app with Redis store"
```

---

### Task 11: ace-web — preference model, consumer, and API

**Files:**
- Create: `apps/presence/models.py`, `apps/presence/consumers.py`, `apps/presence/routing.py`, `apps/presence/api.py`
- Create: `apps/presence/migrations/__init__.py` + generated migration
- Modify: `config/asgi.py:37-42`, `apps/api/api.py:173`
- Test: `apps/presence/tests/test_consumer.py`, `apps/presence/tests/test_api.py`

**Interfaces:**
- Consumes: `apps.presence.keys`, `apps.presence.store` (Task 10); `apps.workspaces.permissions.is_member`; `apps.workspaces.models.Workspace`.
- Produces: `PresenceConsumer` at `ws/presence/`; `GET/PATCH /api/me/presence-preference`.

- [ ] **Step 1: Write the model**

Copy canopy's `apps/realtime/models.py` (Task 6) verbatim to `apps/presence/models.py`. It references `settings.AUTH_USER_MODEL`, which resolves to `ace_auth.User` here with no change.

Create `apps/presence/migrations/__init__.py`, then:

```bash
.venv/bin/python manage.py makemigrations presence
```

- [ ] **Step 2: Write the failing consumer test**

Copy canopy's `tests/test_presence_consumer.py` (Task 7) to
`apps/presence/tests/test_consumer.py` with these ace-web adaptations:

```python
from apps.presence.consumers import PresenceConsumer
from apps.presence.models import PresencePreference


@pytest.fixture
def member_user(db):
    from apps.workspaces.models import Workspace, WorkspaceMembership

    User = get_user_model()
    user = User.objects.create_user(email="m@x.com", password="x")
    workspace = Workspace.objects.create(pk="test-ws", name="Test WS")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    return user
```

Change every `canopy:` page-key prefix to `ace:`.

> Confirm the membership model's field names first:
> `.venv/bin/python -c "from apps.workspaces.models import WorkspaceMembership as M; print([f.name for f in M._meta.get_fields()])"`

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/pytest apps/presence/tests/test_consumer.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.presence.consumers`.

- [ ] **Step 4: Write the consumer**

Copy canopy's `apps/realtime/presence_consumer.py` (Task 7) to
`apps/presence/consumers.py` with three changes — ace-web has no
`user_workspace_slugs` helper, so membership resolves through
`apps.workspaces.permissions.is_member`, and ace-web's `User` has
`display_name` rather than `get_full_name()`:

```python
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member

from . import keys as presence_keys
from . import store as presence_store
from .models import show_presence_for
```

Replace the `connect()` workspace preload with a per-key check, since ace-web
has no cheap "all my slugs" call:

```python
    async def connect(self):
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            await self.close(code=4001)
            return
        self.user = user
        self.connection_id = uuid.uuid4().hex
        self.page_key = None
        self.group = None
        self.sub_location = ""
        self.visible = await database_sync_to_async(show_presence_for)(user)
        self._workspace_cache: dict[str, bool] = {}
        await self.accept()

    @database_sync_to_async
    def _can_view_workspace(self, slug: str) -> bool:
        workspace = Workspace.objects.filter(pk=slug).first()
        return bool(workspace and is_member(self.user, workspace))

    async def _member_of(self, slug: str) -> bool:
        # Cached per connection: a navigating user re-enters often, and
        # membership does not change mid-socket in any way we must honour.
        if slug not in self._workspace_cache:
            self._workspace_cache[slug] = await self._can_view_workspace(slug)
        return self._workspace_cache[slug]
```

and in `_enter`, replace the membership line with:

```python
        if workspace != GLOBAL_WORKSPACE and not await self._member_of(workspace):
            return
```

and in `_write`, replace the name expression with:

```python
            name=getattr(self.user, "display_name", "") or self.user.email,
```

- [ ] **Step 5: Add routing and ASGI wiring**

```python
# apps/presence/routing.py
"""WebSocket routing for viewer presence."""
from django.urls import path

from .consumers import PresenceConsumer

websocket_urlpatterns = [
    path("ws/presence/", PresenceConsumer.as_asgi()),
]
```

In `config/asgi.py`, add the import beside the opps one and extend the pattern list:

```python
from apps.presence.routing import websocket_urlpatterns as presence_ws_urlpatterns  # noqa: E402

websocket_urlpatterns = opps_ws_urlpatterns + presence_ws_urlpatterns
```

- [ ] **Step 6: Run the consumer test to verify it passes**

Run: `.venv/bin/pytest apps/presence/tests/test_consumer.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 7: Write the failing API test, then the endpoints**

Copy canopy's `tests/test_presence_api.py` (Task 8) to
`apps/presence/tests/test_api.py`, changing user creation to
`get_user_model().objects.create_user(email="p@x.com", password="x")`.

Then create the router:

```python
# apps/presence/api.py
"""Per-user presence preference."""
from __future__ import annotations

from ninja import Router, Schema

from .models import PresencePreference, show_presence_for

router = Router(tags=["presence"])


class PresencePreferenceOut(Schema):
    show_presence: bool


class PresencePreferenceIn(Schema):
    show_presence: bool


@router.get("/me/presence-preference", response=PresencePreferenceOut)
def get_presence_preference(request):
    return {"show_presence": show_presence_for(request.user)}


@router.patch("/me/presence-preference", response=PresencePreferenceOut)
def set_presence_preference(request, payload: PresencePreferenceIn):
    PresencePreference.objects.update_or_create(
        user=request.user, defaults={"show_presence": payload.show_presence}
    )
    return {"show_presence": payload.show_presence}
```

Register it in `apps/api/api.py` next to the other root-level routers (near line 173):

```python
from apps.presence.api import router as presence_router
...
api.add_router("", presence_router)
```

- [ ] **Step 8: Run the API test and the full suite**

Run: `.venv/bin/pytest apps/presence/ -v && .venv/bin/pytest -q && .venv/bin/ruff check apps/presence/ config/`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add apps/presence/ config/asgi.py apps/api/api.py
git commit -m "feat(presence): ace-web consumer, preference model, and API"
```

---

### Task 12: ace-web — route table, TopNav mount, settings toggle

**Files:**
- Create: `frontend/src/presence/routes.ts`
- Create: `frontend/src/presence/__tests__/routes.test.ts`
- Modify: `frontend/package.json:18` (canopy-ui pin)
- Modify: `frontend/src/components/TopNav.tsx:59-62`
- Modify: `frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Consumes: `pageKeyFor`, `usePresence`, `PresenceBadge`, `RouteRule` from `canopy-ui/presence` (Task 9's published 0.6.0); `wsUrl` from `@/lib/wsUrl`.
- Produces: `acePresenceRules: RouteRule[]`.

- [ ] **Step 1: Bump the canopy-ui pin**

In `frontend/package.json`, change `"canopy-ui": "0.4.0"` to `"canopy-ui": "0.6.0"`, then:

```bash
cd frontend && bun install
```

- [ ] **Step 2: Write the failing route-table test**

```ts
// frontend/src/presence/__tests__/routes.test.ts
import { describe, expect, it } from "vitest";
import { pageKeyFor } from "canopy-ui/presence";

import { acePresenceRules } from "../routes";

const key = (path: string) => pageKeyFor("ace", path, acePresenceRules);

describe("acePresenceRules", () => {
  it("groups every step of a run onto the run's key", () => {
    const step = key("/w/dimagi-team/opps/bednet/runs/run-001/steps/idea-to-pdd");
    const run = key("/w/dimagi-team/opps/bednet/runs/run-001");
    expect(step?.pageKey).toBe("ace:dimagi-team:opp:bednet/run-001");
    expect(step?.pageKey).toBe(run?.pageKey);
    expect(step?.subLocation).toBe("idea-to-pdd");
  });

  it("keeps a run-less opp separate from its runs", () => {
    expect(key("/w/dimagi-team/opps/bednet")?.pageKey).toBe("ace:dimagi-team:opp:bednet");
  });

  it("groups a video program run", () => {
    expect(key("/w/dimagi-team/videos/promo/runs/run-003")?.pageKey).toBe(
      "ace:dimagi-team:video:promo/run-003",
    );
  });

  it("gives list pages their own keys", () => {
    expect(key("/w/dimagi-team/opps")?.pageKey).toBe("ace:dimagi-team:opps");
    expect(key("/w/dimagi-team/activity")?.pageKey).toBe("ace:dimagi-team:activity");
    expect(key("/w/dimagi-team/videos")?.pageKey).toBe("ace:dimagi-team:videos");
  });

  it("puts workspace-agnostic pages in the global namespace", () => {
    expect(key("/settings")?.pageKey).toBe("ace:global:settings");
    expect(key("/system")?.pageKey).toBe("ace:global:system");
  });

  it("returns null for routes with no rule", () => {
    expect(key("/invite/abc123")).toBeNull();
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && bun run test src/presence/__tests__/routes.test.ts`
Expected: FAIL — cannot resolve `../routes`.

- [ ] **Step 4: Write the route table**

```ts
// frontend/src/presence/routes.ts
import type { RouteRule } from "canopy-ui/presence";

/**
 * ace-web's route table for presence grouping.
 *
 * Order matters — the first match wins, so the most specific patterns come
 * first. Every step of a run deliberately collapses onto the run's key: the
 * whole point is that two people working the same run find each other even
 * when they are on different steps.
 *
 * Routes with no rule (invite acceptance, the public summary page, auth
 * callbacks) get no badge, which is the correct default for pages where a
 * viewer list would be meaningless or unwelcome.
 */
export const acePresenceRules: RouteRule[] = [
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)\/runs\/([^/]+)\/steps\/([^/]+)/,
    build: (m) => ({
      workspace: m[1],
      resource: `opp:${m[2]}/${m[3]}`,
      subLocation: decodeURIComponent(m[4]),
    }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)\/runs\/([^/]+)/,
    build: (m) => ({
      workspace: m[1],
      resource: `opp:${m[2]}/${m[3]}`,
      subLocation: "run overview",
    }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/compare\/([^/]+)\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `compare:${m[2]}/${m[3]}`, subLocation: "Compare" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `opp:${m[2]}`, subLocation: "Opp" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps/,
    build: (m) => ({ workspace: m[1], resource: "opps", subLocation: "Opps" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos\/templates\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `template:${m[2]}`, subLocation: "Template" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos\/([^/]+)\/runs\/([^/]+)/,
    build: (m) => ({
      workspace: m[1],
      resource: `video:${m[2]}/${m[3]}`,
      subLocation: "Beat editor",
    }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos\/(library|templates)/,
    build: (m) => ({ workspace: m[1], resource: `videos-${m[2]}`, subLocation: m[2] }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `video:${m[2]}`, subLocation: "Program" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos/,
    build: (m) => ({ workspace: m[1], resource: "videos", subLocation: "Videos" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/chat\/([^/]+)\/structure/,
    build: (m) => ({ workspace: m[1], resource: `session:${m[2]}`, subLocation: "Structure" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/chat\/c\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `chat:${m[2]}`, subLocation: "Chat" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/activity/,
    build: (m) => ({ workspace: m[1], resource: "activity", subLocation: "Activity" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/sessions/,
    build: (m) => ({ workspace: m[1], resource: "sessions", subLocation: "Sessions" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/workspace-settings/,
    build: (m) => ({
      workspace: m[1],
      resource: "workspace-settings",
      subLocation: "Workspace settings",
    }),
  },
  {
    pattern: /^\/settings/,
    build: () => ({ workspace: "global", resource: "settings", subLocation: "Settings" }),
  },
  {
    pattern: /^\/system/,
    build: () => ({ workspace: "global", resource: "system", subLocation: "System" }),
  },
];
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && bun run test src/presence/__tests__/routes.test.ts`
Expected: PASS, 6 tests.

- [ ] **Step 6: Mount the badge in TopNav**

In `frontend/src/components/TopNav.tsx`, add the imports:

```tsx
import { PresenceBadge, pageKeyFor, usePresence } from "canopy-ui/presence";

import { acePresenceRules } from "@/presence/routes";
import { wsUrl } from "@/lib/wsUrl";
```

Inside the component, after the existing `const { pathname } = useLocation();`:

```tsx
  const presenceLocation = pageKeyFor("ace", pathname, acePresenceRules);
  const { viewers } = usePresence({ url: wsUrl("ws/presence/"), location: presenceLocation });
```

Then in the right-hand utility cluster (`frontend/src/components/TopNav.tsx:59-62`),
place the badge before the workspace switcher:

```tsx
      <div className="ml-auto flex items-center gap-4">
        <PresenceBadge viewers={viewers} />
        <WorkspaceSwitcher />
        <UserMenu />
      </div>
```

Note: `PresenceBadge` renders a `<button>`. Do not wrap it in a `<Link>` —
see `docs/learnings/card-click-and-grid-stretch.md`.

- [ ] **Step 7: Add the Settings toggle**

In `frontend/src/pages/SettingsPage.tsx`, following the existing
`load`/`useEffect` pattern already in that file:

```tsx
const [showPresence, setShowPresence] = useState(true);

useEffect(() => {
  fetch(`${(import.meta.env.BASE_URL ?? "/").replace(/\/$/, "")}/api/me/presence-preference`)
    .then((r) => r.json())
    .then((d) => setShowPresence(Boolean(d.show_presence)))
    .catch(() => {});
}, []);

const togglePresence = async (next: boolean) => {
  setShowPresence(next);
  try {
    await fetch(`${(import.meta.env.BASE_URL ?? "/").replace(/\/$/, "")}/api/me/presence-preference`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ show_presence: next }),
    });
  } catch {
    toast.error("Could not save that preference");
    setShowPresence(!next);
  }
};
```

with the row:

```tsx
<label className="flex items-start gap-2">
  <input
    type="checkbox"
    checked={showPresence}
    onChange={(e) => togglePresence(e.target.checked)}
    className="mt-1"
  />
  <span>
    <span className="block text-sm text-foreground">Show me as viewing</span>
    <span className="block text-xs text-muted-foreground">
      When off, you can still see who else is viewing a page, but they cannot see you.
    </span>
  </span>
</label>
```

- [ ] **Step 8: Verify typecheck and the full frontend suite**

Run: `cd frontend && bun run test && bunx tsc -b`
Expected: all tests pass; `tsc -b` clean. Use `tsc -b`, not `tsc --noEmit`:
build mode is stricter and is what the Docker build runs, so `--noEmit` can
pass locally and still fail the image build.

- [ ] **Step 9: Run the full backend suite once more**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check .`
Expected: all green.

- [ ] **Step 10: Commit and open the ace-web PR**

```bash
git add frontend/package.json frontend/src/presence/ \
        frontend/src/components/TopNav.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat(presence): mount viewer presence badge across ace-web"
```

Open the PR against `main`. Never push to `main` directly.

---

### Task 13: Deploy verification

**Files:** none — this is a live check.

- [ ] **Step 1: Deploy ace-web to labs**

Trigger `.github/workflows/deploy-ace-web-labs.yml` with `run_migrations: true`
(Task 11 adds a migration).

- [ ] **Step 2: Verify the socket connects behind the ALB**

Open `https://labs.connect.dimagi.com/ace/w/dimagi-team/opps` in two browsers
signed in as different users. Both should see a 2-avatar cluster.

The `/ace/ws/` nginx proxy strips the prefix before Django sees it — if the
socket 404s, re-read `docs/learnings/channels-ws-proxy-path.md`; the presence
route must resolve at `ws/presence/`, not `ace/ws/presence/`.

- [ ] **Step 3: Verify the three behaviors that define the feature**

1. Navigate one browser from the opps list into a run — the other browser's
   badge drops to nothing, and the first appears on the run's roster.
2. Put both browsers on the same run at different steps — both show 2 viewers,
   and the expanded panel names each other's step.
3. Close one browser's tab — the other's badge drops to nothing **within a
   second or two**, not after 60s. A slow drop means the disconnect path is
   not firing and the feature has silently degraded to TTL-expiry.

- [ ] **Step 4: Verify opt-out end to end**

Turn off "Show me as viewing" in one browser, reload both. The opted-out user
must vanish from the other's badge while still seeing the other user.

- [ ] **Step 5: Run the post-deploy probe**

Run: `LABS_TOKEN=... uv run --extra walkthrough python scripts/qa/labs_probe.py`
Expected: no new failures versus the previous run. The probe walks every UI
surface, and presence now renders on all of them.

---

## Self-Review

**Spec coverage** — every spec section maps to a task:

| Spec section | Task(s) |
| --- | --- |
| Shared frontend in canopy-ui | 1–4, 9 |
| Page keys, normalized-resource grouping | 1, 8 (canopy table), 12 (ace table) |
| Authorization — do not trust the page key | 7 (canopy), 11 (ace) |
| Redis HASH, per-connection fields, lazy sweep | 5, 10 |
| Protocol (enter / heartbeat / roster) | 3 (client), 7 + 11 (server) |
| Visibility enforced server-side | 6, 7, 8 (canopy); 11, 12 (ace) |
| Idle | 3 (client detection), 5 (`roster` idle-merge), 4 (rendering) |
| Failure behavior | 3 (reconnect + empty roster on close) |
| UI: collapsed cluster, expand, a11y | 4 |
| Testing table | 1–8, 10–12 |
| Build ordering constraint | Task order preamble, 9 |

**Known gaps, accepted:** the spec's "same page open in both apps shows two
rosters" blind spot is by design. The `snapshot()` race is documented in
`store.roster`'s docstring rather than fixed, matching the prior decision.

**Type consistency:** `PageLocation{pageKey, subLocation}`, `Viewer{email, name,
subLocation, idle, self}`, and the wire shape (`page_key`, `sub_location`) are
used identically in Tasks 1, 3, 4, 8, 12; the server payload built in Tasks 7
and 11 matches the client parser in Task 3 field-for-field. Store functions keep
one signature across Tasks 5, 7, 10, 11.
