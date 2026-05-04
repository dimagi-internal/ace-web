from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _events(filename="cost_session.jsonl"):
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / filename)
    return events


def test_aggregate_returns_schema_v1_with_totals():
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    assert breakdown["schema_version"] == 1
    assert "totals" in breakdown
    assert "phases" in breakdown
    assert "computed_at" in breakdown


def test_aggregate_skill_segment_appears_under_other_phase(no_registry):
    """Without phase labeling (Task 7), skills land under the _other phase."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next((p for p in breakdown["phases"] if p["phase_name"] == "_other"), None)
    assert other is not None
    skill = next((s for s in other["skills"] if s["skill_name"] == "ace:idea-to-pdd"), None)
    assert skill is not None
    assert skill["invocation_count"] == 2
    assert len(skill["invocations"]) == 2


def test_aggregate_skill_wall_time_uses_first_to_last_event(no_registry):
    """Two invocations: 15s (18:00:05->18:00:20) and 10s (18:01:05->18:01:15). Sum = 25s."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next(p for p in breakdown["phases"] if p["phase_name"] == "_other")
    skill = next(s for s in other["skills"] if s["skill_name"] == "ace:idea-to-pdd")
    assert skill["wall_time_seconds"] == 25


def test_aggregate_skill_tokens_sum_inside_segment(no_registry):
    """Skill 1 tokens include the dispatch turn (m-2) plus the inner turn (m-3).
    The dispatch assistant turn (m-2: 10/5/0/1100) is attributed to the segment
    it opens rather than to orchestration. Inner turn m-3: 200/300/500/2000.
    Total invoc1: 210/305/500/3100."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next(p for p in breakdown["phases"] if p["phase_name"] == "_other")
    skill = next(s for s in other["skills"] if s["skill_name"] == "ace:idea-to-pdd")
    invoc1 = skill["invocations"][0]
    assert invoc1["tokens"]["input_tokens"] == 210   # 10 (dispatch m-2) + 200 (m-3)
    assert invoc1["tokens"]["output_tokens"] == 305  # 5 (dispatch m-2) + 300 (m-3)
    assert invoc1["tokens"]["cache_creation_tokens"] == 500
    assert invoc1["tokens"]["cache_read_tokens"] == 3100  # 1100 (dispatch) + 2000 (m-3)


def test_aggregate_totals_match_sum_of_all_assistant_turns():
    """Totals include orchestration + every segment, not double-counted.
    Sum of all assistant_turn input_tokens in fixture: 100+10+200+15+400+50+10+80+40 = 905."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    assert breakdown["totals"]["input_tokens"] == 905


def test_aggregate_attributes_sidechain_to_agent_segment(no_registry):
    """The two sidechain turns (u-6, u-7) under tu-agent-1 must roll into
    the design-review segment, not into orchestration. The dispatch turn
    (u-5: 15/8/0/2200) also attributes to the segment it opens."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next(p for p in breakdown["phases"] if p["phase_name"] == "_other")
    agent_skill = next(s for s in other["skills"] if s["skill_name"] == "ace:design-review")
    assert agent_skill is not None
    invoc = agent_skill["invocations"][0]
    # u-5 dispatch: input 15, output 8,   cw 0,    cr 2200
    # u-6 sidechain: input 400, output 200, cw 1000, cr 3000
    # u-7 sidechain: input 50,  output 150, cw 0,    cr 3500
    assert invoc["tokens"]["input_tokens"] == 465   # 15+400+50
    assert invoc["tokens"]["output_tokens"] == 358  # 8+200+150
    assert invoc["tokens"]["cache_creation_tokens"] == 1000
    assert invoc["tokens"]["cache_read_tokens"] == 8700  # 2200+3000+3500


def test_aggregate_orchestration_excludes_sidechain_tokens():
    """Sidechain turns must NOT also land in orchestration."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    orch = next(p for p in breakdown["phases"] if p["phase_name"] == "_orchestration")
    # Orchestration assistant turns: m-1 (100/50), m-12 (40/30) only.
    # The tool_use-only turns m-2, m-5, m-9 carry usage but each opens/dispatches
    # a segment; they're attributed to the segment they *open* per the
    # design (the input/output/cache cost is for the dispatch itself).
    # Without that rule, m-2 (10/5/0/1100) would land here. Pick whichever
    # behavior the implementation uses and assert it consistently.
    assert orch["tokens"]["input_tokens"] == 100 + 40
    assert orch["tokens"]["output_tokens"] == 50 + 30


def test_aggregate_finalizes_interrupted_segment():
    """tu-interrupted has no matching tool_result. It must still appear,
    flagged incomplete, with wall_time bounded by last event inside."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events("cost_session_edge.jsonl"))
    # Segments still open at end of stream finalize at the last event
    # observed inside them. The made-up-skill segment opened at e-1
    # 19:00:00, contained e-2 at 19:00:05, was never closed. Wall time
    # = 5s, flagged incomplete.
    skills = [s for p in breakdown["phases"] for s in p["skills"]]
    interrupted = next((s for s in skills if s["skill_name"] == "ace:made-up-skill"), None)
    assert interrupted is not None
    assert interrupted["invocations"][0]["wall_time_seconds"] == 5
    assert interrupted["invocations"][0].get("incomplete") is True


def test_aggregate_unknown_model_marks_segment_partial():
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events("cost_session_edge.jsonl"))
    skills = [s for p in breakdown["phases"] for s in p["skills"]]
    unknown = next(s for s in skills if s["skill_name"] == "ace:does-not-exist")
    # The inner turn used "some-future-model" which is unpriced.
    assert unknown["cost_is_partial"] is True
    # And totals flag the same.
    assert breakdown["totals"]["cost_is_partial"] is True


def test_aggregate_unknown_skill_name_still_appears(no_registry):
    """Unknown skills (not in apps/system registry) appear under _other.
    Phase 7 wiring will route known skills elsewhere; here we just verify
    both unknown skills landed."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events("cost_session_edge.jsonl"))
    all_skill_names = {s["skill_name"] for p in breakdown["phases"] for s in p["skills"]}
    assert "ace:made-up-skill" in all_skill_names
    assert "ace:does-not-exist" in all_skill_names


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def no_registry(monkeypatch):
    """Monkeypatch _skill_phase_index to return an empty dict.

    Apply to any test that asserts _other phase content so the test is
    independent of the real ACE plugin being installed.
    """
    from apps.ingest import cost_aggregator
    monkeypatch.setattr(cost_aggregator, "_skill_phase_index", lambda: {})


# ---------------------------------------------------------------------------
# Task 7: phase labeling via registry
# ---------------------------------------------------------------------------

def test_aggregate_labels_known_skills_with_phase_from_registry(monkeypatch):
    """Skills in the registry appear under their proper phase row, not _other."""
    from apps.ingest import cost_aggregator

    fake_registry = {
        "ace:idea-to-pdd": {
            "phase": "design-review",
            "phase_display": "Phase 1: Design Review",
            "phase_ordinal": 1,
        },
        "ace:design-review": {
            "phase": "design-review",
            "phase_display": "Phase 1: Design Review",
            "phase_ordinal": 1,
        },
    }
    monkeypatch.setattr(cost_aggregator, "_skill_phase_index", lambda: fake_registry)

    breakdown = cost_aggregator.aggregate(_events())

    # Both skills must appear under the design-review phase.
    dr_phase = next(
        (p for p in breakdown["phases"] if p["phase_name"] == "design-review"), None
    )
    assert dr_phase is not None, "Expected a 'design-review' phase row"
    assert dr_phase["phase_display"] == "Phase 1: Design Review"
    assert dr_phase["phase_ordinal"] == 1

    dr_skill_names = {s["skill_name"] for s in dr_phase["skills"]}
    assert "ace:idea-to-pdd" in dr_skill_names
    assert "ace:design-review" in dr_skill_names


def test_aggregate_attributes_post_dispatch_orchestration_to_current_phase(monkeypatch):
    """Orchestration turns AFTER a phase has been dispatched roll into that
    phase as a synthetic '(orchestration)' skill row.

    In the cost_session.jsonl fixture, u-12 is a pure-text orchestration turn
    that fires AFTER all skill/agent dispatches close. With the registry
    mapping the dispatched skills to 'design-review', u-12's tokens (40/30/
    0/4300) should land under design-review as '(orchestration)'.

    u-1, by contrast, is BEFORE any dispatch — current_phase is still None,
    so it stays in the global _orchestration bucket (genuine setup work).
    """
    from apps.ingest import cost_aggregator

    fake_registry = {
        "ace:idea-to-pdd": {
            "phase": "design-review",
            "phase_display": "Phase 1: Design Review",
            "phase_ordinal": 1,
        },
        "ace:design-review": {
            "phase": "design-review",
            "phase_display": "Phase 1: Design Review",
            "phase_ordinal": 1,
        },
    }
    monkeypatch.setattr(cost_aggregator, "_skill_phase_index", lambda: fake_registry)

    breakdown = cost_aggregator.aggregate(_events())

    # u-1 (pre-dispatch setup) goes into the global _orchestration bucket.
    orch = next(p for p in breakdown["phases"] if p["phase_name"] == "_orchestration")
    assert orch["tokens"]["input_tokens"] == 100  # u-1 only
    assert orch["tokens"]["output_tokens"] == 50

    # u-12 (post-dispatch) goes into design-review as a synthetic skill.
    dr = next(p for p in breakdown["phases"] if p["phase_name"] == "design-review")
    orch_skill = next(
        (s for s in dr["skills"] if s["skill_name"] == "(orchestration)"), None
    )
    assert orch_skill is not None, "Expected a '(orchestration)' synthetic skill in design-review"
    assert orch_skill["invocation_count"] == 1
    assert orch_skill["tokens"]["input_tokens"] == 40
    assert orch_skill["tokens"]["output_tokens"] == 30
    assert orch_skill["tokens"]["cache_read_tokens"] == 4300


def test_aggregate_no_phase_orchestration_when_registry_empty(no_registry):
    """When the registry is empty, no skill maps to a phase, so current_phase
    never updates from None — all orchestration stays in the global
    _orchestration bucket. No '(orchestration)' synthetic skill anywhere."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    for ph in breakdown["phases"]:
        names = {s["skill_name"] for s in ph["skills"]}
        assert "(orchestration)" not in names


def test_aggregate_unknown_skill_falls_back_to_other(monkeypatch):
    """With an empty registry, all skills land in _other."""
    from apps.ingest import cost_aggregator

    monkeypatch.setattr(cost_aggregator, "_skill_phase_index", lambda: {})

    breakdown = cost_aggregator.aggregate(_events())
    other = next((p for p in breakdown["phases"] if p["phase_name"] == "_other"), None)
    assert other is not None

    other_skill_names = {s["skill_name"] for s in other["skills"]}
    assert "ace:idea-to-pdd" in other_skill_names
    assert "ace:design-review" in other_skill_names
