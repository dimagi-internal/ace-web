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


def _find_key(parent_ids: list[str], name: str) -> str:
    """Stable across parent ORDER — the caller builds the list from a folder
    listing whose order Drive does not guarantee, and an order-sensitive key
    would miss on every other request."""
    import hashlib

    digest = hashlib.sha1(
        ("|".join(sorted(parent_ids)) + "::" + name).encode()
    ).hexdigest()[:16]
    return f"drive:{_KEY_VERSION}:find:{digest}"


def _content_key(file_id: str, mime_type: str, export_as: str | None = None) -> str:
    # ``export_as`` is part of the key: the same file exported as text/plain
    # and as text/markdown are different bodies, and collapsing them would
    # serve a prose reader the plain-text export (or worse, hand a YAML
    # reader a markdown-escaped body).
    suffix = f":as={export_as}" if export_as else ""
    return f"drive:{_KEY_VERSION}:body:{file_id}:{mime_type}{suffix}"


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

    def get_content(
        self, file_id: str, mime_type: str, *, export_as: str | None = None
    ) -> FileContent:
        key = _content_key(file_id, mime_type, export_as)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    tracker.record(file_id)
                return hit
        result = self._inner.get_content(file_id, mime_type, export_as=export_as)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            tracker.record(file_id)
        return result

    # --- Bulk fast paths (see GoogleDriveClient) ---------------------------
    # Exposed here as well as on the inner client because DriveRunStore
    # negotiates them with getattr(): if the WRAPPER lacks them, every request
    # silently takes the slow per-run path and the optimisation is inert.

    def find_in_folders(self, parent_ids: list[str], name: str) -> dict:
        finder = getattr(self._inner, "find_in_folders", None)
        if not callable(finder):
            return {}
        key = _find_key(parent_ids, name)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                return hit
        result = finder(parent_ids, name)
        cache.set(key, result, timeout=self._ttl)
        return result

    def get_contents(self, specs: list) -> dict:
        """Serve what the cache already holds; fetch only the misses in bulk.

        Keyed identically to ``get_content``, so a bulk read warms the cache
        for later single reads and vice versa. This is where the repeat-visit
        win comes from: historical runs never change, so after one load only
        the active run's state is actually re-fetched.
        """
        out: dict[str, str] = {}
        misses: list = []
        for file_id, mime_type in specs:
            if not self._bypass:
                hit = cache.get(_content_key(file_id, mime_type))
                if hit is not None:
                    out[file_id] = hit.content
                    tracker = current_tracker()
                    if tracker is not None:
                        tracker.record(file_id)
                    continue
            misses.append((file_id, mime_type))

        bulk = getattr(self._inner, "get_contents", None)
        if misses and callable(bulk):
            fetched = bulk(misses)
        elif misses:
            fetched = {
                fid: self._inner.get_content(fid, mt).content for fid, mt in misses
            }
        else:
            fetched = {}

        mime_by_id = dict(specs)
        for file_id, text in fetched.items():
            out[file_id] = text
            cache.set(
                _content_key(file_id, mime_by_id.get(file_id, "")),
                FileContent(content=text, content_type=mime_by_id.get(file_id, "text/plain")),
                timeout=self._ttl,
            )
            tracker = current_tracker()
            if tracker is not None:
                tracker.record(file_id)
        return out

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

    def upload_binary(
        self, parent_id: str, name: str, content: bytes, mime_type: str
    ) -> str:
        result = self._inner.upload_binary(parent_id, name, content, mime_type)
        _invalidate_folder_listings(parent_id)
        return result

    def update_binary(self, file_id: str, content: bytes, mime_type: str) -> None:
        self._inner.update_binary(file_id, content, mime_type)
        _invalidate_file(file_id, mime_types=(mime_type,))

    def get_binary(self, file_id: str) -> bytes:
        # Binary content is large and per-file unique; no caching layer.
        return self._inner.get_binary(file_id)

    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        result = self._inner.copy_file(file_id, new_parent_id, new_name)
        _invalidate_folder_listings(new_parent_id)
        return result

    def move_file(self, file_id: str, new_parent_id: str) -> None:
        self._inner.move_file(file_id, new_parent_id)
        # The file's old parent listing is now stale, but we don't know it
        # without an extra Drive lookup. Best-effort: invalidate new parent
        # and the file_id itself; the old parent's TTL will expire shortly.
        _invalidate_folder_listings(new_parent_id)
        _invalidate_file(file_id)

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
