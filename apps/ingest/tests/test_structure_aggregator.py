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
