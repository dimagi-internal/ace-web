"""Step detail must carry the step's judge verdict.

The Workbench eval panel rendered "Eval · no eval for this step" for
every step, including ones the lifecycle column scores 86. Two halves:

  * the frontend read ``detail.judge``, which this endpoint didn't have
    (fixed in #709 — the field is declared, just never populated);
  * the payload's ``verdicts`` was hard-coded ``[]`` with the comment
    "verdicts are per-skill; omit in v2 snapshot summary".

That omission is defensible for the LIST payload, but the step-DETAIL
endpoint is served from the very same mapped dict, so detail inherited
it and no step ever carried a verdict.

The data was never missing: ``StepSnapshot.judge`` is populated by
``load_opp`` (observed live: score 8.56 with a full criteria breakdown,
which is exactly the 86 the lifecycle column shows via
``normalize_score_pct``). Only the v2 mapping dropped it — the legacy
opp-detail serializer has shipped the same judge, criteria and all, the
whole time.

We surface ``judge`` rather than synthesizing ``VerdictOut`` rows: the
panel renders a per-criterion breakdown, and VerdictOut has nowhere to
put ``criteria`` (it would also force an invented ``kind``).
"""
from apps.opps.api import _snapshot_to_dict
from apps.opps.parsers import JudgeVerdict, OppManifest, StepManifest
from apps.opps.sync import OppSnapshot, RunDetail, StepSnapshot

JUDGE = JudgeVerdict(
    score=8.56,
    passed=True,
    evaluated_at="2026-07-24T22:40:00Z",
    criteria={"demand_reality": {"score": 8.5, "weight": 0.22}},
    rationale="",
)


def _snap(judge):
    step = StepSnapshot(
        step=StepManifest(
            skill_name="idea-to-pdd", phase="1-design", ordinal=1, status="complete",
        ),
        judge=judge,
        artifacts=[],
        folder_id="phase-folder",
        qa_result=None,
    )
    run = RunDetail(
        run_id="20260724-1622", mode="default", status="complete",
        started_at=None, completed_at=None, current_phase=None, current_step=None,
        skill_versions={}, notes="", steps=[step], folder_id="run-folder",
    )
    return OppSnapshot(
        opp=OppManifest(slug="spark-facilitator", display_name="Spark"),
        pdd_body="", opp_folder_id="opp", current_run=run,
    )


def _step(judge):
    return _snapshot_to_dict(_snap(judge))["steps"][0]


def test_step_carries_its_judge():
    judge = _step(JUDGE)["judge"]
    assert judge is not None, "step detail dropped the judge verdict"
    assert judge["score"] == 8.56


def test_score_is_projected_to_the_scale_the_ui_shows():
    """8.56 is what the lifecycle column renders as 86."""
    assert round(_step(JUDGE)["judge"]["score_pct"]) == 86


def test_criteria_breakdown_survives():
    """The eval panel renders per-criterion rows — don't flatten them away."""
    assert "demand_reality" in _step(JUDGE)["judge"]["criteria"]


def test_a_step_with_no_verdict_stays_none():
    assert _step(None)["judge"] is None
