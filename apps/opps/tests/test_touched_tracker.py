"""Tests for apps.opps.touched_tracker."""
from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.opps.touched_tracker import TouchedFileTracker, current_tracker

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _flush_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client() -> CachedDriveClient:
    inner = FakeDriveClient.from_tree({
        "ACE": {
            "alpha": {
                "run_state.yaml": "step: a\n",
                "idea.md": "alpha idea",
            }
        }
    })
    return CachedDriveClient(inner)


def test_no_tracker_active_means_no_recording(client):
    assert current_tracker() is None
    client.list_files(client._inner.folder_id("ACE/alpha"))
    # Nothing to assert — just confirm no exception.


def test_list_files_records_visited_file_ids(client):
    alpha_id = client._inner.folder_id("ACE/alpha")
    state_id = client._inner.file_id("ACE/alpha/run_state.yaml")
    idea_id = client._inner.file_id("ACE/alpha/idea.md")

    with TouchedFileTracker() as tracker:
        client.list_files(alpha_id)

    # Children get tracked …
    assert state_id in tracker.file_ids
    assert idea_id in tracker.file_ids
    # … and so does the parent folder itself, so that adding a NEW child
    # under it (which bumps the parent's modifiedTime in Drive's changes
    # feed) invalidates anything cached against this listing. Without
    # this, freshly-created run folders never invalidated the OppCard
    # cache and run_count / last_activity_at went stale forever.
    assert alpha_id in tracker.file_ids


def test_get_content_records_file_id(client):
    state_id = client._inner.file_id("ACE/alpha/run_state.yaml")
    with TouchedFileTracker() as tracker:
        client.get_content(state_id, "application/x-yaml")
    assert state_id in tracker.file_ids


def test_pairs_records_modified_time(client):
    """The tracker yields (file_id, modified_time) pairs for fingerprinting."""
    client._inner.set_modified_time("ACE/alpha/run_state.yaml", "2026-05-08T12:00:00Z")
    state_id = client._inner.file_id("ACE/alpha/run_state.yaml")

    with TouchedFileTracker() as tracker:
        client.list_files(client._inner.folder_id("ACE/alpha"))

    pairs = dict(tracker.pairs())
    assert pairs[state_id] == "2026-05-08T12:00:00Z"


def test_nested_with_blocks_track_independently(client):
    alpha_id = client._inner.folder_id("ACE/alpha")
    with TouchedFileTracker() as outer:
        client.list_files(alpha_id)
        outer_count = len(outer.file_ids)
        with TouchedFileTracker() as inner:
            client.list_files(alpha_id)
            assert current_tracker() is inner  # while in inner block
        assert inner.file_ids == outer.file_ids
        assert current_tracker() is outer  # outer restored after inner exit
    assert current_tracker() is None  # both blocks exited
    # outer didn't double-count its work
    assert len(outer.file_ids) == outer_count
