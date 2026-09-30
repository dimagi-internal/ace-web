"""Drive Changes API observer for the videos surface.

Mirror of ``apps.opps.drive_changes.observe`` with a separate pageToken
key. Two observers per workspace (opps + videos) intentionally avoids
the "first consumer drains the feed" problem — each gets its own clean
stream from Drive.

Why videos needs its own observer:

``serve_media`` caches lazy-pulled output.mp4 + explorer assets on
local FS. Without an event-driven invalidator, the cache becomes
permanently stale after a republish (the lazy-pull only fires when
local is missing). This observer surfaces the changed file_ids per
request; ``apps.videos.file_cache.invalidate`` maps them back to
local paths and unlinks the stale files. Next request lazy-pulls
fresh bytes.

Failure modes:
  - Drive API raises:  log WARNING, return set() — caller serves cached.
  - 410 Gone (token expired): re-seed, clear the workspace's file_cache.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from apps.opps.drive_client import DriveClient

log = logging.getLogger(__name__)

# v2 — the feed is the SA's whole corpus, not one shared drive's (see
#      DriveClient.get_changes_start_page_token); v1 tokens are drive-scoped.
_KEY_VERSION = "v2"


def _token_key(workspace_id: str) -> str:
    return f"drive:changes:videos:{_KEY_VERSION}:token:ws:{workspace_id}"


def observe(workspace, client: DriveClient) -> set[str]:
    """Return file_ids changed since `workspace`'s last call.

    The feed is everything the service account can see, never one shared
    drive (see ``apps.opps.drive_changes``); ids outside the workspace are
    harmless to ``file_cache.invalidate``.

    First call seeds the token + returns empty (treats existing caches
    as valid — the alternative is purging all caches on cold-start,
    which costs more than the brief staleness window covers).
    """
    from apps.videos import file_cache  # avoid circular import

    token_key = _token_key(workspace.pk)

    token = cache.get(token_key)
    if not token:
        try:
            new_token = client.get_changes_start_page_token()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "videos.drive_changes: failed to seed start page token for ws=%s: %s",
                workspace.pk, exc,
            )
            return set()
        cache.set(token_key, new_token, timeout=None)
        return set()

    try:
        page = client.list_changes(token)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "videos.drive_changes: list_changes failed for ws=%s: %s",
            workspace.pk, exc,
        )
        return set()

    if page.expired:
        log.info(
            "videos.drive_changes: pageToken expired for ws=%s; re-seeding",
            workspace.pk,
        )
        try:
            new_token = client.get_changes_start_page_token()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "videos.drive_changes: failed to re-seed for ws=%s: %s",
                workspace.pk, exc,
            )
            cache.delete(token_key)
            return set()
        cache.set(token_key, new_token, timeout=None)
        # Conservatively clear all of this workspace's file-cache
        # entries — we don't know what changed during the gap.
        file_cache.clear_workspace(str(workspace.pk))
        return set()

    if page.next_page_token:
        cache.set(token_key, page.next_page_token, timeout=None)
    return page.changed_file_ids
