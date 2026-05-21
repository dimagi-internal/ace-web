"""Reverse-index for the videos local-FS cache.

Maps Drive ``file_id`` → ``(slug, run_id, kind)`` so that when
``drive_changes.observe`` reports a file_id as changed, we can unlink
the corresponding local file. Sibling of ``apps.opps.snapshot_cache``
but much simpler: opps caches assembled snapshot OBJECTS in Redis,
videos caches FILES on disk and only uses Redis to track which file_id
maps to which local path.

Storage layout (Django cache, Redis-backed in prod):

  videos:fcache:v1:fid:<workspace_id>:<file_id>  → {"slug","run_id","kind"}
  videos:fcache:v1:ws:<workspace_id>             → set[str] of cached file_ids

Two known kinds today:

  - ``output_mp4``: local at ``programs/<slug>/runs/<run>/output.mp4``
                    + symlink at ``explorer/media/final.mp4``.
  - ``explorer_archive``: local extracted under ``explorer/`` (no
                    canonical archive file on disk; we just nuke the
                    extracted dir on invalidate so it lazy-extracts).
"""
from __future__ import annotations

import logging
from typing import Literal

from django.core.cache import cache

log = logging.getLogger(__name__)

_KEY_VERSION = "v1"
Kind = Literal["output_mp4", "explorer_archive"]


def _fid_key(workspace_id: str, file_id: str) -> str:
    return f"videos:fcache:{_KEY_VERSION}:fid:{workspace_id}:{file_id}"


def _ws_key(workspace_id: str) -> str:
    return f"videos:fcache:{_KEY_VERSION}:ws:{workspace_id}"


def record(workspace_id: str, slug: str, run_id: str, kind: Kind, file_id: str) -> None:
    """Record that a local file is sourced from this Drive file_id.

    Called right after a lazy-pull or publish so the next
    ``invalidate`` knows which (slug, run_id, kind) to unlink when the
    file_id appears in a Drive changes feed.
    """
    cache.set(
        _fid_key(workspace_id, file_id),
        {"slug": slug, "run_id": run_id, "kind": kind},
        timeout=None,  # forever — invalidate is event-driven
    )
    ws = cache.get(_ws_key(workspace_id)) or set()
    if not isinstance(ws, set):
        ws = set(ws)
    ws.add(file_id)
    cache.set(_ws_key(workspace_id), ws, timeout=None)


def invalidate(workspace_id: str, changed_file_ids: set[str]) -> int:
    """For each changed file_id we have cached, unlink the local file
    and drop the index entry. Returns the count of invalidations
    performed for logging / metrics.

    Idempotent: a file_id we don't know about is a no-op. A file_id
    we know about but whose local file is already gone is also a
    no-op (the Redis entry is dropped regardless so the next
    lazy-pull re-records it).
    """
    if not changed_file_ids:
        return 0
    from apps.videos import service  # avoid circular import

    n = 0
    ws = cache.get(_ws_key(workspace_id)) or set()
    if not isinstance(ws, set):
        ws = set(ws)
    for fid in changed_file_ids:
        entry = cache.get(_fid_key(workspace_id, fid))
        if not entry:
            continue
        slug = entry["slug"]
        run_id = entry["run_id"]
        kind = entry["kind"]
        try:
            if kind == "output_mp4":
                service.output_path(slug, run_id).unlink(missing_ok=True)
                link = service.explorer_dir(slug, run_id) / "media" / "final.mp4"
                if link.is_symlink() or link.exists():
                    link.unlink(missing_ok=True)
            elif kind == "explorer_archive":
                import shutil
                exp_dir = service.explorer_dir(slug, run_id)
                if exp_dir.is_dir():
                    shutil.rmtree(exp_dir, ignore_errors=True)
            else:
                log.warning("videos.file_cache: unknown kind %r for fid=%s", kind, fid)
                continue
            log.info(
                "videos.file_cache: invalidated %s for %s/%s (fid=%s)",
                kind, slug, run_id, fid,
            )
            n += 1
        except OSError as exc:
            log.warning(
                "videos.file_cache: invalidate I/O error for %s/%s/%s: %s",
                slug, run_id, kind, exc,
            )
        finally:
            cache.delete(_fid_key(workspace_id, fid))
            ws.discard(fid)
    cache.set(_ws_key(workspace_id), ws, timeout=None)
    return n


def clear_workspace(workspace_id: str) -> int:
    """Drop every file-cache entry for a workspace. Used on Drive
    pageToken expiry: we don't know what changed during the gap, so
    conservatively invalidate everything for this workspace."""
    ws = cache.get(_ws_key(workspace_id))
    if not ws:
        return 0
    if not isinstance(ws, set):
        ws = set(ws)
    keys = [_fid_key(workspace_id, fid) for fid in ws]
    cache.delete_many(keys)
    cache.delete(_ws_key(workspace_id))
    return len(keys)
