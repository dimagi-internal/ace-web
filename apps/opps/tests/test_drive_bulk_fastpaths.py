"""The bulk Drive fast paths, and the cache layer that makes them pay off.

`DriveRunStore.list_runs` negotiates `find_in_folders` / `get_contents` off
the client with getattr(). The subtle failure this file guards: if the CACHE
WRAPPER doesn't expose them, every request silently takes the slow per-run
path and the optimisation is inert while looking installed.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core.cache import cache

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import DriveFile, FileContent


@dataclass
class _Fake:
    """Minimal inner client offering both fast paths, counting its calls."""

    def __post_init__(self):
        self.find_calls = 0
        self.bulk_calls = 0
        self.single_calls = 0
        self.bulk_seen: list = []

    def find_in_folders(self, parent_ids, name):
        self.find_calls += 1
        return {
            pid: DriveFile(
                id=f"state-{pid}", name=name, mime_type="text/yaml",
                web_view_link="", path=name, parent_id=pid,
            )
            for pid in parent_ids
        }

    def get_contents(self, specs):
        self.bulk_calls += 1
        self.bulk_seen.append([s[0] for s in specs])
        return {fid: f"body-of-{fid}" for fid, _ in specs}

    def get_content(self, file_id, mime_type, *, export_as=None):
        self.single_calls += 1
        return FileContent(content=f"body-of-{file_id}", content_type=mime_type)


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()
    yield
    cache.clear()


def _wrap(inner, bypass=False):
    return CachedDriveClient(inner, ttl_seconds=30, bypass=bypass)


def test_the_wrapper_exposes_the_fast_paths():
    """If it doesn't, DriveRunStore's getattr() check fails and every request
    quietly takes the slow path — installed but inert."""
    c = _wrap(_Fake())
    assert callable(getattr(c, "find_in_folders", None))
    assert callable(getattr(c, "get_contents", None))


def test_find_in_folders_is_cached_and_order_independent():
    inner = _Fake()
    c = _wrap(inner)
    a = c.find_in_folders(["p1", "p2", "p3"], "run_state.yaml")
    b = c.find_in_folders(["p3", "p1", "p2"], "run_state.yaml")  # same set, new order
    assert a.keys() == b.keys()
    assert inner.find_calls == 1, "parent order must not change the cache key"


def test_get_contents_fetches_only_the_misses():
    inner = _Fake()
    c = _wrap(inner)
    specs = [("f1", "text/yaml"), ("f2", "text/yaml")]
    assert c.get_contents(specs) == {"f1": "body-of-f1", "f2": "body-of-f2"}
    # Second call for an overlapping set: only the new id is fetched.
    c.get_contents([("f1", "text/yaml"), ("f3", "text/yaml")])
    assert inner.bulk_seen == [["f1", "f2"], ["f3"]]


def test_a_bulk_read_warms_the_cache_for_single_reads():
    """The repeat-visit win: historical runs never change, so after one load
    only the active run is actually re-fetched."""
    inner = _Fake()
    c = _wrap(inner)
    c.get_contents([("f1", "text/yaml")])
    got = c.get_content("f1", "text/yaml")
    assert got.content == "body-of-f1"
    assert inner.single_calls == 0, "the single read should have hit the bulk-warmed key"


def test_a_single_read_warms_the_cache_for_bulk_reads():
    inner = _Fake()
    c = _wrap(inner)
    c.get_content("f1", "text/yaml")
    c.get_contents([("f1", "text/yaml")])
    assert inner.bulk_calls == 0, "nothing was missing, so no bulk fetch should fire"


def test_bypass_skips_the_cache_on_reads():
    inner = _Fake()
    c = _wrap(inner, bypass=True)
    c.get_contents([("f1", "text/yaml")])
    c.get_contents([("f1", "text/yaml")])
    assert inner.bulk_calls == 2, "a Refresh must actually re-read"


def test_it_degrades_when_the_inner_client_has_no_fast_paths():
    """A DriveClient implementation without the bulk methods must still work —
    the wrapper falls back to single reads rather than raising."""

    class _Plain:
        def __init__(self):
            self.single_calls = 0

        def get_content(self, file_id, mime_type, *, export_as=None):
            self.single_calls += 1
            return FileContent(content=f"body-of-{file_id}", content_type=mime_type)

    inner = _Plain()
    c = _wrap(inner)
    assert c.get_contents([("f1", "text/yaml")]) == {"f1": "body-of-f1"}
    assert inner.single_calls == 1


def test_find_in_folders_synthesises_rather_than_returning_empty():
    """An empty dict is a LEGITIMATE answer — "no folder holds that file". A
    wrapper that returned {} to mean "I can't batch" would be silently
    indistinguishable from "this opp has no runs"."""

    class _Plain:
        def __init__(self):
            self.listed = []

        def list_files(self, folder_id, recursive=False, page_size=100):
            self.listed.append(folder_id)
            return [
                DriveFile(
                    id=f"state-{folder_id}", name="run_state.yaml",
                    mime_type="text/yaml", web_view_link="", path="run_state.yaml",
                )
            ]

    inner = _Plain()
    c = _wrap(inner)
    got = c.find_in_folders(["p1", "p2"], "run_state.yaml")
    assert set(got) == {"p1", "p2"}
    assert got["p1"] is not None and got["p1"].id == "state-p1"
    assert inner.listed == ["p1", "p2"], "it must actually go and look"
