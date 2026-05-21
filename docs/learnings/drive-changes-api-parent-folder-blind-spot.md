# Learning: Drive Changes API does not invalidate cached folder listings

**Date**: 2026-05-21
**Context**: `apps/opps/snapshot_cache.py` caches assembled `OppSnapshot` and `OppCard` payloads long-lived, invalidated only when Google's Drive Changes API reports a tracked file_id has changed. The cache works correctly for **file content** (an edited `run_state.yaml` shows up in the changes feed and invalidates the snapshot). It is reliably broken for **folder listings** — when a new file or subfolder is created externally, the changes feed reports the new child's id but **does not consistently report the parent folder as modified**, so cached snapshots whose only signal that something new exists is "the listing of folder X grew" never get invalidated.
**Status**: Active. Fix shipped 2026-05-21 in #495 (registry pattern). See `apps/opps/freshness_overlays.py` and the cross-link to [opp-cache-architecture](opp-cache-architecture.md).

## The gotcha in one sentence

If the only way ace-web's cache knows "something is new" in a tracked Drive folder is by re-listing that folder, the cache will never know.

## Why it bites

`apps/opps/drive_cache.py:103-122` records every listed folder's id into the `TouchedFileTracker`. The intent (PR #277) was: "Drive bumps a folder's modifiedTime when its children change — added / removed / renamed — so the parent ID showing up in the changes feed is what tells us a new run folder appeared under runs/."

In practice, the Drive Changes API is **inconsistent** about reporting parent-folder modifications when children are added externally (e.g. by a sibling ACE plugin run on another machine). Observed symptom (#484, 2026-05-19): the workbench run-selector blinded itself to runs created after the page first loaded. The cache had a perfectly good `runs_summary`. The Changes feed reported the new run folder's id. `snapshot_cache.invalidate(changed_file_ids)` ran. The new id wasn't in any cached snapshot's tracked set, so nothing invalidated. The cache kept serving the stale list, forever, until something else (an unrelated edit to the same opp's content) tripped the invalidation.

## The fix — freshness overlay registry

`apps/opps/freshness_overlays.py` is a declarative registry of "fields that need a fresh re-listing on every cache hit." On every cache hit, `apply_freshness_overlays(snapshot, client, context=...)` walks the registry and re-fetches just the listings (one Drive `list_files` per registered overlay). The cached payload is mutated in place; content fields remain untouched.

Cost: one Drive folder-listing call per cache hit per registered overlay (currently 1 for `OppSnapshot`, 1 for `OppCard` — total of 1 extra call per workbench request).

Trade-off: a bounded constant extra Drive call per cache hit, versus rebuilding the entire cache invalidation contract to track parent folders out-of-band. The constant cost is acceptable because:
- The listing is shallow (one `list_files`).
- The full cold-load is 25–40 Drive calls — the overlay is a rounding error.
- Drive's own propagation lag remains the only staleness floor.

## When to add a new overlay

Add a `FreshnessOverlay` to `apps/opps/freshness_overlays.py` when a cached field:

1. Is sourced from a Drive **folder listing** (not a file content read), AND
2. Gets **externally appended to** by orchestration or other out-of-band writers mid-cache-lifetime.

Examples that ARE covered today:
- `OppSnapshot.runs_summary` — new run folders under `<opp>/runs/` (the original symptom in #484)
- `OppCard.run_count` — same listing, derived count

Examples that are NOT covered today (intentional — see "out of scope" in `freshness_overlays.py`):
- Per-phase artifact lists (`<opp>/<phase-N>/`)
- Per-run phase folder listings (`<opp>/runs/<id>/<phase>/`)

Refreshing artifact lists would require re-walking the recursive opp tree + replaying the manifest attribution machinery + re-reading every verdict file — substantially more than "one folder listing per overlay." The workbench's per-run view is the natural cache-miss point for new artifacts (a user selecting a different run forces a fresh load of that run's content), so the user-visible staleness window is small. Open a follow-up issue if a real user-visible bug surfaces there.

## How to add an overlay

```python
# apps/opps/freshness_overlays.py

def _fetch_fresh_FIELD(client, snapshot, context):
    """One Drive listing → fresh value, or falsy on Drive blip / not applicable."""
    from apps.opps import snapshot_cache

    fresh_client = snapshot_cache.cold_load_client(client)
    # ... one list_files / list_folder call ...
    return fresh_value or None  # falsy = preserve cached


def _apply_FIELD(snapshot, fresh):
    snapshot.FIELD = fresh


SNAPSHOT_OVERLAYS.append(
    FreshnessOverlay(
        name="FIELD",
        fetch_fn=_fetch_fresh_FIELD,
        apply_fn=_apply_FIELD,
    ),
)
```

Then write per-overlay tests in `apps/opps/tests/test_freshness_overlays.py`:
- Cache hit + new child → fresh value surfaces
- Drive failure → cached value preserved
- The integration test asserts ALL overlays apply on a cache hit
- The perf-guard test asserts `len(call_count) == len(REGISTRY)` — bump the assertion if you accept additional Drive calls

## Implementation traps

**Defeat the underlying `CachedDriveClient` TTL.** The overlay path runs inside the same request that already populated the per-call Drive cache (TTL default 30s). Without `bypass=True`, a sub-TTL refresh would return the same stale listing the snapshot was built from. Always wrap via `snapshot_cache.cold_load_client(client)` before the listing call.

**Preserve the cached value on falsy fetch.** An empty list from a transient Drive blip would clobber a perfectly good cached run list — that's the empty-dropdown regression #484 explicitly avoided. `FreshnessOverlay.apply` skips the `apply_fn` call when `fetch_fn` returned a falsy value. Inside `fetch_fn`, return `None` (or an empty list/0) rather than raising when a Drive call legitimately returns nothing.

**Don't change the cached payload shape.** Overlays mutate field values, not field names. Adding a new top-level field to `OppSnapshot` requires bumping `_KEY_VERSION` in `snapshot_cache.py` (per [opp-cache-architecture](opp-cache-architecture.md)) — not what overlays are for.

**Overlays are per-request side effects on the cached dataclass.** The cached object lives in Redis as a pickled value; mutating it via the overlay also mutates the value future cache hits see in this process. That's fine — the next overlay run just re-overlays. But don't rely on the cached value being "as-stored" between hits.

## Cross-references

- [opp-cache-architecture](opp-cache-architecture.md) — the underlying long-lived cache + Drive Changes API invalidation contract that this learning extends.
- [opps-access-module](opps-access-module.md) — the patching boundary for `apps.opps.access.*` (overlays don't live in `access.py` but follow the same module-attribute-lookup discipline).
- PR #494 — the one-off `_refresh_runs_summary_from_drive` helper that #495 generalized into the registry.
- PR #495 — the registry refactor.
