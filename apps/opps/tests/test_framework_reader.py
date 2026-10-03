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


def _tree_with_superseded_rows() -> dict:
    """A run whose log carries both shapes of HISTORY row next to the live
    ones: an in-run correction (ace#1421: ``d-old`` → ``d-new``) and a row a
    fork retired under a renamed id (ace#2582: ``fx-20260530-1200`` → ``fx``).
    Plus a live row that has history, and one with none — the negative
    control that a live row is never mistaken for history."""
    tree = _demo_multi_run_tree()
    tree["ACE"]["demo"]["runs"]["20260601-0900"]["decisions.yaml"] = (
        "decisions:\n"
        "  - id: d-old\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Which archetype?\n"
        "    ai-default: data-collection\n"
        "    superseded_by: d-new\n"
        "  - id: d-new\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Which archetype?\n"
        "    ai-default: service-delivery\n"
        "  - id: fx-20260530-1200\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Payment per visit?\n"
        "    ai-default: '2 USD'\n"
        "    superseded_by: fx\n"
        "  - id: fx\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Payment per visit?\n"
        "    ai-default: '3 USD'\n"
        "  - id: plain\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Language?\n"
        "    ai-default: English\n"
    )
    return tree


def test_snapshot_decisions_carry_superseded_by():
    """canopy-agent-runs drops ``superseded_by``; the reader must put it back,
    or the Phases panel shows corrected / fork-retired rows as live choices."""
    client = FakeDriveClient.from_tree(_tree_with_superseded_rows())
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    got = {d.id: d.superseded_by for d in snap.current_run.decisions}
    assert got == {
        "d-old": "d-new",
        "d-new": "",
        "fx-20260530-1200": "fx",
        "fx": "",
        "plain": "",
    }


def test_superseded_by_reaches_the_serialized_snapshot():
    from apps.opps.serializers import serialize_run_detail

    client = FakeDriveClient.from_tree(_tree_with_superseded_rows())
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    rows = serialize_run_detail(snap.current_run)["decisions"]
    assert {r["id"]: r["superseded_by"] for r in rows}["d-old"] == "d-new"
    assert {r["id"]: r["superseded_by"] for r in rows}["plain"] == ""


def test_review_fields_reach_the_serialized_snapshot():
    """canopy-agent-runs drops the optional review fields too (``review_ask``,
    ``plain``, ``audience`` …); the reader reads them ace-side, and a row
    without them serves "" — the Workbench renders it as before."""
    from apps.opps.serializers import serialize_run_detail

    tree = _demo_multi_run_tree()
    tree["ACE"]["demo"]["runs"]["20260601-0900"]["decisions.yaml"] = (
        "decisions:\n"
        "  - id: d1\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Which archetype?\n"
        "    ai-default: service-delivery\n"
        "    review_ask: recommended-confirmation\n"
        "    confirm_reason: The partner decides this.\n"
        "    plain: Workers deliver a service.\n"
        "    audience: internal\n"
        "  - id: d2\n"
        "    phase: 1-design\n"
        "    skill: idea-to-pdd\n"
        "    question: Language?\n"
        "    ai-default: English\n"
    )
    client = FakeDriveClient.from_tree(tree)
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    rows = {r["id"]: r for r in serialize_run_detail(snap.current_run)["decisions"]}
    assert rows["d1"]["review_ask"] == "recommended-confirmation"
    assert rows["d1"]["confirm_reason"] == "The partner decides this."
    assert rows["d1"]["plain"] == "Workers deliver a service."
    assert rows["d1"]["audience"] == "internal"
    assert rows["d2"]["review_ask"] == "" and rows["d2"]["plain"] == ""


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


# --------------------------------------------------------------------------- #
# output previews ride the snapshot, and edits to an index invalidate it
# --------------------------------------------------------------------------- #
def _tree_with_learn_app_previews() -> tuple[FakeDriveClient, str]:
    tree = _demo_multi_run_tree()
    run = tree["ACE"]["demo"]["runs"]["20260601-0900"]
    run["run_state.yaml"] += (
        "  commcare-setup:\n"
        "    status: complete\n"
        "    products:\n"
        "      apps:\n"
        "        domain: ace-demo\n"
        "        learn: {hq_app_id: L1}\n"
    )
    run["3-commcare"] = {"previews": {"apps-learn": {"_previews.yaml": "", "01-home.png": ""}}}
    client = FakeDriveClient.from_tree(tree)
    folder = "ACE/demo/runs/20260601-0900/3-commcare/previews/apps-learn"
    index = client.file_id(f"{folder}/_previews.yaml")
    client._nodes_by_id[index].body = (
        "schema_version: 1\n"
        "phase: commcare-setup\n"
        "output_key: apps.learn\n"
        "captured_by: app-screenshot-capture\n"
        f"items:\n  - file_id: {client.file_id(f'{folder}/01-home.png')}\n"
        "    caption: Home\n"
    )
    return client, index


def test_load_opp_reads_output_previews_onto_the_serialized_products():
    from apps.opps.serializers import serialize_run_detail

    client, _ = _tree_with_learn_app_previews()
    snap = load_opp(client, ace_folder_id=client.folder_id("ACE"), slug="demo")
    products = serialize_run_detail(snap.current_run)["products"]
    learn = next(p for p in products if p["key"] == "apps.learn")
    assert [(p["caption"], p["captured_by"]) for p in learn["previews"]] == [
        ("Home", "app-screenshot-capture")
    ]


def test_a_preview_index_is_a_tracked_file():
    """Editing an index must invalidate the cached snapshot like any other
    run file — it rides the same reverse index."""
    inner, index = _tree_with_learn_app_previews()
    client = CachedDriveClient(inner, bypass=False)
    with TouchedFileTracker() as tracker:
        load_opp(client, ace_folder_id=inner.folder_id("ACE"), slug="demo")
    assert index in tracker.file_ids


def test_snapshot_cache_drop_forgets_one_run_only():
    from apps.opps import snapshot_cache

    snapshot_cache.set(workspace_id="w", slug="a", run_id="r1", snap={"n": 1}, file_ids={"f"})
    snapshot_cache.set(workspace_id="w", slug="a", run_id="r2", snap={"n": 2}, file_ids={"f"})
    snapshot_cache.drop(workspace_id="w", slug="a", run_id="r1")
    assert snapshot_cache.get(workspace_id="w", slug="a", run_id="r1") is None
    assert snapshot_cache.get(workspace_id="w", slug="a", run_id="r2") == {"n": 2}
