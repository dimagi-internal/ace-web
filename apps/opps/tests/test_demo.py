"""Unit tests for ``apps.opps.demo`` — the Demo Player payload.

Pure derivation from a rich snapshot dict: no Drive, no DB, no cache.

The tests that matter most here are the *honesty* ones — a run with no
per-step timestamps must report ``timing_source: "ordinal"`` and must not
invent a wall clock, and an act whose data is missing must come back
unavailable with a reason rather than empty-but-available.
"""
from __future__ import annotations

import datetime as dt

import pytest

from apps.opps import demo

UTC = dt.UTC


def _step(
    skill,
    phase,
    ordinal,
    *,
    status="complete",
    started=None,
    completed=None,
    judge=None,
    qa=None,
    artifacts=(),
    error=None,
):
    return {
        "skill_name": skill,
        "display_name": skill.replace("-", " ").title(),
        "phase": phase,
        "phase_display": phase.replace("-", " ").title(),
        "ordinal": ordinal,
        "status": status,
        "started_at": started,
        "completed_at": completed,
        "error": error,
        "judge": judge,
        "qa_result": qa,
        "artifacts": list(artifacts),
    }


def _snapshot(steps, *, decisions=(), run_started=None, run_completed=None):
    return {
        "slug": "hh-poverty-targeting",
        "title": "HH Poverty Targeting",
        "current_run": {
            "run_id": "20260722-1341",
            "status": "complete",
            "started_at": run_started,
            "completed_at": run_completed,
            "steps": steps,
            "decisions": list(decisions),
        },
    }


def _measured_steps():
    return [
        _step(
            "idea-to-pdd", "1-design", 1,
            started="2026-07-22T13:41:00Z", completed="2026-07-22T14:11:00Z",
            artifacts=[{"name": "pdd.md", "drive_web_link": "https://drive/pdd"}],
            judge={"score": 8.0, "passed": True},
        ),
        _step(
            "idea-to-pdd-eval", "1-design", 2,
            started="2026-07-22T14:11:00Z", completed="2026-07-22T14:20:00Z",
        ),
        _step(
            "pdd-to-learn-app", "2-commcare", 3,
            started="2026-07-22T14:30:00Z", completed="2026-07-22T15:41:00Z",
        ),
    ]


# --------------------------------------------------------------------------- #
# timestamp parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-22T13:41:00Z", dt.datetime(2026, 7, 22, 13, 41, tzinfo=UTC)),
        ("2026-07-22T13:41:00+00:00", dt.datetime(2026, 7, 22, 13, 41, tzinfo=UTC)),
        (
            dt.datetime(2026, 7, 22, 13, 41, tzinfo=UTC),
            dt.datetime(2026, 7, 22, 13, 41, tzinfo=UTC),
        ),
        # Naive datetimes (PyYAML parses unquoted scalars without a zone) are UTC.
        (dt.datetime(2026, 7, 22, 13, 41), dt.datetime(2026, 7, 22, 13, 41, tzinfo=UTC)),
    ],
)
def test_parse_iso_accepts_every_shape_the_read_path_produces(raw, expected):
    assert demo._parse_iso(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "not-a-date", 42, {}])
def test_parse_iso_rejects_garbage_rather_than_guessing(raw):
    assert demo._parse_iso(raw) is None


# --------------------------------------------------------------------------- #
# timeline
# --------------------------------------------------------------------------- #
def test_timeline_measures_real_elapsed_time():
    tl = demo.build_timeline(_snapshot(_measured_steps()))
    assert tl["timing_source"] == "measured"
    assert tl["origin"] == "2026-07-22T13:41:00Z"
    # 13:41 -> 15:41 is two hours.
    assert tl["wall_seconds"] == 7200.0


def test_timeline_emits_phase_start_once_per_phase():
    tl = demo.build_timeline(_snapshot(_measured_steps()))
    phase_starts = [e for e in tl["events"] if e["kind"] == "phase_start"]
    assert [e["phase"] for e in phase_starts] == ["1-design", "2-commcare"]


def test_timeline_events_are_sequenced_and_offset_from_origin():
    tl = demo.build_timeline(_snapshot(_measured_steps()))
    assert [e["seq"] for e in tl["events"]] == list(range(len(tl["events"])))
    first_end = next(e for e in tl["events"] if e["kind"] == "step_end")
    assert first_end["t"] == 1800.0  # 13:41 -> 14:11
    assert first_end["duration_seconds"] == 1800.0


def test_timeline_step_end_carries_artifacts_and_verdict():
    tl = demo.build_timeline(_snapshot(_measured_steps()))
    end = next(e for e in tl["events"] if e["kind"] == "step_end")
    assert end["artifacts"] == [{"name": "pdd.md", "url": "https://drive/pdd"}]
    assert end["judge"] == {"score": 8.0, "passed": True}


def test_timeline_without_timestamps_reports_ordinal_and_no_clock():
    """The honesty rule: a run predating per-step timestamps gets sequence,
    never a fabricated wall clock."""
    steps = [_step("idea-to-pdd", "1-design", 1), _step("app-deploy", "2-commcare", 2)]
    tl = demo.build_timeline(_snapshot(steps))
    assert tl["timing_source"] == "ordinal"
    assert tl["wall_seconds"] is None
    assert all(e["t"] is None for e in tl["events"])
    # Ordering still works, which is what makes the act renderable at all.
    assert [e["seq"] for e in tl["events"]] == list(range(len(tl["events"])))


def test_timeline_skips_steps_that_never_ran():
    steps = _measured_steps() + [
        _step("llo-launch", "9-execution", 9, status="pending"),
        _step("closeout", "10-closeout", 10, status="skipped"),
    ]
    tl = demo.build_timeline(_snapshot(steps))
    assert "llo-launch" not in {e.get("skill") for e in tl["events"]}
    assert "closeout" not in {e.get("skill") for e in tl["events"]}


def test_timeline_origin_prefers_first_step_over_a_resumed_run_header():
    """A run resumed after an interruption carries a header timestamp from its
    first attempt; using it would stretch the timeline across the dead hours."""
    tl = demo.build_timeline(
        _snapshot(_measured_steps(), run_started="2026-07-20T09:00:00Z")
    )
    assert tl["origin"] == "2026-07-22T13:41:00Z"


def test_timeline_clamps_negative_offsets_from_clock_skew():
    steps = [
        _step("a", "p", 1, started="2026-07-22T13:41:00Z", completed="2026-07-22T13:45:00Z"),
        # Stamped a second before the run's first step — skew, not time travel.
        _step("b", "p", 2, started="2026-07-22T13:40:59Z", completed="2026-07-22T13:50:00Z"),
    ]
    tl = demo.build_timeline(_snapshot(steps))
    assert all(e["t"] is None or e["t"] >= 0 for e in tl["events"])


def test_timeline_of_an_empty_run_is_empty_not_broken():
    tl = demo.build_timeline(_snapshot([]))
    assert tl["events"] == []
    assert tl["timing_source"] == "ordinal"


# --------------------------------------------------------------------------- #
# time ledger
# --------------------------------------------------------------------------- #
def test_ledger_measures_phase_span_not_the_sum_of_its_skills():
    """The 10-minute gap between the two 2-commcare... er, 1-design skills and
    the next phase is real elapsed time; summing skill durations hides it."""
    ledger = demo.build_time_ledger(_snapshot(_measured_steps()))
    design = next(p for p in ledger["phases"] if p["phase"] == "1-design")
    # 13:41 -> 14:20 span = 2340s; active = 1800 + 540 = 2340s here (no gap).
    assert design["seconds"] == 2340.0
    assert design["active_seconds"] == 2340.0
    assert design["skill_count"] == 2


def test_ledger_span_exceeds_active_time_when_a_phase_has_gaps():
    steps = [
        _step("a", "p1", 1, started="2026-07-22T10:00:00Z", completed="2026-07-22T10:10:00Z"),
        _step("b", "p1", 2, started="2026-07-22T11:00:00Z", completed="2026-07-22T11:10:00Z"),
    ]
    ledger = demo.build_time_ledger(_snapshot(steps))
    phase = ledger["phases"][0]
    assert phase["seconds"] == 4200.0  # 10:00 -> 11:10
    assert phase["active_seconds"] == 1200.0  # 10 + 10 minutes of actual work


def test_ledger_preserves_phase_execution_order():
    ledger = demo.build_time_ledger(_snapshot(_measured_steps()))
    assert [p["phase"] for p in ledger["phases"]] == ["1-design", "2-commcare"]


def test_ledger_reports_no_seconds_without_timestamps():
    steps = [_step("idea-to-pdd", "1-design", 1)]
    ledger = demo.build_time_ledger(_snapshot(steps))
    assert ledger["wall_seconds"] is None
    assert ledger["phases"][0]["seconds"] is None
    assert ledger["phases"][0]["active_seconds"] is None


def test_ledger_never_reports_tokens_or_cost():
    """Deliberate omission — see the spec section of the same name. A token
    ledger discloses our subscription-vs-API cost structure to an audience
    that is frequently an AI company."""
    ledger = demo.build_time_ledger(_snapshot(_measured_steps()))
    blob = repr(ledger).lower()
    for banned in ("token", "cost", "usd", "dollar", "price"):
        assert banned not in blob


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #
def test_gates_surface_a_failed_judge():
    steps = _measured_steps() + [
        _step("pdd-to-deliver-app", "2-commcare", 4, status="judge-fail",
              judge={"score": 2.0, "passed": False, "rationale": "fields out of order"}),
    ]
    gates = demo.build_gates(_snapshot(steps))
    assert [g["skill"] for g in gates] == ["pdd-to-deliver-app"]
    assert gates[0]["judge"]["score"] == 2.0


def test_gates_surface_a_failed_qa():
    steps = [_step("idea-to-pdd", "1-design", 1, status="qa-failed",
                   qa={"verdict": "fail", "failures": ["missing archetype"]})]
    gates = demo.build_gates(_snapshot(steps))
    assert gates[0]["qa_result"]["verdict"] == "fail"


def test_gates_surface_an_errored_step():
    steps = [_step("app-deploy", "3-commcare", 1, status="error", error="boom")]
    gates = demo.build_gates(_snapshot(steps))
    assert gates[0]["error"] == "boom"


def test_gates_empty_on_a_clean_run():
    assert demo.build_gates(_snapshot(_measured_steps())) == []


# --------------------------------------------------------------------------- #
# decisions
# --------------------------------------------------------------------------- #
def test_decisions_count_the_rows_a_human_moved():
    decisions = [
        {"row_id": "d1", "status": "ai-default", "question": "Which archetype?"},
        {"row_id": "d2", "status": "overridden", "question": "Payment per visit?"},
        {"row_id": "d3", "status": "overridden", "question": "Photo required?"},
    ]
    out = demo.build_decisions(_snapshot(_measured_steps(), decisions=decisions))
    assert out["total"] == 3
    assert out["overridden_count"] == 2


def test_decisions_empty_when_the_run_wrote_no_log():
    out = demo.build_decisions(_snapshot(_measured_steps()))
    assert out == {"total": 0, "overridden_count": 0, "rows": []}


# --------------------------------------------------------------------------- #
# acts + payload
# --------------------------------------------------------------------------- #
def test_acts_available_on_a_rich_run():
    steps = _measured_steps() + [
        _step("x", "2-commcare", 5, status="judge-fail", judge={"passed": False, "score": 1.0}),
    ]
    snap = _snapshot(steps, decisions=[{"row_id": "d1", "status": "ai-default"}])
    acts, caps = demo.build_acts(snap)
    assert caps == {"timeline": True, "time_ledger": True, "gates": True, "decisions": True}
    assert all(a["unavailable_reason"] is None for a in acts)


def test_unavailable_acts_carry_a_reason_rather_than_rendering_empty():
    """A thin run gets a short demo, and the player can say why."""
    steps = [_step("idea-to-pdd", "1-design", 1)]  # no timestamps, no gate, no decisions
    acts, caps = demo.build_acts(_snapshot(steps))
    assert caps["timeline"] is True
    assert caps["time_ledger"] is False
    assert caps["gates"] is False
    assert caps["decisions"] is False
    for act in acts:
        if not act["available"]:
            assert act["unavailable_reason"], f"{act['id']} is unavailable with no reason"


def test_empty_run_reports_the_timeline_act_unavailable():
    acts, caps = demo.build_acts(_snapshot([]))
    assert caps["timeline"] is False
    timeline = next(a for a in acts if a["id"] == "timeline")
    assert "no completed steps" in timeline["unavailable_reason"]


def test_payload_header_and_schema_version():
    payload = demo.build_demo_payload(_snapshot(_measured_steps()), run_id="20260722-1341")
    assert payload["schema_version"] == demo.SCHEMA_VERSION
    assert payload["timing_source"] == "measured"
    assert payload["run"]["opp_slug"] == "hh-poverty-targeting"
    assert payload["run"]["opp_title"] == "HH Poverty Targeting"
    assert payload["run"]["run_id"] == "20260722-1341"
    assert payload["run"]["wall_seconds"] == 7200.0
    assert payload["run"]["step_count"] == 3
    assert [a["id"] for a in payload["acts"]] == [
        "timeline", "time_ledger", "gates", "decisions",
    ]


def test_payload_is_json_serializable():
    """It is served through JsonResponse; a stray datetime would 500."""
    import json
    payload = demo.build_demo_payload(_snapshot(_measured_steps()))
    assert json.loads(json.dumps(payload))["schema_version"] == demo.SCHEMA_VERSION
