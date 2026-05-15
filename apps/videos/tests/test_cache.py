"""Tests for the videos cache layer + service-level cache behaviour.

The cache module is just thin wrappers over django.core.cache, so the
service-level "does it actually avoid Drive calls on the hot path" is
the more interesting assertion. We count drive.* calls via mock.spy.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache as django_cache

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import cache, drive, service


SPEC_YAML = "slug: demo\nworkspace: dimagi-team\nname: Demo\n"


@pytest.fixture(autouse=True)
def clear_cache():
    """Each test starts with a clean cache."""
    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)
    return client


@pytest.fixture
def workspace(fake_drive):
    return SimpleNamespace(
        slug="dimagi-team",
        drive_root_folder_id=fake_drive.folder_id("ws-root"),
    )


@pytest.fixture
def seeded(fake_drive, workspace, tmp_path, settings):
    settings.ACE_VIDEOS_ROOT = str(tmp_path)
    layout = drive.resolve_layout(workspace, fake_drive)
    drive.write_spec(layout, fake_drive, "demo", "run-001", SPEC_YAML)
    # Reset cache because resolve_layout / write_spec may have populated it
    # if other code paths cache. (Currently they don't — but be defensive.)
    django_cache.clear()
    return SimpleNamespace(client=fake_drive, workspace=workspace)


# ---------------------------------------------------------------------------
# Primitive get/set/invalidate round-trips
# ---------------------------------------------------------------------------


def test_set_get_spec_roundtrip():
    cache.set_spec("ws", "slug", "run-001", "yaml-body")
    assert cache.get_spec("ws", "slug", "run-001") == "yaml-body"


def test_invalidate_spec_clears():
    cache.set_spec("ws", "slug", "run-001", "yaml")
    cache.invalidate_spec("ws", "slug", "run-001")
    assert cache.get_spec("ws", "slug", "run-001") is None


def test_set_get_runs_roundtrip():
    cache.set_runs("ws", "slug", ["run-001", "run-002"])
    assert cache.get_runs("ws", "slug") == ["run-001", "run-002"]


def test_set_get_slugs_roundtrip():
    cache.set_slugs("ws", ["chc", "mbw"])
    assert cache.get_slugs("ws") == ["chc", "mbw"]


def test_invalidate_program_drops_workspace_slug_list_and_runs():
    cache.set_slugs("ws", ["chc"])
    cache.set_runs("ws", "chc", ["run-001"])
    cache.invalidate_program("ws", "chc")
    assert cache.get_slugs("ws") is None
    assert cache.get_runs("ws", "chc") is None


# ---------------------------------------------------------------------------
# Service-level cache behaviour
# ---------------------------------------------------------------------------


def test_load_program_run_caches_drive_reads(seeded):
    """Second call should not hit Drive (no read_spec call)."""
    rec1 = service.load_program_run(seeded.workspace, "demo", "run-001")
    assert rec1 is not None
    with mock.patch.object(drive, "read_spec") as read_spec:
        rec2 = service.load_program_run(seeded.workspace, "demo", "run-001")
    assert rec2 is not None
    assert rec2.name == "Demo"
    assert read_spec.call_count == 0  # served from cache


def test_list_run_ids_caches(seeded):
    ids1 = service.list_run_ids(seeded.workspace, "demo")
    assert ids1 == ["run-001"]
    with mock.patch.object(drive, "list_run_ids") as list_run_ids:
        ids2 = service.list_run_ids(seeded.workspace, "demo")
    assert ids2 == ["run-001"]
    assert list_run_ids.call_count == 0


def test_apply_edit_invalidates_then_seeds_spec_cache(seeded):
    # Warm the cache.
    service.load_program_run(seeded.workspace, "demo", "run-001")
    assert cache.get_spec("dimagi-team", "demo", "run-001") is not None
    # Edit — should write through cache.
    result = service.apply_edit(
        seeded.workspace, "demo", "run-001",
        {"op": "set-narration", "beatId": "intro", "text": "Hi"},
    )
    assert result.ok, result.message
    cached = cache.get_spec("dimagi-team", "demo", "run-001")
    assert cached is not None
    assert "intro: Hi" in cached


def test_copy_run_invalidates_runs_list(seeded):
    # Seed the cached runs list.
    service.list_run_ids(seeded.workspace, "demo")
    assert cache.get_runs("dimagi-team", "demo") == ["run-001"]
    new_id = service.copy_run(seeded.workspace, "demo", "run-001")
    assert new_id == "run-002"
    # Cache for runs list should be invalidated.
    assert cache.get_runs("dimagi-team", "demo") is None
    # Next call repopulates with both runs.
    ids = service.list_run_ids(seeded.workspace, "demo")
    assert ids == ["run-001", "run-002"]


def test_create_program_invalidates_slugs_list(seeded):
    # Warm the slug list.
    list(service.iter_programs(seeded.workspace))
    assert cache.get_slugs("dimagi-team") == ["demo"]
    # Create a new program — slug list cache should be busted.
    service.create_program_from_spec(
        seeded.workspace, "new-prog",
        "slug: new-prog\nworkspace: dimagi-team\nname: New\n",
    )
    assert cache.get_slugs("dimagi-team") is None
    # Re-list picks up both.
    progs = [p.slug for p in service.iter_programs(seeded.workspace)]
    assert sorted(progs) == ["demo", "new-prog"]
