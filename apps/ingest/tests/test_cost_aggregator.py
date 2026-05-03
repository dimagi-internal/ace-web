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
    """Skill 1 inner assistant turn (m-3) had 200 input, 300 output, 500 cw, 2000 cr."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    other = next(p for p in breakdown["phases"] if p["phase_name"] == "_other")
    skill = next(s for s in other["skills"] if s["skill_name"] == "ace:idea-to-pdd")
    invoc1 = skill["invocations"][0]
    assert invoc1["tokens"]["input_tokens"] == 200
    assert invoc1["tokens"]["output_tokens"] == 300
    assert invoc1["tokens"]["cache_creation_tokens"] == 500
    assert invoc1["tokens"]["cache_read_tokens"] == 2000


def test_aggregate_totals_match_sum_of_all_assistant_turns():
    """Totals include orchestration + every segment, not double-counted.
    Sum of all assistant_turn input_tokens in fixture: 100+10+200+15+400+50+10+80+40 = 905."""
    from apps.ingest.cost_aggregator import aggregate
    breakdown = aggregate(_events())
    assert breakdown["totals"]["input_tokens"] == 905
