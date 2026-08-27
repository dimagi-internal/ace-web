"""Tests for the multi-run-aware structured-layout reader.

Layout being tested:

    ACE/
    ├── turmeric/
    │   ├── inputs/
    │   │   └── pdd.md
    │   ├── runs/
    │   │   ├── 20260502-1830/{run_state.yaml, idea.md, ...}
    │   │   └── 20260502-1430/{run_state.yaml, ...}
    │   └── opp.yaml
    └── ...
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps.drive_client import DriveFile, FileContent
from apps.opps.sync import (
    OppSnapshot,
    list_opp_events_lean,
    list_opp_runs,
    load_opp,
    load_opp_card_by_slug,
)


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


class FakeDrive:
    """Minimal in-memory DriveClient. Just what sync.py uses."""

    def __init__(self, root: _Folder) -> None:
        self._index_by_id = {}
        self._build_index(root)

    def _build_index(self, node) -> None:
        self._index_by_id[node.id] = node
        if isinstance(node, _Folder):
            for c in node.children:
                self._build_index(c)

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        node = self._index_by_id.get(folder_id)
        if not isinstance(node, _Folder):
            return []
        out = []
        for c in node.children:
            mime = (
                "application/vnd.google-apps.folder"
                if isinstance(c, _Folder)
                else c.mime_type
            )
            out.append(
                DriveFile(
                    id=c.id, name=c.name, mime_type=mime,
                    parent_id=folder_id, web_view_link=f"https://drive/{c.id}",
                    size_bytes=len(getattr(c, "body", "")) or None,
                    modified_time="2026-05-02T18:30:00Z",
                    path=c.name,
                )
            )
        return out

    def list_files(self, folder_id: str, recursive: bool = False) -> list[DriveFile]:
        """List files under folder_id. When recursive, walk into subfolders;
        each returned DriveFile.path is the slash-joined path from folder_id."""
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
                        id=c.id, name=c.name, mime_type=mime,
                        parent_id=parent.id,
                        web_view_link=f"https://drive/{c.id}",
                        size_bytes=len(getattr(c, "body", "")) or None,
                        modified_time="2026-05-02T18:30:00Z",
                        path=relpath,
                    )
                )
                if recursive and isinstance(c, _Folder):
                    walk(c, relpath + "/")

        walk(node, "")
        return out

    def get_content(
        self, file_id: str, mime_type: str, *, export_as: str | None = None
    ) -> FileContent:
        node = self._index_by_id.get(file_id)
        body = getattr(node, "body", "") if node else ""
        return FileContent(content=body)


def _build_turmeric_layout() -> _Folder:
    """Two runs under turmeric — newest is 20260502-1830."""
    return _Folder(
        id="ACE", name="ACE", parent="",
        children=[
            _Folder(
                id="turmeric", name="turmeric", parent="ACE",
                children=[
                    _Folder(
                        id="turmeric-inputs", name="inputs", parent="turmeric",
                        children=[
                            _File(
                                id="pdd-input", name="pdd.md", parent="turmeric-inputs",
                                body="# Turmeric PDD\n\n...",
                                mime_type="text/markdown",
                            ),
                        ],
                    ),
                    _Folder(
                        id="turmeric-runs", name="runs", parent="turmeric",
                        children=[
                            _Folder(
                                id="run-1830", name="20260502-1830", parent="turmeric-runs",
                                children=[
                                    _File(
                                        id="state-1830", name="run_state.yaml",
                                        parent="run-1830",
                                        body=(
                                            "mode: default\n"
                                            "phase: ocs\n"
                                            "step: ocs-agent-setup\n"
                                            "opportunity: turmeric\n"
                                            "run_id: 20260502-1830\n"
                                            "gates: {}\n"
                                            "initiated_by: ace@dimagi-ai.com\n"
                                            "last_actor: ace@dimagi-ai.com\n"
                                            "last_actor_at: 2026-05-02T18:42:00Z\n"
                                        ),
                                        mime_type="text/yaml",
                                    ),
                                    _File(
                                        id="idea-1830", name="idea.md",
                                        parent="run-1830",
                                        body="# Turmeric PDD",
                                        mime_type="text/markdown",
                                    ),
                                    _Folder(
                                        id="run-1830-verdicts", name="verdicts",
                                        parent="run-1830",
                                        children=[
                                            _File(
                                                id="verdict-1",
                                                name="idea-to-pdd-deep.yaml",
                                                parent="run-1830-verdicts",
                                                body=(
                                                    "skill: idea-to-pdd\n"
                                                    "verdict: pass\n"
                                                    "overall_score: 87\n"
                                                    "evaluated_at: 2026-05-02T18:35:00Z\n"
                                                ),
                                                mime_type="text/yaml",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            _Folder(
                                id="run-1430", name="20260502-1430", parent="turmeric-runs",
                                children=[
                                    _File(
                                        id="state-1430", name="run_state.yaml",
                                        parent="run-1430",
                                        body=(
                                            "mode: default\n"
                                            "phase: closeout\n"
                                            "step: cycle-grade\n"
                                            "opportunity: turmeric\n"
                                            "run_id: 20260502-1430\n"
                                            "gates: {}\n"
                                            "initiated_by: ace@dimagi-ai.com\n"
                                            "last_actor: ace@dimagi-ai.com\n"
                                            "last_actor_at: 2026-05-02T16:01:00Z\n"
                                        ),
                                        mime_type="text/yaml",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    _File(
                        id="opp-yaml", name="opp.yaml", parent="turmeric",
                        body=(
                            "display_name: Turmeric Market Survey\n"
                            "slug: turmeric\n"
                            "last_run_id: 20260502-1830\n"
                            "tags: []\n"
                            "created_at: 2026-05-02T14:30:00Z\n"
                            "created_by: ace@dimagi-ai.com\n"
                        ),
                        mime_type="text/yaml",
                    ),
                ],
            ),
        ],
    )


def test_list_opp_runs_returns_runs_newest_first():
    fake = FakeDrive(_build_turmeric_layout())
    runs = list_opp_runs(fake, ace_root_folder_id="ACE", opp_slug="turmeric")
    assert [r.run_id for r in runs] == ["20260502-1830", "20260502-1430"]


def test_list_opp_runs_lifecycle_status_in_progress_when_cursor_set():
    fake = FakeDrive(_build_turmeric_layout())
    runs = list_opp_runs(fake, ace_root_folder_id="ACE", opp_slug="turmeric")
    # Both fixture runs have a top-level `phase` cursor → in_progress.
    assert all(r.lifecycle_status == "in_progress" for r in runs)


def test_list_opp_runs_lifecycle_status_in_progress_when_all_phases_pending():
    """Just-kicked-off runs (no cursor, all phases pending) classify as in_progress.

    Reproduces the leep-paint-collection 2026-05-09T22:04 bug where the run
    showed ✓ complete in the Hierarchy view immediately after `/ace:run`
    fired. The frontend used to infer "complete" from "no current_phase +
    has last_actor_at"; that's the same shape a freshly-initialized run
    has, so we now derive an explicit lifecycle_status server-side. With
    the two-state model these still report in_progress — the frontend
    distinguishes "queued (no work yet)" via phases_done==0.
    """
    just_kicked_off_yaml = (
        "opportunity: leep-paint-collection\n"
        "run_id: 20260509-2204\n"
        "mode: default\n"
        "created: 2026-05-10T04:04:35Z\n"
        "last_actor: jjackson@dimagi.com\n"
        "last_actor_at: 2026-05-10T04:04:35Z\n"
        "phases:\n"
        "  design-review:\n"
        "    status: pending\n"
        "    steps:\n"
        "      idea-to-pdd: pending\n"
        "      pdd-to-test-prompts: pending\n"
        "  commcare-setup:\n"
        "    status: pending\n"
        "    steps:\n"
        "      pdd-to-learn-app: pending\n"
    )
    layout = _Folder(
        id="ACE", name="ACE", parent="root",
        children=[
            _Folder(
                id="leep", name="leep-paint-collection", parent="ACE",
                children=[
                    _Folder(
                        id="leep-runs", name="runs", parent="leep",
                        children=[
                            _Folder(
                                id="run-2204", name="20260509-2204", parent="leep-runs",
                                children=[
                                    _File(
                                        id="state-2204", name="run_state.yaml",
                                        parent="run-2204",
                                        body=just_kicked_off_yaml,
                                        mime_type="text/yaml",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    fake = FakeDrive(layout)
    runs = list_opp_runs(
        fake, ace_root_folder_id="ACE", opp_slug="leep-paint-collection",
    )
    assert len(runs) == 1
    r = runs[0]
    assert r.lifecycle_status == "in_progress"
    assert r.phases_done == 0
    assert r.phases_total == 2
    assert r.latest_phase_done is None
    assert r.current_phase is None
    assert r.last_actor_at is not None


def test_list_opp_runs_lifecycle_status_in_progress_between_phases():
    """A run with one phase done and others pending stays in_progress.

    Two-state model: until every phase is done/complete, the run is
    in_progress (no proactive "pause" state). The phase counts +
    latest_phase_done let the UI render "after design-review · 1/2".
    """
    in_progress_yaml = (
        "opportunity: leep-paint-collection\n"
        "run_id: 20260509-1448\n"
        "mode: default\n"
        "last_actor: jjackson@dimagi.com\n"
        "last_actor_at: 2026-05-10T01:35:00Z\n"
        "phases:\n"
        "  design-review:\n"
        "    status: done\n"
        "    completed_at: 2026-05-09T20:56:00Z\n"
        "  commcare-setup:\n"
        "    status: pending\n"
    )
    layout = _Folder(
        id="ACE", name="ACE", parent="root",
        children=[
            _Folder(
                id="leep", name="leep-paint-collection", parent="ACE",
                children=[
                    _Folder(
                        id="leep-runs", name="runs", parent="leep",
                        children=[
                            _Folder(
                                id="run-1448", name="20260509-1448", parent="leep-runs",
                                children=[
                                    _File(
                                        id="state-1448", name="run_state.yaml",
                                        parent="run-1448",
                                        body=in_progress_yaml,
                                        mime_type="text/yaml",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    fake = FakeDrive(layout)
    runs = list_opp_runs(
        fake, ace_root_folder_id="ACE", opp_slug="leep-paint-collection",
    )
    assert len(runs) == 1
    r = runs[0]
    assert r.lifecycle_status == "in_progress"
    assert r.phases_done == 1
    assert r.phases_total == 2
    assert r.latest_phase_done == "design-review"


def test_list_opp_runs_lifecycle_status_complete_when_all_phases_done():
    """All phases done/complete → lifecycle_status == "complete"."""
    fully_done_yaml = (
        "opportunity: leep-paint-collection\n"
        "run_id: 20260503-2128\n"
        "mode: default\n"
        "last_actor: jjackson@dimagi.com\n"
        "last_actor_at: 2026-05-04T03:28:00Z\n"
        "phases:\n"
        "  design-review:\n"
        "    status: complete\n"
        "  commcare-setup:\n"
        "    status: done\n"
    )
    layout = _Folder(
        id="ACE", name="ACE", parent="root",
        children=[
            _Folder(
                id="leep", name="leep-paint-collection", parent="ACE",
                children=[
                    _Folder(
                        id="leep-runs", name="runs", parent="leep",
                        children=[
                            _Folder(
                                id="run-2128", name="20260503-2128", parent="leep-runs",
                                children=[
                                    _File(
                                        id="state-2128", name="run_state.yaml",
                                        parent="run-2128",
                                        body=fully_done_yaml,
                                        mime_type="text/yaml",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    fake = FakeDrive(layout)
    runs = list_opp_runs(
        fake, ace_root_folder_id="ACE", opp_slug="leep-paint-collection",
    )
    assert len(runs) == 1
    r = runs[0]
    assert r.lifecycle_status == "complete"
    assert r.phases_done == 2
    assert r.phases_total == 2
    assert r.latest_phase_done == "commcare-setup"


def test_list_opp_runs_handles_flat_step_shape_without_phase_status():
    """Older run_state.yaml uses ``phase: {step: status, ...}`` directly,
    no ``status:`` field on the phase. We have to derive done-ness from
    step values or otherwise-completed runs (e.g. leep 20260503-2128) read
    as zero-progress and the UI labels them "queued" forever.
    """
    flat_yaml = (
        "opportunity: leep-paint-collection\n"
        "run_id: 20260503-2128\n"
        "mode: default\n"
        "last_actor: jjackson@dimagi.com\n"
        "last_actor_at: 2026-05-04T05:30:00Z\n"
        "phases:\n"
        "  design-review:\n"
        "    idea-to-pdd: done\n"
        "    pdd-to-test-prompts: done\n"
        "  commcare-setup:\n"
        "    pdd-to-learn-app: done\n"
        "    app-screenshot-capture: skipped\n"
        "  llo-management:\n"
        "    llo-invite: pending\n"
        "    llo-onboarding: pending\n"
    )
    layout = _Folder(
        id="ACE", name="ACE", parent="root",
        children=[
            _Folder(
                id="leep", name="leep-paint-collection", parent="ACE",
                children=[
                    _Folder(
                        id="leep-runs", name="runs", parent="leep",
                        children=[
                            _Folder(
                                id="run-2128", name="20260503-2128", parent="leep-runs",
                                children=[
                                    _File(
                                        id="state-2128", name="run_state.yaml",
                                        parent="run-2128",
                                        body=flat_yaml,
                                        mime_type="text/yaml",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    fake = FakeDrive(layout)
    runs = list_opp_runs(
        fake, ace_root_folder_id="ACE", opp_slug="leep-paint-collection",
    )
    assert len(runs) == 1
    r = runs[0]
    # design-review and commcare-setup are fully done (every step done /
    # skipped); llo-management still has pending steps.
    assert r.phases_total == 3
    assert r.phases_done == 2
    assert r.latest_phase_done == "commcare-setup"
    assert r.lifecycle_status == "in_progress"


def test_load_opp_card_uses_opp_yaml_display_name():
    fake = FakeDrive(_build_turmeric_layout())
    card = load_opp_card_by_slug(fake, ace_folder_id="ACE", slug="turmeric")
    assert card.opp.slug == "turmeric"
    assert card.opp.display_name == "Turmeric Market Survey"
    assert card.opp.current_run_id == "20260502-1830"
    assert card.current_phase == "ocs"
    assert card.run_count == 2


def test_load_opp_card_run_count_skips_folders_without_state():
    """A run folder without run_state.yaml (partially deleted or half-
    initialized) must NOT be counted — otherwise the card disagrees with
    the expanded runs list."""
    layout = _build_turmeric_layout()
    runs_folder = next(
        c for c in layout.children[0].children if isinstance(c, _Folder) and c.name == "runs"
    )
    runs_folder.children.append(
        _Folder(
            id="run-orphan", name="20260502-9999", parent="turmeric-runs",
            children=[
                _File(
                    id="orphan-readme", name="README.md", parent="run-orphan",
                    body="started but never wrote run_state.yaml",
                    mime_type="text/markdown",
                ),
            ],
        )
    )
    fake = FakeDrive(layout)
    card = load_opp_card_by_slug(fake, ace_folder_id="ACE", slug="turmeric")
    # 3 folders under runs/, but only 2 have run_state.yaml.
    assert card.run_count == 2
    # And the live runs list agrees.
    runs = list_opp_runs(fake, ace_root_folder_id="ACE", opp_slug="turmeric")
    assert len(runs) == 2


def test_load_opp_returns_default_run_when_no_id_specified():
    fake = FakeDrive(_build_turmeric_layout())
    snap: OppSnapshot = load_opp(fake, ace_root_folder_id="ACE", opp_slug="turmeric")
    assert snap.current_run.run_id == "20260502-1830"
    assert snap.current_run.current_phase == "ocs"


def test_load_opp_loads_specific_run_when_run_id_given():
    fake = FakeDrive(_build_turmeric_layout())
    snap = load_opp(
        fake, ace_root_folder_id="ACE",
        opp_slug="turmeric", run_id="20260502-1430",
    )
    assert snap.current_run.run_id == "20260502-1430"
    assert snap.current_run.current_phase == "closeout"


def test_load_opp_finds_nested_verdict_artifacts():
    """Regression: _load_opp_run must list the run folder recursively.

    Without recursive=True, files in skill subfolders (verdicts/,
    scorecards/, etc.) would not get attributed.
    """
    fake = FakeDrive(_build_turmeric_layout())
    snap = load_opp(fake, ace_root_folder_id="ACE", opp_slug="turmeric")
    # The verdict at verdicts/idea-to-pdd-eval-deep.yaml should be parsed and attached.
    idea_step = next(
        (s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"), None
    )
    assert idea_step is not None, "idea-to-pdd step not found in run snapshot"
    assert idea_step.judge is not None, "verdict was not attached to idea-to-pdd step"
    assert idea_step.judge.score == 87.0


def test_parse_verdict_normalizes_explicit_0_3_scale():
    """Regression: ocs-chatbot-eval emits ``overall_score: 3.0`` with an
    explicit ``scale: "0-3"`` annotation in ``dimensions``. The legacy
    magnitude heuristic in ``normalize_score_pct`` would treat 3.0 as
    a 0-10 score and project to 30/100, which contradicts the YAML's
    own ``verdict: pass``. ``_parse_verdict_yaml`` now reads the
    declared scale and pre-normalizes to 0-100 at parse time so
    downstream sees a coherent score."""
    from apps.opps.sync import _parse_verdict_yaml

    body = (
        "skill: ocs-chatbot-eval\n"
        "overall_score: 3.0\n"
        "verdict: pass\n"
        "dimensions:\n"
        "  overall_quality: { score: 3.0, weight: 1.0, scale: \"0-3\" }\n"
    )
    v = _parse_verdict_yaml(body)
    assert v is not None
    assert v.score == 100.0  # 3 of 3 → 100%
    assert v.passed is True


def test_parse_verdict_falls_back_to_heuristic_without_scale():
    """When the verdict YAML has no explicit scale the parser leaves the
    raw score alone; ``normalize_score_pct`` downstream applies the
    >10/≤10 magnitude heuristic. Verifies the layered behaviour matches
    the legacy contract for unannotated rubrics."""
    from apps.opps.sync import _parse_verdict_yaml

    v = _parse_verdict_yaml("score: 8.5\nverdict: pass\n")
    assert v is not None
    assert v.score == 8.5  # Untouched at parse time.


# NOTE: the unit tests for ace's own ``_attribute_files_to_skills`` (manifest
# matcher + filename-prefix fallback) were removed in the wave-4 single-reader
# swap — that attribution now lives in (and is tested by) the framework lib
# ``canopy_agent_runs.drive.store``. The public chokepoints exercised below
# (``list_opp_runs`` / ``load_opp_card`` / ``load_opp``) remain the ace-side
# parity gate over the framework-sourced read model.


def test_load_opp_attaches_verdicts_at_phase_prefixed_paths():
    """Regression: plugin 0.13.0+ moved verdicts from `verdicts/<skill>.yaml`
    to `<N>-<phase>/<producer>[-eval]_verdict[-variant].yaml`. The reader
    must match both layouts and strip the `-eval` suffix to attach the
    verdict to the target lifecycle skill row.
    """
    fake = FakeDrive(_build_phase_prefixed_layout())
    snap = load_opp(fake, ace_root_folder_id="ACE", opp_slug="turmeric-new")

    idea_step = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd"
    )
    assert idea_step.judge is not None, (
        "1-design/idea-to-pdd-eval_verdict.yaml didn't attach to idea-to-pdd"
    )
    assert idea_step.judge.score == 91.0
    # ocs-chatbot-eval is itself a lifecycle skill (ends in -eval but isn't
    # `-eval`-suffixed against another target). The verdict file name is
    # `ocs-chatbot-eval_verdict-quick.yaml` — producer should resolve to
    # `ocs-chatbot-eval`, not be stripped to `ocs-chatbot`.
    ocs_eval_step = next(
        s for s in snap.current_run.steps
        if s.step.skill_name == "ocs-chatbot-eval"
    )
    assert ocs_eval_step.judge is not None, (
        "self-evaluating ocs-chatbot-eval verdict didn't attach"
    )


def _build_phase_prefixed_layout() -> _Folder:
    """Plugin 0.13.0+ layout: per-run artifacts under `<N>-<phase>/`."""
    return _Folder(
        id="ACE", name="ACE", parent="",
        children=[
            _Folder(
                id="t2", name="turmeric-new", parent="ACE",
                children=[
                    _Folder(
                        id="t2-runs", name="runs", parent="t2",
                        children=[
                            _Folder(
                                id="t2-r1", name="20260506-1304", parent="t2-runs",
                                children=[
                                    _File(
                                        id="t2-state",
                                        name="run_state.yaml",
                                        parent="t2-r1",
                                        body=(
                                            "mode: default\n"
                                            "phase: ocs\n"
                                            "step: ocs-chatbot-eval\n"
                                            "gates: {}\n"
                                        ),
                                        mime_type="text/yaml",
                                    ),
                                    _Folder(
                                        id="t2-design", name="1-design",
                                        parent="t2-r1",
                                        children=[
                                            _File(
                                                id="t2-pdd",
                                                name="idea-to-pdd.md",
                                                parent="t2-design",
                                                body="# PDD\n\nFirst sentence.",
                                                mime_type="text/markdown",
                                            ),
                                            _File(
                                                id="t2-pdd-verdict",
                                                name="idea-to-pdd-eval_verdict.yaml",
                                                parent="t2-design",
                                                body=(
                                                    "verdict: pass\n"
                                                    "overall_score: 91\n"
                                                    "evaluated_at: "
                                                    "2026-05-06T13:10:00Z\n"
                                                ),
                                                mime_type="text/yaml",
                                            ),
                                        ],
                                    ),
                                    _Folder(
                                        id="t2-ocs", name="4-ocs", parent="t2-r1",
                                        children=[
                                            _File(
                                                id="t2-ocs-verdict",
                                                name="ocs-chatbot-eval_verdict-quick.yaml",
                                                parent="t2-ocs",
                                                body=(
                                                    "verdict: pass\n"
                                                    "overall_score: 84\n"
                                                    "evaluated_at: "
                                                    "2026-05-06T13:20:00Z\n"
                                                ),
                                                mime_type="text/yaml",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def test_list_opp_events_lean_descends_into_latest_run():
    """For multi-run-layout opps, verdicts/ lives under runs/<latest>/,
    not at the opp root. The lean event aggregator (used by the activity
    Timeline) must descend into the latest run so its verdicts show up
    in the feed.
    """
    fake = FakeDrive(_build_turmeric_layout())
    verdicts_by_skill = list_opp_events_lean(
        fake, ace_folder_id="ACE", slug="turmeric"
    )
    assert "idea-to-pdd" in verdicts_by_skill
    assert verdicts_by_skill["idea-to-pdd"].score == 87.0
    # PyYAML auto-parses ISO-8601 timestamps into datetime; either string
    # or datetime is acceptable — the helper just hands the value through.
    assert verdicts_by_skill["idea-to-pdd"].evaluated_at is not None


def test_serializer_includes_runs_and_selected_run_id(monkeypatch):
    """The serializer surfaces runs[] (from runs_summary) and selected_run_id."""
    from apps.opps.serializers import serialize_opp_snapshot
    fake = FakeDrive(_build_turmeric_layout())
    snap = load_opp(fake, ace_root_folder_id="ACE", opp_slug="turmeric")
    serialized = serialize_opp_snapshot(snap)
    assert serialized["selected_run_id"] == "20260502-1830"
    assert [r["run_id"] for r in serialized["runs"]] == ["20260502-1830", "20260502-1430"]
    # Confirm the run-summary fields are present:
    first = serialized["runs"][0]
    assert first["current_phase"] == "ocs"
    assert first["current_step"] == "ocs-agent-setup"
    assert first["mode"] == "default"
    assert first["last_actor_at"] == "2026-05-02T18:42:00Z"
