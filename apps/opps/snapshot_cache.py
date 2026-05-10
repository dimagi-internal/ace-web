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

# Bump when the cached dataclass shape changes — stale entries from
# before the bump deserialize into the new dataclass with leftover
# attributes (or missing required ones), and downstream serialization
# can choke on the mismatch. v2 = post #260 (StepSnapshot dropped the
# gates field; OppCard dropped pending_gate_skills).
_KEY_VERSION = "v2"


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


# --- internals ---


def _all_workspace_keys() -> list[str]:
    """Best-effort enumeration of known workspace key-sets.

    Django's cache API doesn't expose key scanning, so we don't attempt a
    real glob; we just check known low-numbered workspace ids. In practice
    workspaces are sparse and small; we cap the scan at 1024 to keep the
    fallback bounded.
    """
    return [_ws_key(i) for i in range(1, 1024)]
