from pathlib import Path

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


def test_aggregate_skill_segment_appears_under_other_phase():
    """Without phase labeling (Task 7), skills land under the _other phase."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next((p for p in breakdown["phases"] if p["phase_name"] == "_other"), None)
    assert other is not None
    skill = next((s for s in other["skills"] if s["skill_name"] == "ace:idea-to-pdd"), None)
    assert skill is not None
    assert skill["invocation_count"] == 2
    assert len(skill["invocations"]) == 2


def test_aggregate_skill_wall_time_uses_first_to_last_event():
    """Two invocations: 15s (18:00:05->18:00:20) and 10s (18:01:05->18:01:15). Sum = 25s."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next(p for p in breakdown["phases"] if p["phase_name"] == "_other")
    skill = next(s for s in other["skills"] if s["skill_name"] == "ace:idea-to-pdd")
    assert skill["wall_time_seconds"] == 25


def test_aggregate_skill_tokens_sum_inside_segment():
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


def test_aggregate_attributes_sidechain_to_agent_segment():
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
