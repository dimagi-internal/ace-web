"""Tests for ``apps/opps/freshness_overlays.py``.

Coverage targets — one per acceptance criterion in #495:

  1. Per-overlay: cache-hit overlay surfaces newly-added Drive children.
  2. Per-overlay: Drive failure preserves the cached value (no
     empty-list regressions on transient Drive blips).
  3. Integration: full ``load_opp_snapshot`` / ``load_rich_opp_snapshot``
     cache-hit path applies ALL overlays in order, mutating each
     listing-derived field.
  4. Performance guard: total Drive ``list_folder`` calls on a cache hit
     equals exactly ``len(OVERLAYS)`` (no n+1 from future overlays
     accidentally walking deeper).

The list_opp_runs path is stubbed at ``apps.opps.sync.list_opp_runs`` —
that's the same monkeypatch target the #484 tests use, so an overlay
implemented in terms of list_opp_runs continues to surface in test
output.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixture helpers — synthesize minimal OppSnapshot / OppCard dataclasses
# ---------------------------------------------------------------------------


def _make_run_summary(run_id: str, folder_id: str | None = None):
    from apps.opps.sync import RunSummary

    return RunSummary(
        run_id=run_id,
        folder_id=folder_id or f"folder-{run_id}",
        current_phase="design",
        current_step=None,
        mode="default",
        last_actor="ace@dimagi-ai.com",
        last_actor_at="2026-05-15T16:00:00Z",
        lifecycle_status="in_progress",
        phases_total=10,
        phases_done=2,
        latest_phase_done="idea-to-pdd",
    )


def _make_snapshot(slug: str = "opp-1", runs: list | None = None):
    from apps.opps.parsers import OppManifest
    from apps.opps.sync import OppSnapshot, RunDetail

    if runs is None:
        runs = [_make_run_summary("20260515-1600")]
    return OppSnapshot(
        opp=OppManifest(
            slug=slug,
            display_name=slug,
            created_at=None,
            created_by=None,
            labels=[],
            current_run_id=runs[0].run_id if runs else None,
        ),
        pdd_body="",
        opp_folder_id=f"opp-folder-{slug}",
        current_run=RunDetail(
            run_id=runs[0].run_id if runs else "r1",
            mode="default",
            status="ok",
            started_at=None,
            completed_at=None,
            current_phase="design",
            current_step=None,
            skill_versions={},
            notes="",
            steps=[],
            folder_id="folder-current",
            decisions=[],
        ),
        runs_summary=list(runs),
    )


def _make_card(slug: str = "opp-1", run_count: int = 1):
    from apps.opps.parsers import OppManifest
    from apps.opps.sync import OppCard

    return OppCard(
        opp=OppManifest(
            slug=slug,
            display_name=slug,
            created_at=None,
            created_by=None,
            labels=[],
            current_run_id="20260515-1600",
        ),
        current_phase=None,
        current_step=None,
        status="ok",
        eval_score=None,
        eval_passed=None,
        last_activity_at=None,
        run_count=run_count,
    )


# ---------------------------------------------------------------------------
# 1. Per-overlay: surface a newly-added child
# ---------------------------------------------------------------------------


def test_runs_summary_overlay_surfaces_new_run(monkeypatch):
    """Cache-hit overlay sees a run that wasn't in the cached
    runs_summary — proves the registry actually re-lists ``<opp>/runs/``
    rather than serving the stale cached list."""
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    snap = _make_snapshot(runs=[_make_run_summary("20260515-1600")])

    fresh_runs = [
        _make_run_summary("20260517-1829", folder_id="folder-new"),
        _make_run_summary("20260515-1600"),
    ]
    calls = {"list_opp_runs": 0}

    def _fake_list_opp_runs(client, *, ace_root_folder_id, opp_slug, opp_children=None):
        calls["list_opp_runs"] += 1
        return list(fresh_runs)

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _fake_list_opp_runs)

    class _StubClient:
        # cold_load_client returns CachedDriveClient wrapping this stub,
        # but list_opp_runs is itself stubbed so the inner client is never
        # actually invoked.
        _inner = None

    apply_freshness_overlays(
        snap, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    assert {r.run_id for r in snap.runs_summary} == {
        "20260517-1829", "20260515-1600",
    }
    assert calls["list_opp_runs"] == 1


def test_run_count_overlay_surfaces_new_count(monkeypatch):
    """Card overlay sees that runs/ has grown to N folders and updates
    the cached run_count from 1 → N."""
    from apps.opps.freshness_overlays import (
        CARD_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    card = _make_card(run_count=1)

    fresh_runs = [
        _make_run_summary("20260517-1829"),
        _make_run_summary("20260516-1200"),
        _make_run_summary("20260515-1600"),
    ]

    def _fake_list_opp_runs(client, *, ace_root_folder_id, opp_slug, opp_children=None):
        return list(fresh_runs)

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _fake_list_opp_runs)

    class _StubClient:
        _inner = None

    apply_freshness_overlays(
        card, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=CARD_OVERLAYS,
    )

    assert card.run_count == 3


# ---------------------------------------------------------------------------
# 2. Per-overlay: Drive failure preserves the cached value
# ---------------------------------------------------------------------------


def test_runs_summary_overlay_drive_failure_preserves_cached(monkeypatch):
    """If the Drive re-listing raises, the cached runs_summary survives
    — empty-dropdown regressions are explicitly the failure mode we're
    avoiding (#484)."""
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    cached_runs = [_make_run_summary("20260515-1600")]
    snap = _make_snapshot(runs=cached_runs)

    def _boom(*args, **kwargs):
        raise RuntimeError("drive down")

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _boom)

    class _StubClient:
        _inner = None

    apply_freshness_overlays(
        snap, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    # Cached value preserved exactly.
    assert [r.run_id for r in snap.runs_summary] == ["20260515-1600"]


def test_runs_summary_overlay_empty_listing_preserves_cached(monkeypatch):
    """An empty list back from Drive is treated as "transient blip" and
    does NOT clobber the cached runs_summary. Symmetry with #484: an
    intermittent failure must never produce an empty dropdown."""
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    cached_runs = [_make_run_summary("20260515-1600")]
    snap = _make_snapshot(runs=cached_runs)

    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs",
        lambda *args, **kwargs: [],
    )

    class _StubClient:
        _inner = None

    apply_freshness_overlays(
        snap, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    assert [r.run_id for r in snap.runs_summary] == ["20260515-1600"]


def test_run_count_overlay_drive_failure_preserves_cached(monkeypatch):
    """Same posture for the card.run_count overlay — a Drive failure
    must not zero out the count."""
    from apps.opps.freshness_overlays import (
        CARD_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    card = _make_card(run_count=3)

    def _boom(*args, **kwargs):
        raise RuntimeError("drive down")

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _boom)

    class _StubClient:
        _inner = None

    apply_freshness_overlays(
        card, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=CARD_OVERLAYS,
    )

    assert card.run_count == 3


def test_apply_freshness_overlays_continues_after_single_overlay_failure(monkeypatch):
    """A single failing overlay must not abort the rest of the walk.

    Construct a registry where the first overlay raises and the second
    succeeds; assert the second still mutates the snapshot.
    """
    from apps.opps.freshness_overlays import (
        FreshnessOverlay,
        OverlayContext,
        apply_freshness_overlays,
    )

    snap = _make_snapshot()

    def _boom(*args, **kwargs):
        raise RuntimeError("first overlay broke")

    def _ok_fetch(client, snapshot, context):
        return [_make_run_summary("new-run")]

    def _ok_apply(snapshot, fresh):
        snapshot.runs_summary = fresh

    overlays = [
        FreshnessOverlay(name="first", fetch_fn=_boom, apply_fn=_ok_apply),
        FreshnessOverlay(name="second", fetch_fn=_ok_fetch, apply_fn=_ok_apply),
    ]

    apply_freshness_overlays(
        snap, object(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=overlays,
    )

    assert [r.run_id for r in snap.runs_summary] == ["new-run"]


# ---------------------------------------------------------------------------
# 3. Integration: full load_opp_snapshot cache-hit applies the registry
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_load_rich_opp_snapshot_cache_hit_applies_registry(monkeypatch, db):
    """The cache-hit branch of ``load_rich_opp_snapshot`` must walk
    SNAPSHOT_OVERLAYS — proves the migration of #494's one-off into the
    registry is wired up end-to-end."""
    from apps.opps import access, snapshot_cache
    from apps.opps.api import load_rich_opp_snapshot

    user = User.objects.create_user(
        email=f"int-{id(monkeypatch)}@example.com",
    )
    workspace = Workspace.objects.filter(created_by=user).first()
    if workspace is None:
        workspace = Workspace.objects.first()

    stale_run = _make_run_summary("20260515-1600", folder_id="folder-stale")
    snap = _make_snapshot(runs=[stale_run])

    snapshot_cache.set(
        workspace_id=workspace.pk,
        slug="opp-1",
        run_id="20260515-1600",
        snap=snap,
        file_ids={"opp-folder-opp-1"},
    )

    class _StubDrive:
        pass

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace=None: _StubDrive(),
    )
    monkeypatch.setattr(
        "apps.opps.drive_changes.observe", lambda workspace, client: set(),
    )

    fresh_runs = [
        _make_run_summary("20260518-1100", folder_id="folder-new"),
        stale_run,
    ]
    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs",
        lambda client, **kwargs: list(fresh_runs),
    )
    monkeypatch.setattr(
        access, "overlay_workspace_display_name",
        lambda manifest, slug, workspace=None: None,
    )

    payload = load_rich_opp_snapshot(
        workspace, "opp-1", run_id="20260515-1600",
    )
    assert payload is not None
    run_ids = {r["run_id"] for r in payload["runs"]}
    assert "20260518-1100" in run_ids
    assert "20260515-1600" in run_ids


# ---------------------------------------------------------------------------
# 4. Performance guard — no n+1 drift
# ---------------------------------------------------------------------------


def test_apply_freshness_overlays_drive_call_count_matches_overlays(monkeypatch):
    """Total Drive folder-listing calls per cache-hit equals
    ``len(SNAPSHOT_OVERLAYS)``. If a future overlay accidentally walks
    deeper and lists more folders, this test fails and forces the author
    to either justify the extra call or factor it out.

    We count Drive calls by counting invocations of
    ``apps.opps.sync.list_opp_runs`` — the only Drive entry point any
    listing-derived overlay uses today. Each overlay calls list_opp_runs
    exactly once.
    """
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    snap = _make_snapshot()

    calls = {"list_opp_runs": 0}

    def _counting_list(*args, **kwargs):
        calls["list_opp_runs"] += 1
        return [_make_run_summary("20260518-1100")]

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _counting_list)

    class _StubClient:
        _inner = None

    apply_freshness_overlays(
        snap, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    assert calls["list_opp_runs"] == len(SNAPSHOT_OVERLAYS), (
        f"Drive calls ({calls['list_opp_runs']}) exceeded the overlay "
        f"count ({len(SNAPSHOT_OVERLAYS)}). Either factor the extra call "
        f"out or update this perf guard with a justification."
    )


def test_card_overlay_drive_call_count_matches_overlays(monkeypatch):
    """Same perf guard for ``CARD_OVERLAYS``."""
    from apps.opps.freshness_overlays import (
        CARD_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    card = _make_card()

    calls = {"list_opp_runs": 0}

    def _counting_list(*args, **kwargs):
        calls["list_opp_runs"] += 1
        return [_make_run_summary("20260518-1100")]

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _counting_list)

    class _StubClient:
        _inner = None

    apply_freshness_overlays(
        card, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=CARD_OVERLAYS,
    )

    assert calls["list_opp_runs"] == len(CARD_OVERLAYS)


# ---------------------------------------------------------------------------
# Context handling
# ---------------------------------------------------------------------------


def test_apply_freshness_overlays_no_context_no_ops(monkeypatch):
    """Calling without a context (or with empty ace_folder_id/slug)
    must NOT crash and must NOT mutate the snapshot — overlays should
    silently no-op when they don't have what they need."""
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        apply_freshness_overlays,
    )

    snap = _make_snapshot()
    original_runs = list(snap.runs_summary)

    boom_called = {"n": 0}

    def _boom(*args, **kwargs):
        boom_called["n"] += 1
        raise RuntimeError("should not be called")

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _boom)

    class _StubClient:
        _inner = None

    # Default context (empty strings) should make overlays skip without
    # calling Drive.
    apply_freshness_overlays(
        snap, _StubClient(), overlays=SNAPSHOT_OVERLAYS,
    )

    assert boom_called["n"] == 0
    assert [r.run_id for r in snap.runs_summary] == [
        r.run_id for r in original_runs
    ]
