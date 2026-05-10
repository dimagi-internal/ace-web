"""TTL cache wrapper for DriveClient.

The Workbench's per-page Drive workload is dominated by ``list_files``
(every folder + recursive subfolder walk) and ``get_content`` (state.yaml,
opp.yaml, every verdict YAML). On a real opp this lands at ~25-40 Drive
calls × 150-300 ms each = 5-25 s wall clock per page load.

This module wraps any ``DriveClient`` with a Django-cache-backed layer
that serves repeated calls from the cache for a short TTL (default 30 s).
Within the TTL, consecutive page loads land in single-digit ms; outside
the TTL, calls fall through to Drive and refill the cache.

Cache keys are versioned so a manifest / schema bump is a one-line change
without a Redis flush.

Force-refresh: pass ``bypass=True`` when constructing the wrapper. Reads
skip the cache but writes still populate it, so a "Refresh" button can
yield fresh data without leaving stale entries behind.

Mutating methods (``upload_file``, ``update_file``, ``create_folder``,
``copy_file``, ``trash_folder``) pass through to the wrapped client and
invalidate the relevant ``list_files`` / ``get_content`` keys so the next
read sees the post-write state.

Future work — fingerprint validation: replace the TTL with a cheap
"has anything moved?" check (e.g. ``files.list`` over the opp's anchor
folders comparing modifiedTime against a stored fingerprint). Until
that lands, the TTL strikes the operator-friendly balance: edits in
Drive show up within ~30 s, and pages within that window are instant.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.cache import cache

from apps.opps.drive_client import ChangesPage, DriveClient, DriveFile, FileContent
from apps.opps.touched_tracker import current_tracker

log = logging.getLogger(__name__)

_KEY_VERSION = "v1"
_DEFAULT_TTL = 30


def _cache_ttl() -> int:
    return int(getattr(settings, "OPPS_DRIVE_CACHE_SECONDS", _DEFAULT_TTL))


def _list_key(folder_id: str, recursive: bool) -> str:
    return f"drive:{_KEY_VERSION}:list:{folder_id}:{int(bool(recursive))}"


def _content_key(file_id: str, mime_type: str) -> str:
    return f"drive:{_KEY_VERSION}:body:{file_id}:{mime_type}"


def _file_meta_key(file_id: str) -> str:
    return f"drive:{_KEY_VERSION}:meta:{file_id}"


def _invalidate_folder_listings(folder_id: str) -> None:
    cache.delete_many([_list_key(folder_id, False), _list_key(folder_id, True)])


def _invalidate_file(file_id: str, mime_types: Iterable[str] = ()) -> None:
    keys = [_file_meta_key(file_id)]
    keys.extend(_content_key(file_id, mt) for mt in mime_types)
    cache.delete_many(keys)


class CachedDriveClient(DriveClient):
    """Decorator over an underlying DriveClient with TTL caching.

    Reads (``list_files``, ``list_folder``, ``get_content``, ``get_file``)
    consult the cache first and refill on miss. Writes pass through and
    invalidate. The wrapped client is opaque — any DriveClient impl
    (Google, fake, in-memory) works.
    """

    def __init__(
        self,
        inner: DriveClient,
        *,
        ttl_seconds: int | None = None,
        bypass: bool = False,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds if ttl_seconds is not None else _cache_ttl()
        self._bypass = bypass

    # --- Reads ---

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        key = _list_key(folder_id, recursive)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    # Record the parent folder itself, not just children.
                    # Drive bumps a folder's modifiedTime when its children
                    # change (added / removed / renamed), so the parent ID
                    # showing up in the changes feed is what tells us a new
                    # run folder appeared under runs/. Without this, adding
                    # a new run never invalidates the OppCard cache because
                    # the new run folder's own ID was never tracked.
                    tracker.record(folder_id)
                    for f in hit:
                        tracker.record(f.id, f.modified_time)
                return hit
        result = self._inner.list_files(folder_id, recursive=recursive, page_size=page_size)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            tracker.record(folder_id)
            for f in result:
                tracker.record(f.id, f.modified_time)
        return result

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        return self.list_files(folder_id, recursive=False)

    def get_file(self, file_id: str) -> DriveFile:
        key = _file_meta_key(file_id)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    tracker.record(hit.id, hit.modified_time)
                return hit
        result = self._inner.get_file(file_id)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            tracker.record(result.id, result.modified_time)
        return result

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        key = _content_key(file_id, mime_type)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    tracker.record(file_id)
                return hit
        result = self._inner.get_content(file_id, mime_type)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            tracker.record(file_id)
        return result

    # --- Writes (pass-through + invalidate) ---

    def create_folder(self, parent_id: str, name: str) -> str:
        result = self._inner.create_folder(parent_id, name)
        _invalidate_folder_listings(parent_id)
        return result

    def upload_file(
        self, parent_id: str, name: str, content: str, mime_type: str
    ) -> str:
        result = self._inner.upload_file(parent_id, name, content, mime_type)
        _invalidate_folder_listings(parent_id)
        return result

    def update_file(self, file_id: str, content: str, mime_type: str) -> None:
        self._inner.update_file(file_id, content, mime_type)
        _invalidate_file(file_id, mime_types=(mime_type,))

    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        result = self._inner.copy_file(file_id, new_parent_id, new_name)
        _invalidate_folder_listings(new_parent_id)
        return result

    def trash_folder(self, folder_id: str) -> None:
        self._inner.trash_folder(folder_id)
        # Best-effort: invalidate the trashed folder + any recursive listing
        # we may have served that included it. Without listing the parent
        # we can't reach the parent's listing key here, but the parent's
        # TTL will expire shortly. Trashing is rare enough that this is fine.
        _invalidate_folder_listings(folder_id)

    # --- Changes feed (pass-through; caching layer doesn't buffer these) ---

    def get_changes_start_page_token(self, drive_id: str | None = None) -> str:
        return self._inner.get_changes_start_page_token(drive_id)

    def list_changes(
        self, page_token: str, *, drive_id: str | None = None
    ) -> ChangesPage:
        return self._inner.list_changes(page_token, drive_id=drive_id)
