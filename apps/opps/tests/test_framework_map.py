"""Unit tests for ``apps.opps.framework_map``.

Builds representative ``canopy_runs.schemas`` read-model objects directly and
asserts the ace-web dataclasses (``OppSnapshot`` / ``RunDetail`` /
``StepSnapshot`` / ``StepManifest`` / ``ArtifactRef`` / ``JudgeVerdict`` /
``QAResult`` / ace ``RunSummary`` / parser ``Decision``) come out field-for-field
correct. No Drive, no DB — pure mapping.
"""
from __future__ import annotations

import datetime as dt

from canopy_runs.schemas import (
    Artifact as FwArtifact,
    Decision as FwDecision,
    Run as FwRun,
    RunSummary as FwRunSummary,
    Step as FwStep,
    Verdict as FwVerdict,
)

from apps.opps import framework_map as fm
from apps.opps.parsers import JudgeVerdict, QAResult, StepManifest
from apps.opps.parsers import Decision as AceDecision
from apps.opps.sync import (
    ArtifactRef,
    OppSnapshot,
    RunDetail,
    RunSummary as AceRunSummary,
    StepSnapshot,
)

UTC = dt.timezone.utc


# --------------------------------------------------------------------------- #
# leaf mappers
# --------------------------------------------------------------------------- #
def test_map_artifact_ref_field_for_field():
    a = FwArtifact(
        step_key="idea-to-pdd",
        name="pdd.md",
        url="https://drive/abc",
        mime_type="text/markdown",
        size=2048,
        role="idea-to-pdd",
    )
    ref = fm.map_artifact_ref(a)
    assert isinstance(ref, ArtifactRef)
    assert ref.name == "pdd.md"
    assert ref.drive_web_link == "https://drive/abc"
    assert ref.mime_type == "text/markdown"
    assert ref.size_bytes == 2048
    # framework Artifact carries neither a Drive file id nor a path
    assert ref.drive_file_id == ""
    assert ref.path == ""


def test_map_judge_verdict():
    v = FwVerdict(
        step_key="idea-to-pdd",
        kind="judge",
        score=8.0,
        passed=True,
        criteria={"clarity": 9},
        rationale="solid",
        evaluated_at=dt.datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )
    j = fm.map_judge_verdict(v)
    assert isinstance(j, JudgeVerdict)
    assert j.score == 8.0
    assert j.passed is True
    assert j.criteria == {"clarity": 9}
    assert j.rationale == "solid"
    assert j.evaluated_at == "2026-06-01T09:00:00Z"


def test_map_judge_verdict_none():
    assert fm.map_judge_verdict(None) is None


def test_map_qa_result_failed_reconstructs_checks_and_failures():
    v = FwVerdict(
        step_key="idea-to-pdd",
        kind="qa",
        passed=False,
        criteria={
            "checks_run": 3,
            "checks_passed": 2,
            "checks_failed": 1,
            "failures": ["has_archetype"],
        },
        rationale="archetype block missing",
        evaluated_at=dt.datetime(2026, 6, 1, 9, 5, tzinfo=UTC),
    )
    qa = fm.map_qa_result(v, target_skill="idea-to-pdd")
    assert isinstance(qa, QAResult)
    assert qa.target_skill == "idea-to-pdd"
    assert qa.skill == "idea-to-pdd-qa"  # reconstructed
    assert qa.verdict == "fail"
    assert qa.ran_at == "2026-06-01T09:05:00Z"
    assert qa.checks_run == 3
    assert qa.checks_passed == 2
    assert qa.checks_failed == 1
    assert len(qa.failures) == 1
    assert qa.failures[0].check == "has_archetype"
    assert qa.failures[0].detail == "archetype block missing"
    assert qa.failures[0].type == "static"


def test_map_qa_result_pass_and_incomplete():
    assert fm.map_qa_result(
        FwVerdict(step_key="s", kind="qa", passed=True), target_skill="s"
    ).verdict == "pass"
    assert fm.map_qa_result(
        FwVerdict(step_key="s", kind="qa", passed=None), target_skill="s"
    ).verdict == "incomplete"
    assert fm.map_qa_result(None, target_skill="s") is None


def test_map_decision_uses_step_key_as_skill_and_reasoning_as_notes():
    d = FwDecision(
        step_key="idea-to-pdd",
        question="Which archetype?",
        ai_default="service-delivery",
        override="data-collection",
        status="overridden",
        reasoning="partner is a survey org",
        evidence_basis="inferred",
    )
    ace = fm.map_decision(d, phase="design-review")
    assert isinstance(ace, AceDecision)
    assert ace.skill == "idea-to-pdd"
    assert ace.phase == "design-review"
    assert ace.question == "Which archetype?"
    assert ace.ai_default == "service-delivery"
    assert ace.override == "data-collection"
    assert ace.status == "overridden"
    assert ace.notes == "partner is a survey org"
    assert ace.evidence_basis == "inferred"


# --------------------------------------------------------------------------- #
# step mapper
# --------------------------------------------------------------------------- #
def test_map_step_snapshot_complete_with_judge():
    step = FwStep(key="idea-to-pdd", ordinal=1, title="design-review", status="complete")
    art = FwArtifact(step_key="idea-to-pdd", name="pdd.md", url="u", mime_type="text/markdown", size=10)
    judge = FwVerdict(step_key="idea-to-pdd", kind="judge", score=9.0, passed=True)
    snap = fm.map_step_snapshot(step, [art], [judge], folder_id="run-folder-1")
    assert isinstance(snap, StepSnapshot)
    assert isinstance(snap.step, StepManifest)
    assert snap.step.skill_name == "idea-to-pdd"
    assert snap.step.phase == "design-review"  # Step.title -> phase
    assert snap.step.ordinal == 1
    assert snap.step.status == "complete"
    assert snap.step.preview_stats == {}
    assert snap.folder_id == "run-folder-1"
    assert len(snap.artifacts) == 1 and snap.artifacts[0].name == "pdd.md"
    assert snap.judge is not None and snap.judge.score == 9.0
    assert snap.qa_result is None


def test_map_step_snapshot_failed_with_qa_becomes_qa_failed():
    step = FwStep(key="idea-to-pdd", ordinal=1, title="design-review", status="failed")
    qa = FwVerdict(
        step_key="idea-to-pdd", kind="qa", passed=False,
        criteria={"checks_run": 1, "checks_passed": 0, "checks_failed": 1, "failures": ["x"]},
    )
    snap = fm.map_step_snapshot(step, [], [qa])
    assert snap.step.status == "qa-failed"
    assert snap.qa_result is not None and snap.qa_result.verdict == "fail"


def test_map_step_snapshot_failed_without_qa_becomes_error():
    step = FwStep(key="app-deploy", ordinal=5, title="commcare-setup", status="failed", error="boom")
    snap = fm.map_step_snapshot(step, [], [])
    assert snap.step.status == "error"
    assert snap.step.error == "boom"


def test_map_step_snapshot_preview_stats_from_run_state():
    step = FwStep(key="idea-to-pdd", ordinal=1, title="design-review", status="complete")
    run_state = {
        "phases": {
            "design-review": {
                "status": "complete",
                "steps": {"idea-to-pdd": {"status": "done", "preview_stats": {"words": 120}}},
            }
        }
    }
    snap = fm.map_step_snapshot(step, [], [], run_state=run_state)
    assert snap.step.preview_stats == {"words": 120}


# --------------------------------------------------------------------------- #
# run mapper
# --------------------------------------------------------------------------- #
def _complete_run() -> FwRun:
    steps = [
        FwStep(key="idea-to-pdd", ordinal=1, title="design-review", status="complete"),
        FwStep(key="pdd-to-learn-app", ordinal=2, title="commcare-setup", status="complete"),
    ]
    run = FwRun(
        id="20260601-0900",
        agent_slug="malaria-rdt-simple",
        label="Malaria RDT (simple)",
        mode="auto",
        current_phase="closeout",
        current_step="cycle-grade",
        created_at=dt.datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        steps=steps,
        artifacts=[
            FwArtifact(step_key="idea-to-pdd", name="pdd.md", url="u1", mime_type="text/markdown", size=1),
            FwArtifact(step_key="pdd-to-learn-app", name="learn-app-summary.md", url="u2", mime_type="text/markdown", size=2),
        ],
        verdicts=[FwVerdict(step_key="idea-to-pdd", kind="judge", score=9.0, passed=True)],
        decisions=[
            FwDecision(step_key="idea-to-pdd", question="archetype?", ai_default="sd", status="ai-default"),
        ],
    )
    return run.with_derived_status()


def test_map_run_detail_header_and_children():
    run = _complete_run()
    assert run.status == "complete"  # derived
    rd = fm.map_run_detail(run, folder_id="rf-1", run_state={"notes": "n", "skill_versions": {"idea-to-pdd": "1.2"}})
    assert isinstance(rd, RunDetail)
    assert rd.run_id == "20260601-0900"
    assert rd.mode == "auto"
    assert rd.status == "complete"  # framework derived status carried through
    assert rd.started_at == "2026-06-01T09:00:00Z"
    assert rd.current_phase == "closeout"
    assert rd.current_step == "cycle-grade"
    assert rd.skill_versions == {"idea-to-pdd": "1.2"}
    assert rd.notes == "n"
    assert rd.folder_id == "rf-1"
    assert len(rd.steps) == 2
    # decision phase resolved from the producing step's phase
    assert len(rd.decisions) == 1
    assert rd.decisions[0].skill == "idea-to-pdd"
    assert rd.decisions[0].phase == "design-review"
    # per-step artifacts/verdicts routed by step_key
    by_skill = {s.step.skill_name: s for s in rd.steps}
    assert by_skill["idea-to-pdd"].artifacts[0].name == "pdd.md"
    assert by_skill["idea-to-pdd"].judge.score == 9.0
    assert by_skill["pdd-to-learn-app"].artifacts[0].name == "learn-app-summary.md"
    assert by_skill["pdd-to-learn-app"].judge is None


def test_map_run_detail_defaults_without_run_state():
    rd = fm.map_run_detail(_complete_run())
    assert rd.skill_versions == {}
    assert rd.notes == ""
    assert rd.folder_id == ""


def test_map_run_summary_supplements_from_run_state():
    fw = FwRunSummary(
        id="20260601-0900",
        agent_slug="malaria-rdt-simple",
        mode="auto",
        status="in_progress",
        current_phase="commcare-setup",
        current_step="pdd-to-learn-app",
    )
    run_state = {
        "last_actor": "ace@dimagi-ai.com",
        "last_actor_at": "2026-06-01T10:00:00Z",
        "phases": {
            "design-review": {"status": "complete", "steps": {"idea-to-pdd": "done"}},
            "commcare-setup": {"status": "pending", "steps": {"pdd-to-learn-app": "pending"}},
        },
    }
    rs = fm.map_run_summary(fw, folder_id="rf-9", run_state=run_state)
    assert isinstance(rs, AceRunSummary)
    assert rs.run_id == "20260601-0900"
    assert rs.folder_id == "rf-9"
    assert rs.current_phase == "commcare-setup"
    assert rs.mode == "auto"
    assert rs.last_actor == "ace@dimagi-ai.com"
    assert rs.last_actor_at == "2026-06-01T10:00:00Z"
    # phase progress derived via ace's own _derive_phase_progress
    assert rs.phases_total == 2
    assert rs.phases_done == 1
    assert rs.latest_phase_done == "design-review"
    assert rs.lifecycle_status == "in_progress"


def test_map_run_summary_defaults_without_run_state():
    fw = FwRunSummary(id="r1", agent_slug="x", current_phase="")
    rs = fm.map_run_summary(fw)
    assert rs.phases_total == 0
    assert rs.phases_done == 0
    assert rs.latest_phase_done is None
    assert rs.current_phase is None


# --------------------------------------------------------------------------- #
# opp snapshot assembly
# --------------------------------------------------------------------------- #
def test_map_opp_snapshot_full_assembly():
    run = _complete_run()
    summaries = [
        FwRunSummary(id="20260601-0900", agent_slug="malaria-rdt-simple", mode="auto", current_phase="closeout"),
    ]
    snap = fm.map_opp_snapshot(
        run,
        summaries,
        opp_folder_id="opp-folder-1",
        run_folder_id="run-folder-1",
        pdd_body="# PDD body",
        run_state={"created_by": "ace@dimagi-ai.com"},
        run_state_by_id={"20260601-0900": {"phases": {"closeout": {"status": "complete", "steps": {"x": "done"}}}}},
        folder_id_by_run={"20260601-0900": "run-folder-1"},
    )
    assert isinstance(snap, OppSnapshot)
    assert snap.opp.slug == "malaria-rdt-simple"
    assert snap.opp.display_name == "Malaria RDT (simple)"
    assert snap.opp.created_by == "ace@dimagi-ai.com"
    assert snap.opp.current_run_id == "20260601-0900"
    assert snap.opp.labels == [] and snap.opp.tags == []
    assert snap.pdd_body == "# PDD body"
    assert snap.opp_folder_id == "opp-folder-1"
    assert isinstance(snap.current_run, RunDetail)
    assert snap.current_run.folder_id == "run-folder-1"
    assert len(snap.runs_summary) == 1
    assert snap.runs_summary[0].folder_id == "run-folder-1"
    assert snap.runs_summary[0].phases_done == 1
