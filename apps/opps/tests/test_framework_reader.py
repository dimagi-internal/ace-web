"""Tests for the wave-4 run-reader swap shim (``apps.opps.framework_reader``).

These pin the parts of the swap that are otherwise thinly covered: that the
chokepoints (now backed by ``canopy_agent_runs.drive.store.DriveRunStore``) surface the
full field-groups end-to-end — per-step artifact Drive identity (``drive_file_id``
+ run-relative ``path``) and the full decisions log (``id`` / ``options_considered``
/ raw ``phase``), which the framework ``Artifact`` / ``Decision`` schemas now carry
(``Artifact.ref``/``path`` + the decisions-log fields) and the mapper passes
straight through; that the flat (legacy) layout reads through the synthetic-run
adapter; and that file-id tracking still flows through ace's ``CachedDriveClient``
so the snapshot-cache reverse index keeps populating.
"""

from __future__ import annotations

import pytest

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.sync import list_opp_runs, load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    nutrition_legacy_flat_tree,
)
from apps.opps.touched_tracker import TouchedFileTracker

pytestmark = pytest.mark.django_db


def _demo_multi_run_tree() -> dict:
    """A multi-run opp carrying the full read-model surface: a phase-prefixed
    artifact, a phase-prefixed eval verdict, and a run-root decisions.yaml — so we
    can assert each comes through the framework read model end-to-end."""
    return {
        "ACE": {
            "demo": {
                "opp.yaml": ("display_name: Demo Opp\nslug: demo\ncreated_by: ace@dimagi-ai.com\n"),
                "runs": {
                    "20260601-0900": {
                        "run_state.yaml": (
                            "current_phase: design-review\n"
                            "current_step: idea-to-pdd\n"
                            "mode: autopilot\n"
                            "started_at: 2026-06-01T09:00:00Z\n"
                            "phases:\n"
                            "  design-review:\n"
                            "    status: complete\n"
                            "    steps:\n"
                            "      idea-to-pdd: {status: done}\n"
                        ),
                        "1-design": {
                            "idea-to-pdd.md": "# PDD\n\nFirst sentence.",
                            "idea-to-pdd-eval_verdict.yaml": (
                                "verdict: pass\n"
                                "overall_score: 91\n"
                                "evaluated_at: 2026-06-01T09:10:00Z\n"
                            ),
                        },
                        "decisions.yaml": (
                            "decisions:\n"
                            "  - id: d1\n"
                            "    phase: 1-design\n"
                            "    skill: idea-to-pdd\n"
                            "    question: Which archetype?\n"
                            "    ai-default: service-delivery\n"
                            "    options: [service-delivery, data-collection]\n"
                            "    reasoning: partner is a survey org\n"
                            "    status: ai-default\n"
                        ),
                    },
                },
            }
        }
    }


def _idea_step(snap):
    return next(s for s in snap.current_run.steps if s.step.skill_name == "idea-to-pdd")


# --------------------------------------------------------------------------- #
# multi-run: artifact identity + decisions + verdict recovery
# --------------------------------------------------------------------------- #
def test_multi_run_artifact_drive_identity():
    """The framework ``Artifact`` carries ``ref`` (the Drive file id) + ``path``;
    the mapper surfaces them as ``drive_file_id``/``path`` so file-open +
    preview-by-path keep working — sourced from the framework, not re-attributed."""
    client = FakeDriveClient.from_tree(_demo_multi_run_tree())
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    art = next(a for a in _idea_step(snap).artifacts if a.name == "idea-to-pdd.md")
    assert art.drive_file_id  # non-empty — would be "" straight off the framework
    assert art.drive_file_id == client.file_id(
        "ACE/demo/runs/20260601-0900/1-design/idea-to-pdd.md"
    )
    assert art.path == "1-design/idea-to-pdd.md"


def test_multi_run_full_decision_rows():
    """The framework ``Decision`` carries id/options/raw-phase; the mapper passes
    them straight through so the Decisions panel keeps its full rows."""
    client = FakeDriveClient.from_tree(_demo_multi_run_tree())
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    decisions = snap.current_run.decisions
    assert [d.id for d in decisions] == ["d1"]
    d = decisions[0]
    assert d.skill == "idea-to-pdd"
    assert d.phase == "1-design"  # raw row phase, not the step's phase
    assert d.options_considered == ["service-delivery", "data-collection"]
    assert d.notes == "partner is a survey org"


def test_multi_run_attaches_judge_verdict_via_store():
    """Step status + judge verdict come from the framework store + map."""
    client = FakeDriveClient.from_tree(_demo_multi_run_tree())
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    idea = _idea_step(snap)
    assert idea.step.status == "complete"
    assert idea.judge is not None
    assert idea.judge.score == 91.0


def test_multi_run_mode_keeps_raw_value_not_framework_canonical():
    """list_opp_runs preserves the literal run_state mode (the framework
    canonicalizes ``autopilot`` → ``auto``)."""
    client = FakeDriveClient.from_tree(_demo_multi_run_tree())
    runs = list_opp_runs(client, ace_root_folder_id=client.folder_id("ACE"), opp_slug="demo")
    assert len(runs) == 1
    assert runs[0].mode == "autopilot"
    assert runs[0].current_phase == "design-review"
    assert runs[0].lifecycle_status == "complete"


# --------------------------------------------------------------------------- #
# flat (legacy) layout: synthetic-run adapter
# --------------------------------------------------------------------------- #
def test_flat_layout_recovers_artifact_identity_and_status():
    """The flat opp is read through the synthetic ``r1`` run; artifacts keep
    their Drive identity and subfolder-presence still drives status."""
    client = FakeDriveClient.from_tree(nutrition_legacy_flat_tree())
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="nutrition-legacy")
    assert snap.current_run.run_id == "r1"
    learn = next(s for s in snap.current_run.steps if s.step.skill_name == "pdd-to-learn-app")
    assert learn.step.status == "complete"
    art = next(a for a in learn.artifacts if "learn-app-summary" in a.name)
    assert art.drive_file_id  # non-empty
    assert art.path.startswith("app-summaries/")


# --------------------------------------------------------------------------- #
# cache / touched-file tracking flows through the store's reads
# --------------------------------------------------------------------------- #
def test_load_opp_through_cached_client_tracks_touched_file_ids():
    """Every Drive read the store issues goes through ace's CachedDriveClient,
    so the snapshot-cache reverse index still captures the run's file ids —
    including the run_state file and the run-tree artifacts."""
    inner = FakeDriveClient.from_tree(_demo_multi_run_tree())
    client = CachedDriveClient(inner, bypass=False)
    with TouchedFileTracker() as tracker:
        load_opp(client, ace_folder_id=inner.folder_id("ACE"), slug="demo")

    state_id = inner.file_id("ACE/demo/runs/20260601-0900/run_state.yaml")
    art_id = inner.file_id("ACE/demo/runs/20260601-0900/1-design/idea-to-pdd.md")
    assert state_id in tracker.file_ids
    assert art_id in tracker.file_ids


def test_list_opp_runs_through_cached_client_tracks_run_folder():
    """list_opp_runs over the cached client records the run folder + its
    state file so adding/removing runs invalidates the cached summary."""
    inner = FakeDriveClient.from_tree(_demo_multi_run_tree())
    client = CachedDriveClient(inner, bypass=False)
    with TouchedFileTracker() as tracker:
        list_opp_runs(client, ace_root_folder_id=inner.folder_id("ACE"), opp_slug="demo")

    run_folder_id = inner.folder_id("ACE/demo/runs/20260601-0900")
    state_id = inner.file_id("ACE/demo/runs/20260601-0900/run_state.yaml")
    assert run_folder_id in tracker.file_ids
    assert state_id in tracker.file_ids
