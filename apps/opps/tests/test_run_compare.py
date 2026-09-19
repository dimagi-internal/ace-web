"""Unit tests for ``apps.opps.run_compare`` — what the later run did differently."""
from __future__ import annotations

from apps.opps.run_compare import build_run_compare


def _step(skill, phase, status="complete", passed=True, score=80):
    judge = None if passed is None else {"passed": passed, "score_pct": score}
    return {"skill_name": skill, "display_name": skill.title(), "phase": phase,
            "phase_display": phase.title(), "ordinal": 1, "status": status,
            "judge": judge, "qa_result": None}


def _decision(id_, question, answer, phase="design", override=None, status="ai-default"):
    return {"id": id_, "phase": phase, "skill": "idea-to-pdd", "question": question,
            "ai_default": answer, "override": override, "status": status}


PHASES = [{"name": "design", "display_name": "Design", "ordinal": 1},
          {"name": "commcare", "display_name": "CommCare", "ordinal": 3}]


def _snap(run_id, steps, decisions):
    return {"slug": "opp", "opp": {"slug": "opp", "display_name": "Opp"}, "phases": PHASES,
            "current_run": {"run_id": run_id, "started_at": None, "completed_at": None,
                            "steps": steps, "decisions": decisions}}


BASE = _snap(
    "20260722-1341",
    [_step("idea-to-pdd", "design"), _step("learn-app", "commcare", score=94),
     _step("old-check", "commcare")],
    [_decision("archetype", "Which archetype?", "service delivery"),
     _decision("cap", "Daily visit cap?", "10"),
     _decision("gone", "Something dropped?", "x")],
)
HEAD = _snap(
    "20260728-0705",
    [_step("idea-to-pdd", "design"),
     _step("learn-app", "commcare", status="judge-fail", passed=False, score=40),
     _step("app-connect-coverage", "commcare"),
     _step("not-yet", "commcare", status="pending", passed=None)],
    [_decision("archetype", "Which archetype?", "service delivery"),
     _decision("cap", "Daily visit cap?", "10", override="12", status="overridden"),
     _decision("gps-capture-scope", "Which outcomes capture GPS?", "all", phase="commcare"),
     _decision("required-fields", "Which fields are required?", "all but phone")],
)


def test_leads_with_decisions_the_later_run_made_that_the_earlier_never_did():
    out = build_run_compare(BASE, HEAD)
    assert [d["id"] for d in out["new_decisions"]] == ["required-fields", "gps-capture-scope"]
    gps = next(d for d in out["new_decisions"] if d["id"] == "gps-capture-scope")
    assert gps["answer"] == "all"
    assert gps["phase_display"] == "CommCare"


def test_new_decisions_are_ordered_by_phase():
    out = build_run_compare(BASE, HEAD)
    assert [d["phase"] for d in out["new_decisions"]] == ["design", "commcare"]


def test_reports_a_decision_answered_differently_using_the_human_override():
    out = build_run_compare(BASE, HEAD)
    (cap,) = out["changed_decisions"]
    assert (cap["id"], cap["before"], cap["after"]) == ("cap", "10", "12")
    assert cap["overridden"] is True


def test_reports_decisions_that_disappeared():
    out = build_run_compare(BASE, HEAD)
    assert [d["id"] for d in out["dropped_decisions"]] == ["gone"]


def test_new_checks_are_steps_that_ran_only_in_the_later_run():
    out = build_run_compare(BASE, HEAD)
    assert [s["skill"] for s in out["new_steps"]] == ["app-connect-coverage"]


def test_a_step_that_never_ran_is_not_new():
    out = build_run_compare(BASE, HEAD)
    assert "not-yet" not in [s["skill"] for s in out["new_steps"]]


def test_reports_steps_the_later_run_no_longer_ran():
    out = build_run_compare(BASE, HEAD)
    assert [s["skill"] for s in out["dropped_steps"]] == ["old-check"]


def test_step_table_states_verdicts_plainly_without_a_delta():
    """A stricter grader makes the better run score lower, so the table
    reports each run's verdict and never a better/worse delta."""
    out = build_run_compare(BASE, HEAD)
    learn = next(r for r in out["steps"] if r["skill"] == "learn-app")
    assert learn["base"]["label"] == "passed"
    assert learn["head"]["label"] == "did not pass"
    assert learn["changed"] is True
    assert "delta" not in learn


def test_step_present_in_only_one_run_has_no_verdict_for_the_other():
    out = build_run_compare(BASE, HEAD)
    row = next(r for r in out["steps"] if r["skill"] == "app-connect-coverage")
    assert row["base"] is None
    assert row["head"]["label"] == "passed"


def test_headers_count_what_each_run_did():
    out = build_run_compare(BASE, HEAD)
    assert out["base"] == {"run_id": "20260722-1341", "started_at": None,
                           "completed_at": None, "steps_run": 3, "decision_count": 3}
    assert out["head"]["steps_run"] == 3  # the pending step is not counted
    assert out["head"]["decision_count"] == 4


def test_identical_runs_have_nothing_new():
    out = build_run_compare(BASE, BASE)
    for key in ("new_decisions", "changed_decisions", "dropped_decisions",
                "new_steps", "dropped_steps"):
        assert out[key] == []
    assert not any(r["changed"] for r in out["steps"])


def test_a_change_of_case_or_spacing_is_not_a_changed_answer():
    """Real pair: "weekly" -> "Weekly" showed up as a changed decision."""
    base = _snap("a", [], [_decision("cadence", "Reporting cadence?", "weekly")])
    head = _snap("b", [], [_decision("cadence", "Reporting cadence?", "  Weekly. ")])
    assert build_run_compare(base, head)["changed_decisions"] == []
