"""Tests for ``load_scorecard`` — the opp-eval umbrella reader.

Pins the fast-path added for issue #467: when an opp has no ``scorecards/``
or ``verdicts/`` subfolder at its root, the reader returns an empty snapshot
without doing a recursive walk over the opp's runs/, app-summaries/, etc.
On a real opp that recursive walk costs 5-12s and returns null for the
common case (most opps haven't been opp-eval'd yet).
"""
from __future__ import annotations

import pytest

from apps.opps.sync import load_scorecard
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    opp_with_scorecard_tree,
    turmeric_multi_run_tree,
)


class _CountingFakeDrive(FakeDriveClient):
    """FakeDrive wrapper that counts list_files calls + tracks recursive listings."""

    def __init__(self):
        super().__init__()
        self.list_calls: list[tuple[str, bool]] = []  # (folder_id, recursive)

    def list_files(self, folder_id, recursive=False, page_size=100):  # type: ignore[override]
        self.list_calls.append((folder_id, recursive))
        return super().list_files(folder_id, recursive=recursive, page_size=page_size)

    @classmethod
    def from_tree(cls, tree: dict):
        client = cls()
        client._load(client._root, tree)
        return client


def test_load_scorecard_returns_empty_when_no_opp_eval_artifacts():
    """Opp with no ``scorecards/`` or ``verdicts/`` at root → empty snapshot."""
    # turmeric_multi_run_tree puts verdicts/ under runs/<rid>/, NOT at the
    # opp root. So opp-eval files at the root level don't exist.
    client = FakeDriveClient.from_tree(turmeric_multi_run_tree())
    ace_id = client.folder_id("ACE")

    sc = load_scorecard(client, ace_folder_id=ace_id, slug="turmeric")

    assert sc.latest_verdict is None
    assert sc.latest_verdict_variant is None
    assert sc.latest_scorecard_path is None
    assert sc.latest_scorecard_body == ""
    assert sc.trend_path is None
    assert sc.trend_body == ""


def test_load_scorecard_fast_path_skips_recursive_tree_walk():
    """Issue #467: when no opp-eval artifacts exist, don't recurse the tree.

    The historical implementation called ``list_files(opp_folder.id,
    recursive=True)`` unconditionally — a 5-12s round-trip on real opps. The
    fast-path lists the opp's immediate children, sees no scorecards/ or
    verdicts/ subfolder, and returns immediately. This test pins the call
    shape so that a future "simplify" doesn't regress to the slow path.
    """
    client = _CountingFakeDrive.from_tree(turmeric_multi_run_tree())
    ace_id = client.folder_id("ACE")

    load_scorecard(client, ace_folder_id=ace_id, slug="turmeric")

    # The opp has no scorecards/ or verdicts/ at root → no recursive call
    # anywhere in the listing log.
    recursive_calls = [c for c in client.list_calls if c[1] is True]
    assert recursive_calls == [], (
        f"Fast-path should not recurse, but saw: {recursive_calls}"
    )


def test_load_scorecard_recurses_only_into_scorecard_and_verdict_folders():
    """When opp-eval artifacts DO exist, recursive walks are scoped to
    just ``scorecards/`` + ``verdicts/`` — not the whole opp tree.
    """
    client = _CountingFakeDrive.from_tree(opp_with_scorecard_tree())
    ace_id = client.folder_id("ACE")
    opp_id = client.folder_id("ACE/cholera-smoketest")
    scorecards_id = client.folder_id("ACE/cholera-smoketest/scorecards")
    verdicts_id = client.folder_id("ACE/cholera-smoketest/verdicts")

    load_scorecard(client, ace_folder_id=ace_id, slug="cholera-smoketest")

    recursive_folder_ids = {fid for fid, recursive in client.list_calls if recursive}

    # Recursion is scoped to the opp-eval subfolders, NOT the opp root.
    assert opp_id not in recursive_folder_ids
    assert recursive_folder_ids <= {scorecards_id, verdicts_id}


def test_load_scorecard_happy_path_reads_verdict_and_scorecard_body():
    """End-to-end: opp with opp-eval artifacts returns populated snapshot."""
    client = FakeDriveClient.from_tree(opp_with_scorecard_tree())
    ace_id = client.folder_id("ACE")

    sc = load_scorecard(client, ace_folder_id=ace_id, slug="cholera-smoketest")

    assert sc.latest_verdict is not None
    assert sc.latest_verdict_variant == "deep"
    assert sc.latest_verdict.score == 82
    assert sc.latest_verdict.passed is True
    assert sc.latest_scorecard_path == "scorecards/2026-04-15-opp-eval-deep.md"
    assert "Overall: **82/100**" in sc.latest_scorecard_body
    assert sc.trend_path == "scorecards/trend.md"
    assert "opp-eval trend" in sc.trend_body


def test_load_scorecard_raises_for_missing_opp():
    client = FakeDriveClient.from_tree(turmeric_multi_run_tree())
    ace_id = client.folder_id("ACE")

    with pytest.raises(FileNotFoundError):
        load_scorecard(client, ace_folder_id=ace_id, slug="no-such-opp")
