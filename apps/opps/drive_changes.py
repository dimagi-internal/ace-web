"""Drive Changes API observer for cache invalidation.

`observe(workspace, client)` returns the set of file_ids that changed
since the last call, across everything the service account can see — not
just this workspace's folder, and never scoped to one shared drive (that
needs drive membership the SA deliberately lacks; see
DriveClient.get_changes_start_page_token). Ids outside the workspace are
harmless: invalidation only touches cache entries that recorded reading
them. Each unique change is reported exactly once per workspace across all
worker processes via a Redis-stored pageToken.

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

# v2 — the feed is the SA's whole corpus, not one shared drive's (see
#      DriveClient.get_changes_start_page_token). A v1 token belongs to the
#      drive-scoped feed and must not be replayed against the new one.
_KEY_VERSION = "v2"

# How long to stop retrying a failing seed. A seed failure caches nothing, so
# without this every request pays another Drive round-trip to fail the same
# way (measured on labs 2026-09-19, when the seed was still drive-scoped and
# every request logged `teamDriveMembershipRequired`). Short enough that a
# fixed credential takes effect within minutes without a deploy.
SEED_RETRY_SECONDS = 300


def _token_key(workspace_id: str) -> str:
    return f"drive:changes:{_KEY_VERSION}:token:ws:{workspace_id}"


def _seed_backoff_key(workspace_id: str) -> str:
    return f"drive:changes:{_KEY_VERSION}:seedfail:ws:{workspace_id}"


def observe(workspace, client: DriveClient) -> set[str]:
    """Return the set of file_ids changed since `workspace`'s last call.

    First call (no token in Redis): seed the token, return set() (treat as
    "no changes yet, all caches are valid"). On Drive failure: log WARNING,
    return set(). On 410 Gone: re-seed, clear the workspace's snapshot cache
    via snapshot_cache.clear_workspace, return set().
    """
    from apps.opps import snapshot_cache  # noqa: PLC0415  (avoid circular import)

    token_key = _token_key(workspace.pk)

    token = cache.get(token_key)
    if not token:
        # A recent seed failed. Don't pay the round-trip again yet — a
        # persistent failure (e.g. a revoked credential) would otherwise cost
        # every request a Drive call and a log line, and none of them can
        # succeed.
        if cache.get(_seed_backoff_key(workspace.pk)):
            return set()
        try:
            new_token = client.get_changes_start_page_token()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "drive_changes: failed to seed start page token for ws=%s "
                "(not retrying for %ss): %s",
                workspace.pk, SEED_RETRY_SECONDS, exc,
            )
            cache.set(_seed_backoff_key(workspace.pk), 1, timeout=SEED_RETRY_SECONDS)
            return set()
        cache.delete(_seed_backoff_key(workspace.pk))
        cache.set(token_key, new_token, timeout=None)
        return set()

    try:
        page = client.list_changes(token)
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
            new_token = client.get_changes_start_page_token()
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
