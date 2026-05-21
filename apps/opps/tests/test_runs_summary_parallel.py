"""Pins parallelism of the per-run ``runs_summary`` cold-load.

Regression test for #516. PR #513 added a per-card ``runs_summary``
field, populated during cold load by reading each run's ``state.yaml``
from Drive. The reads were serial: 5 opps × 3 runs ≈ 15 sequential
Drive calls compounded to 53s observed cold-load wall time on labs.

These tests mock the Drive client with a synthetic per-call latency
(``time.sleep(0.5)``) and assert that the resulting cold-load wall
time matches the parallel shape rather than the serial shape.
Without parallelism, a future refactor that re-serializes the loop
would lengthen these by ``runs × per_call_latency``; the assertions
would fire.

The shapes of the assertions:

  - Per-run inner loop (``_fetch_runs_summary_parallel``):
    N runs × M Drive calls / run × per_call_latency
    serial:   N × M × per_call_latency  (e.g. 6 × 0.05 = 0.30s)
    parallel: M × per_call_latency      (e.g. 2 × 0.05 = 0.10s)

  - Outer per-opp loop (``list_opp_cards``):
    N opps × per-opp work
    serial:   N × per_opp_latency
    parallel: per_opp_latency  (subject to max_workers cap)

The assertions use generous slack (3-4×) to stay non-flaky under
GIL contention while still rejecting a full serialization regression
(which would land 5-10× over the parallel target).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from apps.opps.drive_client import DriveFile, FileContent
from apps.opps.sync import load_opp_card_by_slug


@dataclass
class _Folder:
    id: str
    name: str
    parent: str
    children: list  # list[_File | _Folder]


@dataclass
class _File:
    id: str
    name: str
    parent: str
    body: str = ""
    mime_type: str = "text/plain"


class SlowFakeDrive:
    """Minimal DriveClient that sleeps ``latency`` per network call.

    Mirrors the ``FakeDrive`` in test_sync_multi_run.py but each method
    that would normally hit Drive over HTTP sleeps first to model
    real-world per-call latency. Used to pin parallelism behavior
    without touching the network.
    """

    def __init__(self, root: _Folder, latency: float = 0.05) -> None:
        self._index_by_id: dict[str, _Folder | _File] = {}
        self._build_index(root)
        self._latency = latency
        self.call_count = 0

    def _build_index(self, node) -> None:
        self._index_by_id[node.id] = node
        if isinstance(node, _Folder):
            for c in node.children:
                self._build_index(c)

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        return self.list_files(folder_id, recursive=False)

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        time.sleep(self._latency)
        self.call_count += 1
        node = self._index_by_id.get(folder_id)
        if not isinstance(node, _Folder):
            return []
        out: list[DriveFile] = []

        def walk(parent: _Folder, prefix: str) -> None:
            for c in parent.children:
                mime = (
                    "application/vnd.google-apps.folder"
                    if isinstance(c, _Folder)
                    else c.mime_type
                )
                relpath = f"{prefix}{c.name}"
                out.append(
                    DriveFile(
                        id=c.id,
                        name=c.name,
                        mime_type=mime,
                        parent_id=parent.id,
                        web_view_link=f"https://drive/{c.id}",
                        size_bytes=len(getattr(c, "body", "")) or None,
                        modified_time="2026-05-20T18:30:00Z",
                        path=relpath,
                    )
                )
                if recursive and isinstance(c, _Folder):
                    walk(c, relpath + "/")

        walk(node, "")
        return out

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        time.sleep(self._latency)
        self.call_count += 1
        node = self._index_by_id.get(file_id)
        body = getattr(node, "body", "") if node else ""
        return FileContent(content=body)


def _run_state_body(name: str, phase: str = "ocs", step: str = "ocs-agent-setup") -> str:
    return (
        f"mode: default\n"
        f"phase: {phase}\n"
        f"step: {step}\n"
        f"opportunity: {name}\n"
        f"run_id: {name}\n"
        f"gates: {{}}\n"
        f"initiated_by: ace@dimagi-ai.com\n"
        f"last_actor: ace@dimagi-ai.com\n"
        f"last_actor_at: 2026-05-20T18:30:00Z\n"
    )


def _build_opp_with_n_runs(slug: str, n_runs: int) -> _Folder:
    """Build a multi-run opp folder with ``n_runs`` valid run subfolders."""
    run_folders = []
    for i in range(n_runs):
        # Newest-first sort keys on rf.name, so use descending timestamps.
        run_name = f"20260520-{1830 - i:04d}"
        run_id = f"{slug}-run-{i}"
        run_folders.append(
            _Folder(
                id=run_id,
                name=run_name,
                parent=f"{slug}-runs",
                children=[
                    _File(
                        id=f"{run_id}-state",
                        name="run_state.yaml",
                        parent=run_id,
                        body=_run_state_body(run_name),
                        mime_type="text/yaml",
                    ),
                ],
            )
        )
    return _Folder(
        id=slug,
        name=slug,
        parent="ACE",
        children=[
            _Folder(
                id=f"{slug}-runs",
                name="runs",
                parent=slug,
                children=run_folders,
            ),
            _File(
                id=f"{slug}-opp-yaml",
                name="opp.yaml",
                parent=slug,
                body=f"display_name: {slug.title()}\ncreated_at: 2026-05-20\n",
                mime_type="text/yaml",
            ),
        ],
    )


def _build_workspace(n_opps: int, runs_per_opp: int) -> _Folder:
    return _Folder(
        id="ACE",
        name="ACE",
        parent="",
        children=[
            _build_opp_with_n_runs(f"opp-{i:02d}", runs_per_opp)
            for i in range(n_opps)
        ],
    )


# ---------------------------------------------------------------------------
# Inner per-run loop (load_opp_card)
# ---------------------------------------------------------------------------


def test_load_opp_card_parallelizes_per_run_state_yaml_reads():
    """6 runs × (1 list_files + 1 get_content) per run = 12 inner Drive
    calls. Serially these would add 12 × 0.05 = 0.60s on top of the
    ~5 base calls; parallelized with max_workers=10 they should add
    only ~0.10s (2 sequential calls per worker × per-call latency).

    Pre-parallel (serial) total ≈ 17 × 0.05 = 0.85s.
    Post-parallel total ≈ (5 base + 2 inner) × 0.05 = 0.35s + overhead.

    The 0.55s threshold below comfortably rejects the serial regression
    while leaving 0.20s headroom for thread-start overhead and CI
    noise.
    """
    layout = _Folder(
        id="ACE",
        name="ACE",
        parent="",
        children=[_build_opp_with_n_runs("turmeric", n_runs=6)],
    )
    fake = SlowFakeDrive(layout, latency=0.05)

    t0 = time.monotonic()
    card = load_opp_card_by_slug(fake, ace_folder_id="ACE", slug="turmeric")
    elapsed = time.monotonic() - t0

    assert card.run_count == 6
    assert len(card.runs_summary) == 6
    # newest-first ordering preserved
    assert card.runs_summary[0].run_id == "20260520-1830"
    assert card.runs_summary[-1].run_id == "20260520-1825"

    assert elapsed < 0.55, (
        f"per-run runs_summary loop appears to have serialized: "
        f"{elapsed:.2f}s for 6 runs × 0.05s latency; expected < 0.55s "
        f"(serial floor would be ~0.85s)"
    )


def test_load_opp_card_concurrency_capped():
    """Even with many runs, concurrency is capped at OPPS_RUNS_SUMMARY_MAX_WORKERS.

    Default cap is 10; 20 runs at 0.05s each should land at roughly
    ceil(20/10) × 2 × 0.05 = 0.20s inner-loop cost (each run does
    2 sequential Drive calls; a worker handles ~2 runs in serial),
    plus the ~5 base calls = ~0.45s.

    Serial baseline: 5 base + 40 inner = 45 × 0.05 = 2.25s.
    Threshold of 1.0s rejects serial regression with ample margin.
    """
    layout = _Folder(
        id="ACE",
        name="ACE",
        parent="",
        children=[_build_opp_with_n_runs("turmeric", n_runs=20)],
    )
    fake = SlowFakeDrive(layout, latency=0.05)

    t0 = time.monotonic()
    card = load_opp_card_by_slug(fake, ace_folder_id="ACE", slug="turmeric")
    elapsed = time.monotonic() - t0

    assert card.run_count == 20
    assert elapsed < 1.0, (
        f"20-run parallelization didn't kick in: {elapsed:.2f}s "
        f"(serial would be ~2.25s)"
    )


# ---------------------------------------------------------------------------
# Outer per-opp loop (list_opp_cards)
# ---------------------------------------------------------------------------


import pytest  # noqa: E402


@pytest.mark.django_db
def test_list_opp_cards_parallelizes_cold_per_opp_loads(monkeypatch):
    """5 opps × per-opp cold load. The list_files call on each opp folder
    is the inner Drive read; with serial execution that compounds to
    5 × 0.05 = 0.25s just for the per-opp folder listings. Parallel,
    with max_workers=10, it should land roughly 0.05s + overhead.

    Pre-populating the snapshot cache means we DON'T trigger load_opp_card
    inside the worker (which would add its own parallelized inner loop on
    top); we isolate the outer-loop parallelism test cleanly.

    Generous slack: assert wall time < 0.20s (well under the 0.25s
    serial floor) while leaving room for thread-start overhead.
    """
    from django.contrib.auth import get_user_model

    from apps.opps import snapshot_cache
    from apps.opps.api import list_opp_cards
    from apps.opps.drive_client import DriveFile
    from apps.opps.parsers import OppManifest
    from apps.opps.sync import OppCard
    from apps.workspaces.models import Workspace

    User = get_user_model()
    creator = User.objects.create_user(
        email=f"par-list-{id(monkeypatch)}@example.com",
    )
    workspace = Workspace.objects.create(
        slug=f"ws-par-list-{id(monkeypatch)}",
        display_name="Par WS",
        drive_root_folder_id="ace-root",
        created_by=creator,
    )

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

    per_call_latency = 0.05

    def _list_files(folder_id):
        time.sleep(per_call_latency)
        if folder_id == "ace-root":
            return list(opp_folders)
        # Each opp folder has an opp.yaml so list_opp_cards considers it
        # a valid opp (the gate at api.py).
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

    # Pre-populate the card cache so workers don't fall through to the
    # full cold-load path; this isolates outer-loop parallelism.
    for i in range(n_opps):
        manifest = OppManifest(
            slug=f"opp-{i}",
            display_name=f"Opp {i}",
            current_run_id="r1",
        )
        card = OppCard(
            opp=manifest,
            current_phase=None,
            current_step=None,
            status="ok",
            eval_score=None,
            eval_passed=None,
            last_activity_at=None,
            run_count=1,
        )
        snapshot_cache.set_card(
            workspace_id=workspace.pk,
            slug=f"opp-{i}",
            card=card,
            file_ids={f"opp-folder-{i}"},
        )

    t0 = time.monotonic()
    cards = list_opp_cards(workspace)
    elapsed = time.monotonic() - t0

    assert len(cards) == n_opps
    # Serial baseline: 1 root list_files + 5 per-opp list_files
    # = 6 × 0.05 = 0.30s.
    # Parallel: 1 × 0.05 (root, serial) + 1 × 0.05 (all 5 per-opp
    # list_files concurrent) + thread overhead = ~0.15-0.20s.
    # Threshold rejects full serial (0.30s) with reasonable margin.
    assert elapsed < 0.25, (
        f"list_opp_cards outer loop appears to have serialized: "
        f"{elapsed:.2f}s for {n_opps} opps × {per_call_latency}s latency; "
        f"expected < 0.25s (serial would be ~0.30s)"
    )


@pytest.mark.django_db
def test_list_opp_cards_preserves_ordering(monkeypatch):
    """Parallel execution must NOT reshuffle results — the response order
    follows the Drive root listing order. The frontend doesn't sort the
    cards itself; the API response order is what's rendered."""
    from django.contrib.auth import get_user_model

    from apps.opps import snapshot_cache
    from apps.opps.api import list_opp_cards
    from apps.opps.drive_client import DriveFile
    from apps.opps.parsers import OppManifest
    from apps.opps.sync import OppCard
    from apps.workspaces.models import Workspace

    User = get_user_model()
    creator = User.objects.create_user(
        email=f"par-order-{id(monkeypatch)}@example.com",
    )
    workspace = Workspace.objects.create(
        slug=f"ws-par-order-{id(monkeypatch)}",
        display_name="Order WS",
        drive_root_folder_id="ace-root",
        created_by=creator,
    )

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

    for i in range(n_opps):
        manifest = OppManifest(
            slug=f"opp-{i}",
            display_name=f"Opp {i}",
            current_run_id="r1",
        )
        card = OppCard(
            opp=manifest,
            current_phase=None,
            current_step=None,
            status="ok",
            eval_score=None,
            eval_passed=None,
            last_activity_at=None,
            run_count=1,
        )
        snapshot_cache.set_card(
            workspace_id=workspace.pk,
            slug=f"opp-{i}",
            card=card,
            file_ids={f"opp-folder-{i}"},
        )

    cards = list_opp_cards(workspace)
    slugs = [c.get("slug") or c.get("title") for c in cards]
    # Drive listing order is opp-0..opp-4 — output order must match.
    assert slugs == [f"opp-{i}" for i in range(n_opps)] or slugs == [
        f"Opp {i}" for i in range(n_opps)
    ], f"order shuffled by parallel execution: {slugs}"


def test_load_opp_card_preserves_newest_first_ordering():
    """Parallel execution must NOT reshuffle results. ``runs_summary``
    is newest-first (descending by run-folder name), which matches the
    ordering frontend chips assume."""
    layout = _Folder(
        id="ACE",
        name="ACE",
        parent="",
        children=[_build_opp_with_n_runs("turmeric", n_runs=5)],
    )
    fake = SlowFakeDrive(layout, latency=0.0)  # no latency — just check order
    card = load_opp_card_by_slug(fake, ace_folder_id="ACE", slug="turmeric")
    names = [r.run_id for r in card.runs_summary]
    assert names == sorted(names, reverse=True), (
        f"runs_summary must be newest-first; got {names}"
    )
