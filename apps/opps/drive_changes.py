"""Drive Changes API observer for cache invalidation.

`observe(workspace, client)` returns the set of file_ids that changed in
the workspace's drive since the last call. Each unique change is reported
exactly once across all worker processes via a Redis-stored pageToken.

This is the single source of truth for "did anything change in Drive?".
Views call it once per request and use the returned file_ids to invalidate
matching snapshot-cache keys via apps.opps.snapshot_cache.invalidate.

Failure modes:
  - Drive API raises: log WARNING, return set() (caller serves cached).
  - Drive returns 410 Gone (token expired): re-seed via
    get_changes_start_page_token, clear the workspace's snapshot cache,
    return set() for THIS call. The next call observes from the new token.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from apps.opps.drive_client import DriveClient

log = logging.getLogger(__name__)

_KEY_VERSION = "v1"


def _token_key(workspace_id: str) -> str:
    return f"drive:changes:{_KEY_VERSION}:token:ws:{workspace_id}"


def _drive_id_key(workspace_id: str) -> str:
    return f"drive:changes:{_KEY_VERSION}:driveid:ws:{workspace_id}"


def _resolve_drive_id(workspace, client: DriveClient) -> str | None:
    """Resolve the workspace's containing shared-drive id (or None for My Drive).

    Cached in Redis so we don't pay a `files.get` on every observe(). The
    cache survives forever because the answer doesn't change for a given
    folder id.
    """
    key = _drive_id_key(workspace.pk)
    sentinel = object()
    cached = cache.get(key, sentinel)
    if cached is not sentinel:
        return cached or None  # "" sentinel for "we resolved it as My Drive"
    try:
        f = client.get_file(workspace.drive_root_folder_id)
        # `drive_id` is a future field on DriveFile (see Step 6 below) —
        # for now, getattr fallback so this works pre-extension.
        drive_id = getattr(f, "drive_id", None) or None
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_changes: failed to resolve drive_id for workspace %s: %s",
            workspace.pk, exc,
        )
        return None
    cache.set(key, drive_id or "", timeout=None)
    return drive_id


def observe(workspace, client: DriveClient) -> set[str]:
    """Return the set of file_ids changed in `workspace`'s drive since the last call.

    First call (no token in Redis): seed the token, return set() (treat as
    "no changes yet, all caches are valid"). On Drive failure: log WARNING,
    return set(). On 410 Gone: re-seed, clear the workspace's snapshot cache
    via snapshot_cache.clear_workspace, return set().
    """
    from apps.opps import snapshot_cache  # noqa: PLC0415  (avoid circular import)

    token_key = _token_key(workspace.pk)
    drive_id = _resolve_drive_id(workspace, client)

    token = cache.get(token_key)
    if not token:
        # First call: seed and return empty.
        try:
            new_token = client.get_changes_start_page_token(drive_id=drive_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "drive_changes: failed to seed start page token for ws=%s: %s",
                workspace.pk, exc,
            )
            return set()
        cache.set(token_key, new_token, timeout=None)
        return set()

    try:
        page = client.list_changes(token, drive_id=drive_id)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_changes: list_changes failed for ws=%s: %s",
            workspace.pk, exc,
        )
        return set()

    if page.expired:
        log.info(
            "drive_changes: pageToken expired for ws=%s; re-seeding",
            workspace.pk,
        )
        try:
            new_token = client.get_changes_start_page_token(drive_id=drive_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "drive_changes: failed to re-seed for ws=%s after 410: %s",
                workspace.pk, exc,
            )
            cache.delete(token_key)
            return set()
        cache.set(token_key, new_token, timeout=None)
        snapshot_cache.clear_workspace(workspace.pk)
        return set()

    if page.next_page_token:
        cache.set(token_key, page.next_page_token, timeout=None)
    return page.changed_file_ids
