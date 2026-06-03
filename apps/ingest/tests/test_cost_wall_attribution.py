"""Wall-time attribution: per-phase / per-skill wall must be the duration of
the UNION of time intervals, never a sum of overlapping sub-intervals.

Regression coverage for the inflation bug where a phase reported
Σ(skill segment walls) + orchestration-span — double-counting the wall-clock
window that the orchestration span already blanketed (a 60-min run reporting
phases that summed to 90+ min; one skill slot showing ~27 min of overlap)."""
from datetime import datetime, timedelta

import apps.ingest.cost_aggregator as agg
from apps.ingest.parser import CostEvent

T0 = datetime.fromisoformat("2026-06-01T00:00:00+00:00")


def _ts(sec):
    return T0 + timedelta(seconds=sec)


_USAGE = {"input_tokens": 1, "output_tokens": 1,
          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def _two_skill_phase_events():
    """Two sequential skill segments in phase alpha with an orchestration turn
    between them and one after. Real elapsed = 600s (10..610 -> totals span)."""
    return [
        CostEvent(kind="tool_use", timestamp=_ts(10), uuid="a1",
                  tool_use_id="t1", tool_name="Skill",
                  tool_input={"skill": "skill-one"}),
        CostEvent(kind="tool_result", timestamp=_ts(300), uuid="u1",
                  matched_tool_use_id="t1"),
        CostEvent(kind="assistant_turn", timestamp=_ts(310), uuid="a2",
                  model="claude", usage=_USAGE),
        CostEvent(kind="tool_use", timestamp=_ts(320), uuid="a3",
                  tool_use_id="t2", tool_name="Skill",
                  tool_input={"skill": "skill-two"}),
        CostEvent(kind="tool_result", timestamp=_ts(600), uuid="u2",
                  matched_tool_use_id="t2"),
        CostEvent(kind="assistant_turn", timestamp=_ts(610), uuid="a4",
                  model="claude", usage=_USAGE),
    ]


def _alpha_index():
    return {
        "skill-one": {"phase": "alpha", "phase_display": "Alpha", "phase_ordinal": 3},
        "skill-two": {"phase": "alpha", "phase_display": "Alpha", "phase_ordinal": 3},
    }


def test_phase_wall_is_interval_union_not_sum(monkeypatch):
    monkeypatch.setattr(agg, "skill_phase_index", _alpha_index)
    b = agg.aggregate(_two_skill_phase_events())

    alpha = next(p for p in b["phases"] if p["phase_name"] == "alpha")
    # Intervals: skill-one [10,300]=290, skill-two [320,600]=280, orch turns
    # span [310,610]. Union = [10,300] ∪ [310,610] = 290 + 300 = 590.
    assert alpha["wall_time_seconds"] == 590

    walls = {s["skill_name"]: s["wall_time_seconds"] for s in alpha["skills"]}
    assert walls["skill-one"] == 290
    assert walls["skill-two"] == 280
    # Orchestration row = phase union (590) minus union of skill segments
    # ([10,300] ∪ [320,600] = 570) = 20s of genuine between-skill orchestration.
    assert walls["(orchestration)"] == 20


def test_phase_walls_never_exceed_total(monkeypatch):
    monkeypatch.setattr(agg, "skill_phase_index", _alpha_index)
    b = agg.aggregate(_two_skill_phase_events())
    total = b["totals"]["wall_time_seconds"]
    sum_phases = sum(p["wall_time_seconds"] for p in b["phases"])
    assert sum_phases <= total, f"phase walls {sum_phases}s > total elapsed {total}s"


def test_global_orchestration_wall_excludes_skill_segments(monkeypatch):
    """Skills dispatched before any phase is entered (current_phase still None
    → '_other') run inside the global orchestration span. The global
    _orchestration wall must be the RESIDUAL (span minus skill union), not the
    full span, or the run sums past 100%."""
    monkeypatch.setattr(agg, "skill_phase_index", lambda: {})  # no registry → _other
    events = [
        # Orchestration turn at t=0 opens the global span.
        CostEvent(kind="assistant_turn", timestamp=_ts(0), uuid="g0",
                  model="claude", usage=_USAGE),
        # Unknown skill segment [10, 70] lands in _other, runs inside the span.
        CostEvent(kind="tool_use", timestamp=_ts(10), uuid="g1",
                  tool_use_id="t1", tool_name="Skill",
                  tool_input={"skill": "mystery-skill"}),
        CostEvent(kind="tool_result", timestamp=_ts(70), uuid="u1",
                  matched_tool_use_id="t1"),
        # Closing orchestration turn at t=80.
        CostEvent(kind="assistant_turn", timestamp=_ts(80), uuid="g2",
                  model="claude", usage=_USAGE),
    ]
    b = agg.aggregate(events)
    total = b["totals"]["wall_time_seconds"]
    assert sum(p["wall_time_seconds"] for p in b["phases"]) <= total

    orch = next(p for p in b["phases"] if p["phase_name"] == "_orchestration")
    other = next(p for p in b["phases"] if p["phase_name"] == "_other")
    assert other["wall_time_seconds"] == 60          # the [10,70] skill segment
    # Global span [0,80]=80s minus the [10,70]=60s skill segment = 20s residual.
    assert orch["wall_time_seconds"] == 20


def test_skill_rows_sum_to_phase_wall(monkeypatch):
    """Within a phase, the skill rows (incl. synthetic orchestration) partition
    the phase wall — they sum to it exactly, no overlap."""
    monkeypatch.setattr(agg, "skill_phase_index", _alpha_index)
    b = agg.aggregate(_two_skill_phase_events())
    alpha = next(p for p in b["phases"] if p["phase_name"] == "alpha")
    assert sum(s["wall_time_seconds"] for s in alpha["skills"]) == alpha["wall_time_seconds"]
