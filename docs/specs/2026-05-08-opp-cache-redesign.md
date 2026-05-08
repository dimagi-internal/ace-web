# Opp Workbench cache redesign

**Date**: 2026-05-08
**Status**: Approved (brainstorming complete; ready for implementation plan)
**Author**: jjackson + Claude

## Summary

Today the Workbench reads through to Google Drive on every request, with a
30-second TTL cache (`apps/opps/drive_cache.py`) covering individual
`list_files` / `get_content` calls. Inside the TTL window, page loads are
fast; outside, every load triggers a full ~25–40 Drive call walk taking
5–25 s wall clock. The result is that navigating around opps feels slow
even after an "initial" load.

This spec replaces the TTL strategy with a Drive-side change-detection
strategy backed by Google's Drive Changes API, plus a frontend ETag-aware
cache that survives route navigation. The end state: load any opp once,
and subsequent navigations are zero Drive calls until something in that
opp's tree actually changes in Drive.

## Goals

- Load any opp once; subsequent navigations to it are **zero Drive walks**
  until something in that opp's tree actually changes.
- Single source of truth for "did anything change?" — Drive's Changes API.
- Frontend cache survives route navigation in-tab; backend cache survives
  process restart (Redis-backed).
- Failure of the Changes API degrades to "serve last known good snapshot,"
  not "fall back to TTL re-walks."

## Non-goals

- Cross-tab cache sync (each browser tab has its own JS heap; fine).
- Real-time push (no Drive `watch`/webhook channels — too much infra for the
  marginal gain over per-request polling).
- Eliminating the cold first load. The first read of an opp is still
  5–25 s; we just guarantee it's only the first.

## Background

**Drive write sources:**
- The local `ace` CLI dominates today. It runs on operator machines and
  writes to Drive via the same shared service account ace-web uses for
  reads. Writes happen out-of-band — by the time a user opens ace-web,
  any pending Drive activity has long since propagated to the Drive
  Changes feed.
- Live web-chat-driven writes are aspirational/future. The chat
  subprocess writes via the same SA. The existing
  `apps/sessions/opp_broadcast.maybe_emit_opp_updated` already broadcasts
  an `opp.updated` WebSocket event when a chat tool produces a Drive
  side-effect.
- Direct user edits in the Drive web UI are rare but possible.

**Why the current design is slow outside the TTL window:**
`load_opp` walks an opp's full Drive tree — `list_files` per folder
(non-recursive at top, recursive inside specific subfolders) plus
`get_content` for `state.yaml`, `pdd.md`, every verdict YAML, and so
on. ~25–40 Drive calls × 150–300 ms each = 5–25 s wall clock per page
load. The 30-second TTL makes the first repeated load fast; everything
beyond that pays the full cost.

**Why "load once, instant forever" is achievable:** Drive exposes a
`changes.list` API designed precisely for this question. One call
(~100–200 ms) returns the set of file IDs that have changed in a Drive
since a stored `pageToken`. We use that as our invalidation signal and
hold a long-lived assembled-`OppSnapshot` cache that never expires on
its own.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend (React)                                                        │
│  ┌─────────────────┐   ETag round-trip   ┌──────────────────────────┐   │
│  │ oppCache.ts     │ ──────────────────► │ /api/opps/<slug>          │   │
│  │ Map<key,        │ ◄────── 304 ──────  │ If-None-Match: <etag>     │   │
│  │   {snap,etag}>  │                     └──────────────────────────┘   │
│  └─────────────────┘                                                     │
│         ▲                                                                │
│         │ drop entry                                                     │
│  ┌──────┴─────────┐                                                      │
│  │ useOppSocket   │ ◄── opp.updated event                                │
│  └────────────────┘                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend (Django)                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ apps/opps/views.py: workbench()                                  │    │
│  │   1. observe_drive_changes(workspace) → set[file_id]             │    │
│  │   2. invalidate snapshots whose file_ids intersect               │    │
│  │   3. cache hit?  →  return cached  +  ETag header                │    │
│  │      (If-None-Match matches?  →  304 no body)                    │    │
│  │   4. cache miss  →  load_opp(...)  +  cache  +  return           │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────┐    ┌──────────────────────────────────────┐    │
│  │ drive_changes.py    │    │ snapshot_cache.py                    │    │
│  │ - observe(ws)       │    │ - get/set OppSnapshot by             │    │
│  │ - pageToken in Redis│    │   (workspace_id, slug, run_id)       │    │
│  │ - per-request poll  │    │ - file_id → cache_key reverse index  │    │
│  └─────────────────────┘    │ - invalidate(file_ids)               │    │
│                              └──────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       Google Drive API
                  - files.list (cold reads only)
                  - changes.list (validation polls, every request)
```

Two new backend modules; one new frontend module. The existing
`apps/opps/drive_cache.CachedDriveClient` stays put — it's still useful
inside the cold-path `load_opp` walk to dedupe repeated calls within a
single load. We just remove its role as the primary cache layer.

## Backend components

### `apps/opps/drive_changes.py` (new)

Stateless wrapper over Drive's `changes.list` API. Public surface:

```python
def observe(workspace: Workspace, client: DriveClient) -> set[str]:
    """Return the set of file_ids that have changed in the workspace's
    drive since the last call. Each unique change is reported exactly
    once across all worker processes (pageToken advances atomically).

    First call (no pageToken in Redis): seeds the token via
    `changes.getStartPageToken`, returns set() (treat as "no changes
    yet, all caches valid").

    Returns set() on Drive API failure — caller treats this as
    "no changes" and serves cached. Logs at WARNING. Repeated failures
    should escalate to ERROR; pager rules deferred to a follow-up.
    """
```

Implementation notes:

- Redis key `drive:changes:token:<drive_id>` holds the current pageToken.
- Polling is **per-request** (no debounce lock). Concurrent polls with
  the same token are safe: each gets the same delta, applies the same
  idempotent invalidation, and writes the same successor token. Drive
  API quota is not a concern at our scale.
- `<drive_id>` is the resolved Drive container for the workspace's
  `drive_root_folder_id`. Resolution is lazy and cached: on first call
  for a workspace, fetch the file's `driveId` field. If non-null, scope
  `changes.list` to `corpora=drive` + that `driveId`. If null (the
  folder is in the SA's My Drive), scope to `corpora=user`.
- Token expiration: when `changes.list` returns 410 Gone, fetch a new
  start page token, conservatively invalidate **all** snapshots and
  lists for that workspace, return ∅. Next requests do full re-walks.
  Should be very rare.

### `apps/opps/snapshot_cache.py` (new)

Long-lived assembled-snapshot cache with file-id-driven invalidation.
Public surface:

```python
def get(workspace_id: int, slug: str, run_id: str | None) -> OppSnapshot | None
def set(workspace_id: int, slug: str, run_id: str | None,
        snap: OppSnapshot, file_ids: set[str]) -> None
def invalidate(file_ids: set[str]) -> None
def fingerprint(snap: OppSnapshot) -> str  # used as ETag

def get_card(workspace_id: int, slug: str) -> OppCard | None
def set_card(workspace_id: int, slug: str, card: OppCard,
             file_ids: set[str]) -> None

def clear_workspace(workspace_id: int) -> None  # for 410 fallback
```

Storage:

- `opp:snap:<workspace_id>:<slug>:<run_id>` → pickled `OppSnapshot`.
- `opp:card:<workspace_id>:<slug>` → pickled `OppCard`.
- `opp:idx:<file_id>` is a Redis SET of cache-key strings that depend
  on this file_id. On `set` we add to N sets; on `invalidate` we union
  the sets and `DEL` the snapshot/card keys.
- The cache value also carries its own list of file_ids inline as a
  fallback. If the reverse index is missing (Redis eviction or cold
  start mid-session), we scan all snapshot keys, decode the inline
  file_id list, and invalidate by intersection. Bounded by N opps;
  acceptable.

Fingerprint:

- SHA-256 over `sorted((file_id, modified_time))` tuples extracted from
  the cached snapshot. Stable, content-addressed, cheap. Returned to
  the frontend as the ETag header value.

Note: the snapshot cache stores derived/assembled `OppSnapshot` objects
(post-`load_opp`), not raw Drive bytes. The existing `CachedDriveClient`
keeps doing in-load deduplication.

### `load_opp` instrumentation

`load_opp` and `load_opp_card` already touch every file. We thread a
thin tracker through them — either a `_TouchedFileTracker` parameter or
a `contextvar` — that records every `file_id` and `modified_time` seen.
The view passes the touched set to `snapshot_cache.set` so the reverse
index is populated correctly.

No semantic change to either loader. Existing tests continue to pass
unchanged.

### View-layer wiring

`workbench()` in `apps/opps/views.py:477` becomes:

```python
ws, client, err = _require_drive(request)
if err: return err

# 1. Validate cache against Drive's change feed.
changed = drive_changes.observe(ws, client)  # ~100-200ms; ∅ when nothing changed
if changed:
    snapshot_cache.invalidate(changed)

# 2. Cache hit path.
cached = snapshot_cache.get(ws.id, slug, run_id)
if cached and not request.GET.get("force"):
    etag = snapshot_cache.fingerprint(cached)
    if request.headers.get("If-None-Match") == etag:
        return HttpResponse(status=304, headers={"ETag": etag})
    return Response(success_response(serialize_opp_snapshot(cached)),
                    headers={"ETag": etag})

# 3. Cache miss: full load + cache + serve.
with _TouchedFileTracker() as tracked:
    snap = load_opp(client, ace_folder_id=..., slug=slug, run_id=run_id)
snapshot_cache.set(ws.id, slug, run_id, snap, file_ids=tracked.file_ids)
etag = snapshot_cache.fingerprint(snap)
return Response(success_response(serialize_opp_snapshot(snap)),
                headers={"ETag": etag})
```

The `?force=1` query param keeps working as the manual escape hatch
(skips the cache-hit path, always re-walks). Powers the explicit
"Refresh" button.

`opp_collection` (the list page) follows the same pattern with
per-`OppCard` caching: validate via `observe()`, intersect with each
cached card's file_ids, invalidate the affected cards, re-walk only
those, assemble + sort + filter the list at request time. The list
endpoint also returns an ETag derived from the sorted card
fingerprints.

## Frontend components

### `frontend/src/api/oppCache.ts` (new)

Module-scoped, per-tab. Survives route mounts; dies on tab close. No
persistence to localStorage (correctness in the face of stale
localStorage isn't worth the complexity).

```typescript
type Entry<T> = { data: T; etag: string };
const oppSnapshots = new Map<string, Entry<OppSnapshot>>();
const oppLists = new Map<string, Entry<OppCard[]>>();

export function getCachedSnapshot(slug: string, runId: string | null): Entry<OppSnapshot> | undefined;
export function setCachedSnapshot(slug: string, runId: string | null, e: Entry<OppSnapshot>): void;
export function dropOpp(slug: string): void;             // called from useOppSocket
export function getCachedList(key: string): Entry<OppCard[]> | undefined;
export function setCachedList(key: string, e: Entry<OppCard[]>): void;
export function dropList(key: string): void;
export function clearAll(): void;                        // for "Refresh" button
```

### `getOpp` / `listOpps` become ETag-aware

`frontend/src/api/opps.ts`:

```typescript
export async function getOpp(slug, runId, opts) {
  const cached = getCachedSnapshot(slug, runId);
  const headers: HeadersInit = cached && !opts?.force
    ? { "If-None-Match": cached.etag }
    : {};
  const res = await rawRequest(/* path */, { headers });
  if (res.status === 304 && cached) return cached.data;
  const etag = res.headers.get("ETag") ?? "";
  const data = unwrapEnvelope(await res.json());
  setCachedSnapshot(slug, runId, { data, etag });
  return data;
}
```

`request()` (the existing client wrapper at `frontend/src/api/client.ts`)
needs a small extension to expose response headers and 304 status to
callers without breaking unrelated callsites. Either a sibling
`rawRequest()` for the few endpoints that need ETag plumbing, or a
small additional return shape on `request()`. Spec defers the choice
to the implementation plan; either is fine.

### WebSocket integration

`OppWorkbenchPage` (and any other consumer of `useOppSocket`):

```typescript
useOppSocket({
  slug,
  runId,
  onOppUpdated: () => {
    dropOpp(slug);          // local cache evicted
    load({ silent: true }); // refetch — no force=true
  },
});
```

The `force: true` flag goes away from this code path. The Drive Changes
API is now the only invalidation mechanism. `force=true` survives only
on the manual "Refresh" button.

## Data flow examples

**Example A — first visit, cold cache:**
1. Frontend `getOpp("leep-paint", "run-001")` — no cached entry — request without `If-None-Match`.
2. Backend `observe()` polls Changes API (first call, seeds pageToken, returns ∅). `snapshot_cache.get()` misses.
3. `load_opp` walks Drive: ~30 calls, ~5–25 s. Tracker collects file_ids.
4. `snapshot_cache.set` stores snapshot + reverse index. Computes fingerprint → ETag.
5. Response: 200 + body + `ETag: sha256:abc...`. Frontend caches.

**Example B — second visit, nothing changed:**
1. Frontend has cached snapshot + etag — request with `If-None-Match: sha256:abc...`.
2. Backend `observe()` polls Changes API → ∅. No invalidations.
3. `snapshot_cache.get()` hits. Computed fingerprint matches `If-None-Match`.
4. Response: **304 Not Modified, no body.** Frontend uses its in-memory copy.
5. Total cost: 1 Drive call (~150 ms) + 1 Redis read (~1 ms) + 1 fingerprint hash (~1 ms) ≈ 200 ms vs. today's 5–25 s.

**Example C — chat in another tab writes to opp:**
1. Chat process writes `state.yaml` via Drive API.
2. Chat broadcasts `opp.updated` over WebSocket.
3. Tab A's `useOppSocket` fires → `dropOpp("leep-paint")` evicts local cache → `load({ silent: true })`.
4. Backend `observe()` polls Changes → returns `{state.yaml.id}`. `snapshot_cache.invalidate()` drops the snapshot.
5. Cache miss → re-walk → fresh snapshot + new ETag. Response 200 + new body.
6. Tab A re-renders with fresh data. Cache now holds the new etag.

**Example D — list page, one opp updated, 19 untouched:**
1. `listOpps()` request — `If-None-Match: sha256:list-etag-1`.
2. Backend `observe()` returns `{state.yaml.id-of-opp-leep-paint}`. Reverse index says: invalidate `opp:snap:1:leep-paint:*`, `opp:card:1:leep-paint`, and `opp:list:1:*`.
3. List cache miss. Per-card cache: 19 cards still fresh, only `leep-paint` re-walks via `load_opp_card`. Assemble + sort + filter. New list ETag.
4. Response 200 + body. Frontend updates its cache.

## Failure modes

**Drive Changes API call fails (network, 500, quota):**
- `observe()` returns ∅ + logs WARNING. Treated as "no changes." Backend serves cached. Worst case: stale data until the next successful poll.
- This is the right fallback. "Serve last known good" is always better than today's "fall back to TTL re-walks every request."
- After 3 consecutive failures: WARNING → ERROR. Pager rule deferred.

**pageToken expires (Drive returns 410 Gone):**
- `observe()` catches the error, fetches a new `getStartPageToken`,
  calls `snapshot_cache.clear_workspace(ws.id)`, returns ∅.
- Next requests do full re-walks. One-time hit; should be very rare.

**Cached snapshot in Redis but reverse index missing (Redis eviction or cold start mid-session):**
- The reverse index is the source-of-truth for invalidation. Without
  it, we can't safely use it.
- Fallback: snapshot values carry their inline `file_ids` list. On
  reverse-index miss, we SCAN snapshot keys, decode the inline list,
  and invalidate by intersection. Bounded by N opps in the workspace;
  acceptable. (Redis SCAN is non-blocking with a sensible COUNT.)

**Snapshot cache itself unavailable (Redis down):**
- `snapshot_cache.get()` returns None on every call. Every request does
  a full `load_opp` walk — back to today's behavior, just without the
  30 s call-level cache. Acceptable graceful degradation; many other
  things are broken in this scenario too.

**ETag mismatch on a stale frontend (e.g., user kept tab open for hours, backend cache evicted, Drive changed):**
- Frontend sends `If-None-Match: <old-etag>`. Backend computes current
  ETag, doesn't match → 200 + new body. Frontend updates cache. No
  drama.

**Drive's Changes-feed propagation lag (live-chat self-write race):**
- Drive has a small internal lag (~100 ms typical, occasionally 1–2 s)
  between "a write API call returned 200" and "the change is visible
  in `changes.list`."
- For CLI writes this never matters — there's a huge gap between the
  write and any user reading.
- For live web chat this means: chat writes → WebSocket fires → frontend
  refetches → backend `observe()` polls Changes → Drive hasn't
  propagated yet → backend serves the stale cached snapshot → user
  sees old data for ~1–2 s → next interaction (or any subsequent
  poll) catches up.
- **Decision:** accept this as v1. 1–2 s self-write staleness is fine.
  If observed to be worse, add a slug-hint shortcut: WebSocket payload
  includes `slug`, frontend passes `?invalidated_slug=<slug>` on its
  post-WS refetch, backend drops that snapshot before serving. ~5
  lines on each side. Defer until proven necessary.

## Migration / rollout

Internal-only deploy. No public API contract; no backwards-compat
concerns.

1. Land Drive-Changes-API observer behind a settings flag
   `OPPS_USE_CHANGES_API` defaulting to `False`.
2. Land snapshot cache behind the same flag (when off, falls through to
   the current `CachedDriveClient` 30 s TTL behavior unchanged).
3. Test in dev with the flag on. Verify: cache hits on repeat loads,
   ETag returns 304, WebSocket triggers fresh re-fetch, CLI-driven
   writes invalidate on next request.
4. Flip the flag on in `connectlabs.py`. Monitor.
5. Once stable for ~1 week, delete the flag and the legacy 30 s-TTL
   wrapper at the snapshot layer. Keep `CachedDriveClient` for in-load
   dedup.

## Tests

**Unit:**
- `drive_changes.observe()` returns the right deltas given a
  `FakeDriveClient` that records mutations.
- `drive_changes.observe()` recovers from 410 Gone by fetching a new
  start page token and clearing the workspace cache.
- `snapshot_cache.invalidate()` correctly drops keys whose file_ids
  intersect the changed set.
- `snapshot_cache.fingerprint()` is stable across snapshot
  re-serializations and changes when any `(file_id, modified_time)`
  pair changes.
- Reverse-index miss fallback: SCAN finds the affected keys via the
  inline file_ids.

**Integration (Django request cycle):**
- Cold load: first request walks Drive, response carries ETag.
- Repeat load (no Drive change): `If-None-Match` returns 304.
- Mutate-then-request: changed file_id observed by `observe()` →
  invalidation → 200 with fresh body.
- WebSocket path: emit `opp.updated`, confirm cache eviction + refetch.
- pageToken-expired path: fake returns 410; confirm full invalidation
  + recovery.
- `?force=1` bypasses cache regardless of state.

**Frontend (vitest):**
- `oppCache.ts`: set, get, drop, clearAll.
- `getOpp` sends `If-None-Match` when cached; handles 304 by returning
  the cached value; updates cache on 200.
- `useOppSocket` `onOppUpdated` drops the cached entry.

## Out of scope / follow-ups

- Drive `watch` channels for real-time push instead of per-request
  polling. Adds infrastructure (a public webhook endpoint) for
  marginal latency improvement. Defer until needed.
- Pager rules for repeated `changes.list` failures.
- Cross-tab cache synchronization via `BroadcastChannel`.
- Slug-hint shortcut for live-chat self-writes (see "Failure modes").
  Add only if the 1–2 s staleness window is observed to bite.
