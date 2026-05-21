"""Long-lived OppSnapshot / OppCard cache, invalidated by Drive file_ids.

Storage layout (all in the Django cache, Redis-backed in prod):

  opp:snap:v1:<workspace_id>:<slug>:<run_id|->        -> dict envelope
  opp:card:v1:<workspace_id>:<slug>                   -> dict envelope
  opp:idx:v1:<file_id>                                -> set[str] of cache keys
  opp:ws:v1:<workspace_id>                            -> set[str] of cache keys

Each snapshot/card envelope is `{"value": <object>, "file_ids": <set>}`.
Storing the file_ids inline gives a fallback when the reverse-index
entry is missing (Redis eviction or cold-start mid-session) — we walk
the workspace key set, decode each envelope, and invalidate by
intersection.

Fingerprint:
  fingerprint(seq_of_(file_id, modified_time)) -> "sha256:<hex>"

Returned to clients as an ETag header. Stable across the same set of
(file_id, modified_time) pairs regardless of input order.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache

log = logging.getLogger(__name__)

_set = set  # preserve builtin before our module-level `set` shadows it

# Bump when the cached dataclass shape *or* the file_id-tracking
# semantics change — stale entries from before the bump deserialize into
# the new dataclass with leftover attributes (or missing required ones),
# and tracking-semantic bumps similarly orphan entries written with the
# old set of dependencies (they can't receive the new invalidation
# signals). Without the bump, the changes-feed pipeline silently serves
# stale data forever for those entries.
#   v2 — post #260 (StepSnapshot dropped gates; OppCard dropped pending_gate_skills)
#   v3 — post #277 (CachedDriveClient.list_files now records parent
#        folder_id; old entries don't track parent IDs so a new run
#        folder appearing under runs/ never invalidated their cards)
#   v4 — post #512 (OppCard grew a ``runs_summary: list[RunSummary]``
#        field; entries written before this bump deserialise without it
#        and the Opps-list strip would render an empty chip row)
_KEY_VERSION = "v4"


def _snap_key(workspace_id: str, slug: str, run_id: str | None) -> str:
    rid = run_id or "-"
    return f"opp:snap:{_KEY_VERSION}:{workspace_id}:{slug}:{rid}"


def _card_key(workspace_id: str, slug: str) -> str:
    return f"opp:card:{_KEY_VERSION}:{workspace_id}:{slug}"


def _idx_key(file_id: str) -> str:
    return f"opp:idx:{_KEY_VERSION}:{file_id}"


def _ws_key(workspace_id: str) -> str:
    return f"opp:ws:{_KEY_VERSION}:{workspace_id}"


def _add_to_set(cache_key: str, member: str) -> None:
    """Append `member` to a set stored under `cache_key`. Works on any
    Django cache backend (Redis, locmem) by reading-modifying-writing.
    Not strictly atomic — acceptable here because a missed write only
    means we fall back to the inline-file_ids scan path.
    """
    members: _set[str] = cache.get(cache_key) or _set()
    if not isinstance(members, _set):
        members = _set(members)
    if member in members:
        return
    members.add(member)
    cache.set(cache_key, members, timeout=None)


def _remove_set_entries(cache_key: str, members_to_remove: _set[str]) -> None:
    members: _set[str] = cache.get(cache_key) or _set()
    if not isinstance(members, _set):
        members = _set(members)
    members.difference_update(members_to_remove)
    if members:
        cache.set(cache_key, members, timeout=None)
    else:
        cache.delete(cache_key)


def get(*, workspace_id: str, slug: str, run_id: str | None) -> Any | None:
    env = cache.get(_snap_key(workspace_id, slug, run_id))
    if not env:
        return None
    return env.get("value")


def set(  # noqa: A001  (shadows builtin; namespace via module is fine)
    *,
    workspace_id: str,
    slug: str,
    run_id: str | None,
    snap: Any,
    file_ids: _set[str],
) -> None:
    key = _snap_key(workspace_id, slug, run_id)
    cache.set(key, {"value": snap, "file_ids": _set(file_ids)}, timeout=None)
    for fid in file_ids:
        _add_to_set(_idx_key(fid), key)
    _add_to_set(_ws_key(workspace_id), key)


def get_card(workspace_id: str, slug: str) -> Any | None:
    env = cache.get(_card_key(workspace_id, slug))
    if not env:
        return None
    return env.get("value")


def set_card(
    *, workspace_id: str, slug: str, card: Any, file_ids: _set[str],
) -> None:
    key = _card_key(workspace_id, slug)
    cache.set(key, {"value": card, "file_ids": _set(file_ids)}, timeout=None)
    for fid in file_ids:
        _add_to_set(_idx_key(fid), key)
    _add_to_set(_ws_key(workspace_id), key)


def invalidate(file_ids: Iterable[str]) -> None:
    """Drop every snapshot/card whose file_ids intersect the input."""
    file_ids = _set(file_ids)
    if not file_ids:
        return
    keys_to_drop: _set[str] = _set()

    # Fast path: reverse index.
    for fid in file_ids:
        members = cache.get(_idx_key(fid))
        if members:
            keys_to_drop.update(members)

    # Fallback: walk every cached workspace's known keys for an inline
    # file_id intersection. Bounded by N opps per workspace.
    if not keys_to_drop:
        for ws_key in _all_workspace_keys():
            for key in cache.get(ws_key) or _set():
                env = cache.get(key)
                if env and file_ids.intersection(env.get("file_ids") or _set()):
                    keys_to_drop.add(key)

    if keys_to_drop:
        cache.delete_many(keys_to_drop)
        # Clean up reverse-index entries for the dropped keys.
        for fid in file_ids:
            _remove_set_entries(_idx_key(fid), keys_to_drop)


def clear_workspace(workspace_id: str) -> None:
    """Drop every cached snapshot/card for the workspace."""
    ws_key = _ws_key(workspace_id)
    keys = cache.get(ws_key) or _set()
    if keys:
        cache.delete_many(keys)
    cache.delete(ws_key)


def fingerprint(file_id_modtime_pairs: Iterable[tuple[str, str | None]]) -> str:
    """Stable SHA-256 over sorted (file_id, modified_time) pairs.

    Returned as `sha256:<hex>` for use as an HTTP ETag.
    """
    h = hashlib.sha256()
    for fid, mt in sorted((fid, mt or "") for fid, mt in file_id_modtime_pairs):
        h.update(fid.encode("utf-8"))
        h.update(b"\x00")
        h.update(mt.encode("utf-8"))
        h.update(b"\x00")
    return f"sha256:{h.hexdigest()}"


# --- view helpers ---


def cold_load_client(client):
    """Return a CachedDriveClient with bypass=True wrapping the same inner
    client.

    On the cold-load path we must defeat the underlying Drive TTL cache:
    a request that lands here arrived because either a snapshot cache
    miss / explicit ?force=1 OR a Drive Changes API hit invalidated the
    snapshot. In both cases we cannot serve content from a stale per-call
    TTL entry that was written before the snapshot cache was invalidated.
    """
    # Local import to avoid a cycle: drive_cache imports nothing from
    # snapshot_cache, but snapshot_cache being shared we keep its imports
    # narrow.
    from apps.opps.drive_cache import CachedDriveClient

    inner = client._inner if isinstance(client, CachedDriveClient) else client
    return CachedDriveClient(inner, bypass=True)


def etag_or_304(request, etag, build_response):
    """Honor If-None-Match: return a 304 if the request's ETag matches,
    otherwise call ``build_response()`` and tag its response with the ETag.

    Centralizes the ETag round-trip for the read paths that serve cached
    OppSnapshot / OppCard / opp-list payloads. Both branches must agree
    on the ETag value, so passing it in once eliminates a class of bugs
    where the cold-load and cached-hit paths drifted.
    """
    from django.http import HttpResponse

    if request.headers.get("If-None-Match") == etag:
        return HttpResponse(status=304, headers={"ETag": etag})
    resp = build_response()
    resp["ETag"] = etag
    return resp


# --- internals ---


def _all_workspace_keys() -> list[str]:
    """Best-effort enumeration of known workspace key-sets.

    Django's cache API doesn't expose key scanning, so we don't attempt a
    real glob; we just check known low-numbered workspace ids. In practice
    workspaces are sparse and small; we cap the scan at 1024 to keep the
    fallback bounded.
    """
    return [_ws_key(i) for i in range(1, 1024)]
