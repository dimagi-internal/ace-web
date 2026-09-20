"""Tests for ``apps/opps/freshness_overlays.py``.

Coverage targets:

  1. Per-overlay: cache-hit overlay surfaces newly-added Drive children
     (snapshot only — see (5) for why card overlays were removed).
  2. Per-overlay: Drive failure preserves the cached value (no
     empty-list regressions on transient Drive blips).
  3. Integration: full ``load_opp_snapshot`` / ``load_rich_opp_snapshot``
     cache-hit path applies ALL snapshot overlays in order, mutating each
     listing-derived field.
  4. Performance guard: total Drive ``list_folder`` calls on a cache hit
     equals exactly ``len(SNAPSHOT_OVERLAYS)`` for snapshots and 0 for
     ``CARD_OVERLAYS`` (no n+1 from future overlays accidentally walking
     deeper, no N-fanout on the list view).
  5. Regression for #510 — the Opps-list path never fans out per-opp
     Drive list calls on a cache hit.

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


class _FolderStub:
    """Minimal client serving ``<opp>/runs/<run folders>``.

    ``cold_load_client`` wraps this in ``CachedDriveClient(bypass=True)``,
    whose ``list_folder`` forwards to ``list_files``. Records every folder
    id it was asked to list so tests can count round-trips.
    """

    _inner = None

    def __init__(self, run_names: list[str], *, opp_folder_id: str = "opp-folder-opp-1"):
        self.run_names = list(run_names)
        self.opp_folder_id = opp_folder_id
        self.listed: list[str] = []

    def list_files(self, folder_id, recursive=False, page_size=100):
        from apps.opps.drive_client import DriveFile
        from apps.opps.framework_reader import FOLDER_MIME

        self.listed.append(folder_id)
        if folder_id == self.opp_folder_id:
            return [DriveFile(
                id="runs-folder", name="runs",
                mime_type=FOLDER_MIME, web_view_link="",
            )]
        if folder_id == "runs-folder":
            return [
                DriveFile(
                    id=f"folder-{n}", name=n,
                    mime_type=FOLDER_MIME, web_view_link="",
                )
                for n in self.run_names
            ]
        return []


@pytest.fixture(autouse=True)
def _clear_cache():
    """The overlay remembers folder-name sets and folder ids in the cache;
    leaking one between tests would let a later test skip its rebuild."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


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

    apply_freshness_overlays(
        snap, _FolderStub(["20260515-1600", "20260517-1829"]),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    assert {r.run_id for r in snap.runs_summary} == {
        "20260517-1829", "20260515-1600",
    }
    assert calls["list_opp_runs"] == 1


def test_card_overlays_registry_is_empty():
    """CARD_OVERLAYS is deliberately empty as of #510 / #511.

    The list view (``list_opp_cards``) renders N cards per request; any
    overlay registered here fans out to N parallel Drive listings on every
    page load. The freshness-overlay rule of thumb is documented in the
    module docstring: overlays are appropriate for fields visible to ONE
    cached item per request (workbench detail), not N (list views).

    If you're tempted to add an overlay here, ask: is this field rendered
    across N opps at once? If yes, prefer the cached value. The Drive
    Changes API correctly invalidates underlying card caches when existing
    files inside the opp folder are touched, which covers the normal-use
    refresh path.
    """
    from apps.opps.freshness_overlays import CARD_OVERLAYS

    assert CARD_OVERLAYS == [], (
        "CARD_OVERLAYS must stay empty — N-fanout on the Opps list view "
        "regresses page load to 8-12s+ (see #510). If you have a real "
        "card-level staleness bug, document the trade in the module "
        "docstring AND the drive-changes-api-parent-folder-blind-spot "
        "learning before registering an overlay here."
    )


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

    apply_freshness_overlays(
        snap, _FolderStub(["20260515-1600", "20260517-1829"]),
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

    apply_freshness_overlays(
        snap, _FolderStub(["20260515-1600", "20260517-1829"]),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    assert [r.run_id for r in snap.runs_summary] == ["20260515-1600"]


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

    # Serves <opp>/runs/ so the overlay's probe listing sees the new run
    # folder and decides a rebuild is warranted.
    _StubDrive = lambda: _FolderStub(  # noqa: E731
        ["20260515-1600", "20260518-1100"],
    )

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


def test_runs_summary_overlay_steady_state_is_one_listing(monkeypatch):
    """The overlay's real budget: ONE Drive listing when nothing changed.

    This guard replaces one that monkeypatched ``list_opp_runs`` and
    asserted it was called once. That measured the wrong thing — the
    loader costs ~10 uncached Drive round-trips, so a guard that stubs it
    out reads 10 as 1. Between 2026-05 and 2026-09 that hid the bulk of an
    8-9 second warm Workbench load. Count round-trips at the CLIENT, and
    make the second request the one under test: the first legitimately
    rebuilds, every one after it should be nearly free.
    """
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    runs = ["20260515-1600"]
    loader_calls = {"n": 0}

    def _counting_loader(*args, **kwargs):
        loader_calls["n"] += 1
        return [_make_run_summary("20260515-1600")]

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _counting_loader)
    client = _FolderStub(runs)
    ctx = OverlayContext(ace_folder_id="ace-root", slug="opp-1")

    apply_freshness_overlays(
        _make_snapshot(), client, context=ctx, overlays=SNAPSHOT_OVERLAYS,
    )
    first_listings = len(client.listed)
    client.listed.clear()

    apply_freshness_overlays(
        _make_snapshot(), client, context=ctx, overlays=SNAPSHOT_OVERLAYS,
    )

    assert loader_calls["n"] == 1, (
        f"list_opp_runs ran {loader_calls['n']} times across two cache hits "
        f"with an unchanged runs/ folder. It must run only when the set of "
        f"run folders actually changed — it costs ~10 Drive round-trips."
    )
    assert client.listed.count("runs-folder") == 1, (
        f"runs_summary cost {client.listed.count('runs-folder')} listings of "
        f"runs/ on a steady-state cache hit {client.listed}; budget is 1."
    )
    assert len(client.listed) == 2, (
        f"the whole registry cost {len(client.listed)} Drive listings "
        f"{client.listed} on a steady-state cache hit. Budget is 2: one "
        f"runs/ listing for runs_summary (the runs-folder id itself is "
        f"cached after the first hit) and one opp-folder listing for "
        f"saved_overrides. The first hit cost {first_listings}, which is "
        f"fine — that one rebuilds."
    )


def test_runs_summary_overlay_rebuilds_when_a_run_folder_appears(monkeypatch):
    """The cheap path must not blind the overlay to the thing it exists for."""
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    known = [_make_run_summary("20260515-1600")]
    fresh = {"rows": list(known)}
    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs", lambda *a, **k: list(fresh["rows"]),
    )
    client = _FolderStub(["20260515-1600"])
    ctx = OverlayContext(ace_folder_id="ace-root", slug="opp-1")

    snap = _make_snapshot(runs=known)
    apply_freshness_overlays(snap, client, context=ctx, overlays=SNAPSHOT_OVERLAYS)

    # Orchestration on another machine creates a new run folder.
    client.run_names.append("20260519-0900")
    fresh["rows"] = [_make_run_summary("20260519-0900"), *known]

    snap = _make_snapshot(runs=known)
    apply_freshness_overlays(snap, client, context=ctx, overlays=SNAPSHOT_OVERLAYS)

    assert {r.run_id for r in snap.runs_summary} == {
        "20260515-1600", "20260519-0900",
    }


def test_half_initialised_run_folder_does_not_rebuild_forever(monkeypatch):
    """A run folder with no ``run_state.yaml`` never reaches runs_summary.

    Comparing the listing against the cached summary's run_ids would then
    differ on every single request and rebuild forever — the exact cost this
    change removes. The overlay compares against the folder-name set it last
    rebuilt from instead, which is stable.
    """
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    loader_calls = {"n": 0}

    def _loader(*args, **kwargs):
        loader_calls["n"] += 1
        return [_make_run_summary("20260515-1600")]  # the half-built one is skipped

    monkeypatch.setattr("apps.opps.sync.list_opp_runs", _loader)
    client = _FolderStub(["20260515-1600", "20260520-1200-half-built"])
    ctx = OverlayContext(ace_folder_id="ace-root", slug="opp-1")

    for _ in range(4):
        apply_freshness_overlays(
            _make_snapshot(), client, context=ctx, overlays=SNAPSHOT_OVERLAYS,
        )

    assert loader_calls["n"] == 1


def test_saved_overrides_overlay_listing_budget(monkeypatch):
    """``saved_overrides`` (#673 PR 2) does at most two ``list_files`` calls
    (opp folder → find ``inputs/``, then ``inputs/`` itself) plus one content
    read — through the request's 30s-TTL caching client, so the steady-state
    per-request cost is usually zero fresh Drive calls."""
    from apps.opps.freshness_overlays import (
        SNAPSHOT_OVERLAYS,
        OverlayContext,
        apply_freshness_overlays,
    )

    snap = _make_snapshot()
    snap.opp_folder_id = "opp-folder-1"
    calls = {"list_files": 0}

    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs",
        lambda *a, **k: [_make_run_summary("20260518-1100")],
    )

    class _StubClient:
        _inner = None

        def list_files(self, folder_id, recursive=False, page_size=100):
            calls["list_files"] += 1
            return []

    apply_freshness_overlays(
        snap, _StubClient(),
        context=OverlayContext(ace_folder_id="ace-root", slug="opp-1"),
        overlays=SNAPSHOT_OVERLAYS,
    )

    # The runs_summary overlay's own probe listing is counted here too; it
    # finds no runs/ folder on this stub and bails, which is the budget floor.
    assert calls["list_files"] <= 3, (
        f"saved_overrides listing calls ({calls['list_files']}) exceeded "
        f"its budget. Either factor the extra call out or update this perf "
        f"guard with a justification."
    )


def test_card_overlay_zero_drive_calls(monkeypatch):
    """``CARD_OVERLAYS`` is empty as of #510 / #511 — applying it must
    trigger zero Drive list calls. This is the perf-guard that protects
    the Opps-list view from a regressed N-fanout.

    If ``CARD_OVERLAYS`` ever becomes non-empty again, this test fails and
    the author has to either justify the N parallel Drive calls per
    page-load on the Opps list view, or factor out the listing some
    other way.
    """
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

    assert calls["list_opp_runs"] == 0
    assert len(CARD_OVERLAYS) == 0


# ---------------------------------------------------------------------------
# Context handling
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regression: Opps-list view does NOT fan out per-opp Drive list calls (#510)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_opp_cards_does_not_fan_out_per_opp_drive_calls(monkeypatch):
    """Regression for #510.

    PR #497 registered an ``OppCard.run_count`` overlay that re-listed
    ``<opp>/runs/`` on every Opps-list page render. With N opps, this
    fanned out to N parallel ``list_opp_runs`` calls — observed 8-12s
    page loads at N=5, would be unusable at N=50.

    The Opps-list path (``apps.opps.api.list_opp_cards``) must NOT trigger
    any ``list_opp_runs`` call on a cache hit. The card's ``run_count``
    serves from the cached snapshot; the Drive Changes API keeps it
    roughly fresh during normal use, and the workbench detail view's
    ``runs_summary`` overlay recovers the count on next visit when an
    external run lands.
    """
    from apps.opps import snapshot_cache
    from apps.opps.api import list_opp_cards
    from apps.opps.drive_client import DriveFile

    creator = User.objects.create_user(
        email=f"list-card-perf-{id(monkeypatch)}@example.com",
    )
    workspace = Workspace.objects.create(
        slug=f"ws-list-perf-{id(monkeypatch)}",
        display_name="Perf WS",
        drive_root_folder_id="ace-root",
        created_by=creator,
    )

    # Stub the Drive client: root listing returns N opp folders. Each
    # opp's child listing is a single ``opp.yaml`` so it qualifies as an
    # opp without triggering deep recursion.
    n_opps = 5
    opp_folders = [
        DriveFile(
            id=f"opp-folder-{i}",
            name=f"opp-{i}",
            mime_type="application/vnd.google-apps.folder",
            web_view_link="",
        )
        for i in range(n_opps)
    ]

    def _list_files(folder_id):
        if folder_id == "ace-root":
            return list(opp_folders)
        # Each opp folder has an opp.yaml so list_opp_cards considers it
        # a valid opp (the gate at api.py:97-104).
        return [
            DriveFile(
                id=f"{folder_id}-opp-yaml",
                name="opp.yaml",
                mime_type="text/yaml",
                web_view_link="",
            )
        ]

    class _StubDrive:
        def list_files(self, folder_id, recursive=False, page_size=100):
            return _list_files(folder_id)

        def list_folder(self, folder_id):
            return _list_files(folder_id)

    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace=None: _StubDrive(),
    )
    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root",
    )
    monkeypatch.setattr(
        "apps.opps.access.overlay_workspace_display_name",
        lambda manifest, slug, workspace=None: None,
    )
    monkeypatch.setattr(
        "apps.opps.drive_changes.observe", lambda workspace, client: set(),
    )

    # Pre-populate the card cache for all N opps so we hit the cached
    # branch in list_opp_cards (the only branch the run_count overlay
    # used to run on).
    for i in range(n_opps):
        card = _make_card(slug=f"opp-{i}", run_count=1)
        snapshot_cache.set_card(
            workspace_id=workspace.pk,
            slug=f"opp-{i}",
            card=card,
            file_ids={f"opp-folder-{i}"},
        )

    # Sentinel: any call to list_opp_runs is the regression we're guarding
    # against. The list view must never invoke it.
    calls = {"list_opp_runs": 0}

    def _forbidden_list_opp_runs(*args, **kwargs):
        calls["list_opp_runs"] += 1
        return []

    monkeypatch.setattr(
        "apps.opps.sync.list_opp_runs", _forbidden_list_opp_runs,
    )

    cards = list_opp_cards(workspace)

    assert len(cards) == n_opps
    assert calls["list_opp_runs"] == 0, (
        f"Opps-list view triggered {calls['list_opp_runs']} list_opp_runs "
        f"calls — this is the N-fanout regression from #510. The list "
        f"view must never overlay per-card freshness; the cached value "
        f"is the source of truth on the list page."
    )


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
