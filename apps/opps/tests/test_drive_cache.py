"""Tests for the CachedDriveClient TTL wrapper.

The wrapper sits between views.py and the GoogleDriveClient (or any
DriveClient impl). It needs to:

  1. Serve repeated reads from the Django cache without hitting the inner
     client a second time within the TTL.
  2. Respect ``bypass=True`` for force-refresh: skip read-cache but still
     populate it with fresh data so subsequent (non-bypass) reads are
     fast again.
  3. Pass-through writes and invalidate the relevant read-cache entries
     so the next read sees the post-write state.

These tests use a tiny in-process FakeDriveClient so we can count exact
inner-method calls per scenario.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core.cache import cache

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import DriveClient, DriveFile, FileContent

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _flush_cache():
    """Django's LocMem cache is process-wide; without flushing between
    tests the per-folder list cache leaks state across the suite."""
    cache.clear()
    yield
    cache.clear()


@dataclass
class _Counts:
    list_files: int = 0
    get_content: int = 0
    get_file: int = 0


class _FakeDriveClient(DriveClient):
    def __init__(self):
        self.counts = _Counts()
        self._files: dict[str, DriveFile] = {}
        self._bodies: dict[tuple[str, str], FileContent] = {}
        self._listings: dict[tuple[str, bool], list[DriveFile]] = {}

    def seed_listing(
        self, folder_id: str, recursive: bool, files: list[DriveFile]
    ) -> None:
        self._listings[(folder_id, recursive)] = files

    def seed_body(self, file_id: str, mime_type: str, content: str) -> None:
        self._bodies[(file_id, mime_type)] = FileContent(
            content=content, content_type=mime_type
        )

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ):
        self.counts.list_files += 1
        return list(self._listings.get((folder_id, recursive), []))

    def get_content(self, file_id: str, mime_type: str):
        self.counts.get_content += 1
        return self._bodies[(file_id, mime_type)]

    def get_file(self, file_id: str):
        self.counts.get_file += 1
        return self._files[file_id]

    # No-op writes — we just need them to exist for invalidation tests.
    def create_folder(self, parent_id, name):
        return f"new-{name}"

    def upload_file(self, parent_id, name, content, mime_type):
        return f"new-{name}"

    def update_file(self, file_id, content, mime_type):
        pass

    def copy_file(self, file_id, new_parent_id, new_name=None):
        return f"copy-{file_id}"

    def trash_folder(self, folder_id):
        pass


@pytest.fixture
def inner():
    fake = _FakeDriveClient()
    fake.seed_listing(
        "folder-A", False,
        [DriveFile(id="f1", name="a.md", mime_type="text/markdown", path="a.md", web_view_link="")],
    )
    fake.seed_body("f1", "text/markdown", "# A")
    return fake


def test_list_files_cached_within_ttl(inner):
    client = CachedDriveClient(inner)
    out_a = client.list_files("folder-A")
    out_b = client.list_files("folder-A")
    out_c = client.list_files("folder-A")

    assert inner.counts.list_files == 1
    assert out_a == out_b == out_c


def test_get_content_cached_within_ttl(inner):
    client = CachedDriveClient(inner)
    a = client.get_content("f1", "text/markdown")
    b = client.get_content("f1", "text/markdown")

    assert inner.counts.get_content == 1
    assert a.content == b.content == "# A"


def test_recursive_and_non_recursive_listings_have_separate_keys(inner):
    inner.seed_listing("folder-A", True, [
        DriveFile(
            id="f1", name="a.md", mime_type="text/markdown",
            path="a.md", web_view_link="",
        ),
        DriveFile(
            id="f2", name="sub/b.md", mime_type="text/markdown",
            path="sub/b.md", web_view_link="",
        ),
    ])
    client = CachedDriveClient(inner)

    flat = client.list_files("folder-A", recursive=False)
    deep = client.list_files("folder-A", recursive=True)

    assert len(flat) == 1
    assert len(deep) == 2
    assert inner.counts.list_files == 2  # Distinct cache keys, distinct calls.


def test_bypass_skips_read_cache_but_repopulates(inner):
    client = CachedDriveClient(inner)
    client.list_files("folder-A")  # warm
    assert inner.counts.list_files == 1

    bypass_client = CachedDriveClient(inner, bypass=True)
    bypass_client.list_files("folder-A")
    assert inner.counts.list_files == 2  # Bypass forced an inner call.

    # And after bypass repopulates, the next (non-bypass) read is cached.
    cached_again = CachedDriveClient(inner)
    cached_again.list_files("folder-A")
    assert inner.counts.list_files == 2  # No new inner call.


def test_upload_invalidates_parent_listing(inner):
    client = CachedDriveClient(inner)
    client.list_files("folder-A")  # warm
    assert inner.counts.list_files == 1

    client.upload_file("folder-A", "b.md", "# B", "text/markdown")

    client.list_files("folder-A")  # post-write, should refetch
    assert inner.counts.list_files == 2


def test_update_file_invalidates_content_cache(inner):
    client = CachedDriveClient(inner)
    client.get_content("f1", "text/markdown")
    assert inner.counts.get_content == 1

    client.update_file("f1", "# A — edited", "text/markdown")

    client.get_content("f1", "text/markdown")
    assert inner.counts.get_content == 2  # Refetched after update.


def test_create_folder_invalidates_parent_listings(inner):
    client = CachedDriveClient(inner)
    client.list_files("folder-A", recursive=False)
    client.list_files("folder-A", recursive=True)
    assert inner.counts.list_files == 2

    client.create_folder("folder-A", "new-sub")

    client.list_files("folder-A", recursive=False)
    client.list_files("folder-A", recursive=True)
    # Both flat and recursive listings must invalidate.
    assert inner.counts.list_files == 4
