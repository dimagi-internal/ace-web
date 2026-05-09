"""Tests for apps.opps.snapshot_cache."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core.cache import cache

from apps.opps import snapshot_cache

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _flush_cache():
    cache.clear()
    yield
    cache.clear()


@dataclass
class _MockSnapshot:
    """Stands in for OppSnapshot — only needs to be picklable + dataclass."""
    slug: str
    payload: str
    files: list[tuple[str, str]]  # (file_id, modified_time)


@dataclass
class _MockCard:
    """Stands in for OppCard — module-level so it's picklable."""
    slug: str


def _files(*pairs: tuple[str, str]) -> list[tuple[str, str]]:
    return list(pairs)


def test_get_returns_none_when_unset():
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id=None) is None


def test_set_then_get_round_trip():
    snap = _MockSnapshot("alpha", "p", _files(("f1", "2026-01-01")))
    snapshot_cache.set(
        workspace_id=1, slug="alpha", run_id="r1", snap=snap,
        file_ids={"f1"},
    )
    got = snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1")
    assert got == snap


def test_invalidate_drops_matching_snapshot():
    snap = _MockSnapshot("alpha", "p", _files(("f1", "t1")))
    snapshot_cache.set(
        workspace_id=1, slug="alpha", run_id="r1", snap=snap,
        file_ids={"f1", "f2"},
    )

    snapshot_cache.invalidate({"f2"})
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1") is None


def test_invalidate_only_drops_intersecting_keys():
    snap_a = _MockSnapshot("alpha", "a", _files(("f1", "t1")))
    snap_b = _MockSnapshot("beta", "b", _files(("f3", "t3")))
    snapshot_cache.set(
        workspace_id=1, slug="alpha", run_id="r1", snap=snap_a, file_ids={"f1", "f2"}
    )
    snapshot_cache.set(workspace_id=1, slug="beta", run_id="r1", snap=snap_b, file_ids={"f3"})

    snapshot_cache.invalidate({"f2"})
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1") is None
    assert snapshot_cache.get(workspace_id=1, slug="beta", run_id="r1") == snap_b


def test_invalidate_unrelated_file_id_is_noop():
    snap = _MockSnapshot("alpha", "p", _files())
    snapshot_cache.set(workspace_id=1, slug="alpha", run_id="r1", snap=snap, file_ids={"f1"})

    snapshot_cache.invalidate({"unknown-file"})
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1") == snap


def test_card_get_set_round_trip():
    c = _MockCard("alpha")
    snapshot_cache.set_card(workspace_id=1, slug="alpha", card=c, file_ids={"fc1"})
    assert snapshot_cache.get_card(1, "alpha") == c

    snapshot_cache.invalidate({"fc1"})
    assert snapshot_cache.get_card(1, "alpha") is None


def test_clear_workspace_drops_all_keys_for_that_workspace():
    snap_a = _MockSnapshot("alpha", "a", _files())
    snap_b = _MockSnapshot("beta", "b", _files())
    snapshot_cache.set(workspace_id=1, slug="alpha", run_id="r1", snap=snap_a, file_ids={"f1"})
    snapshot_cache.set(workspace_id=1, slug="beta", run_id="r1", snap=snap_b, file_ids={"f2"})
    snapshot_cache.set(workspace_id=2, slug="gamma", run_id="r1", snap=snap_a, file_ids={"f3"})

    snapshot_cache.clear_workspace(1)
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1") is None
    assert snapshot_cache.get(workspace_id=1, slug="beta", run_id="r1") is None
    assert snapshot_cache.get(workspace_id=2, slug="gamma", run_id="r1") == snap_a


def test_fingerprint_is_stable():
    fp1 = snapshot_cache.fingerprint([("f1", "t1"), ("f2", "t2")])
    fp2 = snapshot_cache.fingerprint([("f2", "t2"), ("f1", "t1")])  # different order
    assert fp1 == fp2  # sorted internally


def test_fingerprint_changes_when_modified_time_changes():
    fp1 = snapshot_cache.fingerprint([("f1", "t1")])
    fp2 = snapshot_cache.fingerprint([("f1", "t2")])
    assert fp1 != fp2


def test_invalidate_falls_back_when_reverse_index_missing():
    """If the reverse index is gone (Redis eviction), invalidation falls
    back to the inline file_ids stored on each snapshot value."""
    snap = _MockSnapshot("alpha", "p", _files())
    snapshot_cache.set(workspace_id=1, slug="alpha", run_id="r1", snap=snap, file_ids={"f1"})

    # Simulate reverse-index loss.
    cache.delete("opp:idx:v1:f1")

    snapshot_cache.invalidate({"f1"})
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1") is None
