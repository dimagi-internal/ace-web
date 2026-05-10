from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _events(filename="cost_session.jsonl"):
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / filename)
    return events


def test_aggregate_returns_schema_v1_with_session_totals():
    from apps.ingest.structure_aggregator import aggregate
    tree = aggregate(_events())
    assert tree["schema_version"] == 1
    assert "session" in tree
    assert "phases" in tree
    assert "computed_at" in tree
    assert tree["session"]["wall_time_seconds"] >= 0


def test_skill_dispatch_appears_under_phase(monkeypatch):
    """A Skill tool_use becomes a skill node under the phase the registry maps it to."""
    from apps.ingest import structure_aggregator
    monkeypatch.setattr(
        structure_aggregator, "skill_phase_index",
        lambda: {"idea-to-pdd": {"phase": "phase-1-design-review",
                                 "phase_display": "Phase 1: Design Review",
                                 "phase_ordinal": 1,
                                 "skill_display": "Idea to PDD"}},
    )
    tree = structure_aggregator.aggregate(_events())
    phase = next((p for p in tree["phases"] if p["name"] == "phase-1-design-review"), None)
    assert phase is not None
    assert phase["display"] == "Phase 1: Design Review"
    assert phase["kind"] == "phase"
    skills = [c for c in phase["children"] if c["kind"] == "skill"]
    assert any(s["name"] == "ace:idea-to-pdd" for s in skills)


def test_consecutive_same_turn_tools_form_parallel_group(tmp_path):
    """Two tool_use blocks in one assistant turn → parallel_group node."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "parallel.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Read","input":{"file_path":"a.txt"}},'
        '{"type":"tool_use","id":"tB","name":"Read","input":{"file_path":"b.txt"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tA","content":"a"}]}}\n'
        '{"type":"user","uuid":"u3","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tB","content":"b"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    orch = next((p for p in tree["phases"] if p["name"] == "_orchestration"), None)
    assert orch is not None, f"got phases {[p['name'] for p in tree['phases']]}"
    assert len(orch["children"]) == 1
    group = orch["children"][0]
    assert group["kind"] == "parallel_group"
    assert len(group["children"]) == 2
    assert {c["tool_use_id"] for c in group["children"]} == {"tA", "tB"}


def test_tool_error_propagates_status_up_to_session(tmp_path):
    """A tool with is_error → its phase and session status flip to 'error'."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "errors.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Bash","input":{"command":"false"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tA",'
        '"is_error":true,"content":"exit 1"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    assert tree["session"]["status"] == "error"


def test_nested_skill_dispatch_marked_is_subagent(tmp_path):
    """A Skill issued from inside another open frame is is_subagent=True;
    the outer Skill stays is_subagent=False."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "nested.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        # Outer Skill dispatch (top-level)
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tOuter","name":"Skill","input":{"skill":"outer-skill"}}]}}\n'
        # Inner Agent dispatch (sidechain — child of outer)
        '{"type":"assistant","uuid":"u2","parentUuid":"u1","isSidechain":true,'
        '"timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"id":"m2","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tInner","name":"Agent","input":{"subagent_type":"inner-agent"}}]}}\n'
        # Inner result first (LIFO close)
        '{"type":"user","uuid":"u3","timestamp":"2026-05-10T14:00:02Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tInner","content":"inner done"}]}}\n'
        # Outer result
        '{"type":"user","uuid":"u4","timestamp":"2026-05-10T14:00:03Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tOuter","content":"outer done"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    # Outer skill should appear under some phase (registry-less → _other)
    outer_phase = next(
        (p for p in tree["phases"] if any(c["kind"] == "skill" for c in p["children"])),
        None,
    )
    assert outer_phase is not None, f"got phases {[p['name'] for p in tree['phases']]}"
    outer = next(c for c in outer_phase["children"] if c["kind"] == "skill")
    assert outer["is_subagent"] is False, "outer top-level dispatch is not a subagent"
    # The inner Agent dispatch nests under the outer skill
    inner_skills = [c for c in outer["children"] if c["kind"] == "skill"]
    assert len(inner_skills) == 1
    assert inner_skills[0]["is_subagent"] is True
    # Agent dispatches name themselves by subagent_type
    assert inner_skills[0]["name"] == "inner-agent"


def test_open_frame_at_end_of_stream_is_incomplete(tmp_path):
    """A Skill tool_use without a matching tool_result becomes
    status='incomplete' and propagates to the session."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "interrupted.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Skill","input":{"skill":"some-skill"}}]}}\n'
        # No tool_result for tA — stream ends with the frame open.
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    assert tree["session"]["status"] == "incomplete"
    # The skill node still appears under a phase, marked incomplete
    phase = next(
        p for p in tree["phases"]
        if any(c["kind"] == "skill" for c in p["children"])
    )
    skill = next(c for c in phase["children"] if c["kind"] == "skill")
    assert skill["status"] == "incomplete"
