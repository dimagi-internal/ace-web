# Learning: Opp Workbench cache uses Drive Changes API, not TTLs

**Date**: 2026-05-08
**Context**: `apps/opps/views.py` (`workbench`, `_opp_list_impl`) reads through to Google Drive. A naive load is 25–40 Drive calls (5–25s wall clock for a real opp). Today's architecture caches assembled `OppSnapshot` and `OppCard` objects long-lived and validates them per-request against Drive's Changes API. Cold load happens once; subsequent navigations are sub-second until something in that opp's tree actually changes in Drive.
**Status**: Active. Spec: `docs/specs/2026-05-08-opp-cache-redesign.md`. Plan: `docs/plans/2026-05-08-opp-cache-redesign.md`.

## How it works

```
Request /api/opps/<slug>
  │
  ▼
drive_changes.observe(workspace, client)        ─── ~150ms Drive call
  │   (per-request poll of changes.list with Redis-stored pageToken)
  ▼
snapshot_cache.invalidate(changed_file_ids)     ─── Redis-backed reverse index
  │
  ▼
snapshot_cache.get(workspace_id, slug, run_id)
  │
  ├─ HIT  → ETag = sha256(json.dumps(serialized, sort_keys=True))
  │        If-None-Match matches?  →  304 (no body)
  │        else                    →  200 + body + ETag
  │
  └─ MISS → load_opp via TouchedFileTracker (records every file_id seen)
            snapshot_cache.set(... file_ids=tracker.file_ids)
            return 200 + body + new ETag
```

Per-card cache for `_opp_list_impl` follows the same pattern — only the affected `OppCard` re-walks when its file_ids appear in the Changes feed.

## Load-bearing details

**`workspace.pk` is a slug, not an int.** `apps/workspaces/models.py:22` declares `slug = models.CharField(primary_key=True, ...)`. Code that expected `workspace.id` to be an integer was silently using the slug. `snapshot_cache` and `drive_changes` both type the workspace key as `str` and use `workspace.pk`.

**Cold-load needs `bypass=True` on the inner `CachedDriveClient`.** After `snapshot_cache.invalidate(changed)` drops a snapshot, the underlying per-call `CachedDriveClient` (the original 30s-TTL helper, kept for in-load dedup) still has stale entries for the changed files. Re-walking through the non-bypass client would rebuild the snapshot from cached-stale Drive content. The view explicitly wraps `client._inner` in a fresh `CachedDriveClient(..., bypass=True)` before calling `load_opp` / `load_opp_card`. See `apps/opps/views.py` (`workbench` cold-load path).

**ETag is `sha256(json.dumps(serialized_payload, sort_keys=True, default=str))`, not `fingerprint(file_id, modified_time)` pairs.** Both cold and warm paths must produce the same ETag for the same data. Hashing the actual response body is the only stable signal — file fingerprints diverge from cached snapshots after `_overlay_workspace_display_name` mutates the `display_name` from the DB. See `_snapshot_etag` in `apps/opps/views.py`.

**410 Gone on `pageToken` triggers `snapshot_cache.clear_workspace(workspace.pk)`.** Drive's pageToken can expire after long inactivity. `drive_changes.observe` catches `ChangesPage(expired=True)`, fetches a fresh start token, and conservatively invalidates every cached snapshot/card for that workspace. Next requests do full re-walks. One-time hit; rare.

**Per-request Drive-Changes poll is intentional, not a bug.** The architecture polls `drive.changes.list` once per request with no debounce lock. Cost: ~100–200ms. Benefit: Drive's own propagation lag (~100–500ms typical) is the only "staleness" floor — we never serve cached data after Drive has reported the change. This is the explicit trade-off chosen during brainstorming. Don't add a debounce lock without re-reading the spec.

**Cross-task cache coordination is automatic.** All ECS tasks share the labs Redis (`REDIS_URL` from AWS Secrets Manager) and share the same `drive:changes:v1:token:ws:<id>` key. Each Drive change is processed exactly once across the fleet. No application-level synchronization needed — `drive.changes.list` returns the same delta to concurrent callers with the same token, and the `snapshot_cache.invalidate` is idempotent.

**Pickled `OppSnapshot` / `OppCard` are shared cross-task.** Mid-deploy, old and new ECS tasks may read each other's pickled cache values. The cache key carries `_KEY_VERSION = "v1"` (in both `snapshot_cache.py` and `drive_changes.py`). When you change `OppSnapshot` field shape, bump that to `v2` in the same commit so the deploy invalidates everything cleanly.

## What stayed

`apps/opps/drive_cache.py` (`CachedDriveClient`) is still in use. It's no longer the primary cache layer — it's now in-load dedup during the cold-path walk so repeated reads of the same file_id within a single `load_opp` invocation don't double-charge Drive. Don't remove it.

## Failure modes

- **Drive API failure on `changes.list`**: `observe()` returns `set()`, logs WARNING, callers serve cached. Worst case: stale data until the next successful poll.
- **Redis unavailable**: every request behaves like a cache miss; we fall back to the full cold-walk path. Acceptable degradation.
- **Reverse-index miss (Redis eviction mid-session)**: `invalidate` falls back to scanning the workspace key set and matching against inline `file_ids` stored in each cached envelope. Bounded by N opps; fine.
- **Frontend ETag mismatch on long-open tab**: backend computes current ETag, doesn't match stale `If-None-Match` → 200 + new body. Frontend updates cache. No drama.

## ETag round-trip on the frontend

`frontend/src/api/oppCache.ts` is a per-tab `Map<key, {data, etag}>`. `getOpp` / `listOpps` send `If-None-Match` from the cached entry; on 304 they return the cached body with no network body. WebSocket `opp.updated` events drop the cached entry; the next normal fetch (no `force: true`) goes through the backend's Changes-API path, which discovers the change and serves fresh.

## Don't

- Don't propose adding a TTL to the snapshot cache. The whole point of the redesign was to remove TTLs — staleness is detected via Drive's own change feed, not by clock.
- Don't add a slug-hint shortcut to skip the Changes-API poll on chat-driven writes unless you've observed the 1–2s self-write staleness window biting in real use. The spec deliberately accepts that race for architectural simplicity.
- Don't store anything PII in the cached snapshot — Redis is shared across tenants on labs. Workspace scoping in the cache key is the access-control gate; don't cross it.
