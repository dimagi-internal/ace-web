from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _events(filename="cost_session.jsonl"):
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / filename)
    return events


def test_aggregate_returns_schema_v2_with_session_totals():
    from apps.ingest.structure_aggregator import aggregate
    tree = aggregate(_events())
    assert tree["schema_version"] == 2
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


def test_tool_error_stays_pinned_and_does_not_roll_up(tmp_path):
    """A tool with is_error keeps `status: "error"` on its own row, but the
    phase and session stay `"ok"`. A single tool blip should not paint a
    whole transcript red."""
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
    assert tree["session"]["status"] == "ok"
    phase = tree["phases"][0]
    assert phase["status"] == "ok"
    # The errored tool node still carries status=error so the UI can flag it.
    tool_nodes = [c for c in phase["children"] if c["kind"] == "tool"]
    assert tool_nodes and tool_nodes[0]["status"] == "error"


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
        '"message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"tInner","content":"inner done"}]}}\n'
        # Outer result
        '{"type":"user","uuid":"u4","timestamp":"2026-05-10T14:00:03Z",'
        '"message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"tOuter","content":"outer done"}]}}\n'
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


def test_tool_content_preview_propagates_from_tool_result(tmp_path):
    """The content_preview captured on tool_result events lands on the tool node."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "preview.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Bash","input":{"command":"ls"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tA",'
        '"content":"file1.txt\\nfile2.txt"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    orch = next(p for p in tree["phases"] if p["name"] == "_orchestration")
    tool = next(c for c in orch["children"] if c["kind"] == "tool")
    assert tool["content_preview"] == "file1.txt\nfile2.txt"


def test_nested_subagent_cost_rolls_up_to_parent_and_phase(tmp_path, monkeypatch):
    """Cost from a sidechain assistant turn inside a subagent must roll up
    to the parent skill node and to the phase total — otherwise a
    /ace:run-style transcript (orchestrator dispatches → subagents do all
    the model work) shows session_cost > 0 but every phase row = $0.
    """
    from apps.ingest import structure_aggregator
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    monkeypatch.setattr(
        structure_aggregator, "skill_phase_index",
        lambda: {"qa-and-training": {"phase": "phase-5-qa-and-training",
                                     "phase_display": "Phase 5: QA and Training",
                                     "phase_ordinal": 5,
                                     "skill_display": "QA and Training"}},
    )

    jsonl = tmp_path / "nested_costs.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        # Orchestrator's dispatch turn — has its own usage even though it
        # only contains a Skill tool_use block. Without dispatch-turn
        # deferral this cost would be lost from every phase.
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":1000,"output_tokens":100},"content":['
        '{"type":"tool_use","id":"tOuter","name":"Skill",'
        '"input":{"skill":"qa-and-training"}}]}}\n'
        # Inner Agent dispatch (sidechain — runs inside qa-and-training).
        '{"type":"assistant","uuid":"u2","parentUuid":"u1","isSidechain":true,'
        '"timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"id":"m2","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tInner","name":"Agent",'
        '"input":{"subagent_type":"unknown-inner"}}]}}\n'
        # The big cost: the subagent's leaf assistant turn does the real work.
        '{"type":"assistant","uuid":"u3","parentUuid":"u2","isSidechain":true,'
        '"timestamp":"2026-05-10T14:00:02Z",'
        '"message":{"id":"m3","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":50000,"output_tokens":2000},"content":['
        '{"type":"text","text":"working"}]}}\n'
        # Inner result first (LIFO close).
        '{"type":"user","uuid":"u4","timestamp":"2026-05-10T14:00:03Z",'
        '"message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"tInner","content":"inner done"}]}}\n'
        # Outer result.
        '{"type":"user","uuid":"u5","timestamp":"2026-05-10T14:00:04Z",'
        '"message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"tOuter","content":"outer done"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)

    session_cost = tree["session"]["estimated_cost_usd"]
    assert session_cost > 0, "fixture must have nonzero cost or the test is vacuous"

    phase = next(p for p in tree["phases"] if p["name"] == "phase-5-qa-and-training")
    assert phase["estimated_cost_usd"] == session_cost, (
        f"phase rollup {phase['estimated_cost_usd']} should equal session total "
        f"{session_cost} — all events landed under this single phase"
    )

    outer = next(c for c in phase["children"] if c["kind"] == "skill")
    assert outer["estimated_cost_usd"] == session_cost, (
        "top-level skill node must include its subagent's cost so the row "
        "shows the inclusive spend; otherwise the phase rollup drops it"
    )
    # Tokens propagate too — needed for the tokens chip on the skill row.
    assert outer["tokens"]["input_tokens"] == 51000
    assert outer["tokens"]["output_tokens"] == 2100

    inner = next(c for c in outer["children"] if c["kind"] == "skill")
    assert inner["is_subagent"] is True
    # The inner skill node reports its own subtree cost (no parent dispatch
    # turn was attributed to it).
    assert inner["tokens"]["input_tokens"] == 50000
    assert inner["tokens"]["output_tokens"] == 2000


def test_orchestrator_thinking_attributed_to_current_phase(tmp_path, monkeypatch):
    """Top-level assistant turns (not dispatch turns, no open frame) belong
    to the most-recently-entered phase as a synthetic "(orchestration)"
    skill row. Otherwise their cost is lost from phase rollups even though
    the wall-time and tool nodes are bucketed correctly.
    """
    from apps.ingest import structure_aggregator
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    monkeypatch.setattr(
        structure_aggregator, "skill_phase_index",
        lambda: {"qa-and-training": {"phase": "phase-5-qa-and-training",
                                     "phase_display": "Phase 5: QA and Training",
                                     "phase_ordinal": 5,
                                     "skill_display": "QA and Training"}},
    )

    jsonl = tmp_path / "orch_thinking.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        # Dispatch + close a Skill — enters the phase, then closes.
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Skill",'
        '"input":{"skill":"qa-and-training"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"tA","content":"done"}]}}\n'
        # AFTER the skill closes: top-level orchestrator turn with real
        # usage but no enclosing frame and no dispatch. This is the gap
        # that was losing cost — there are ~50 of these in a real chat
        # session that imports a transcript and keeps talking to Claude.
        '{"type":"assistant","uuid":"u3","timestamp":"2026-05-10T14:00:02Z",'
        '"message":{"id":"m3","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":100000,"output_tokens":5000},"content":['
        '{"type":"text","text":"thinking after the dispatch"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)

    phase = next(p for p in tree["phases"] if p["name"] == "phase-5-qa-and-training")
    # Phase total reconciles with session total — the orchestrator turn's
    # cost lives in a synthetic "(orchestration)" child of the phase.
    assert phase["estimated_cost_usd"] == tree["session"]["estimated_cost_usd"]

    orch_rows = [c for c in phase["children"]
                 if c["kind"] == "skill" and c["name"] == "(direct turns)"]
    assert len(orch_rows) == 1
    assert orch_rows[0]["tokens"]["input_tokens"] == 100000
    assert orch_rows[0]["tokens"]["output_tokens"] == 5000
    assert orch_rows[0]["estimated_cost_usd"] > 0
    # Each orchestrator turn is also surfaced as a `direct_turn` child so the
    # user can drill into where the spend went.
    children = orch_rows[0]["children"]
    assert len(children) == 1
    turn = children[0]
    assert turn["kind"] == "direct_turn"
    assert turn["tokens"]["input_tokens"] == 100000
    assert turn["tokens"]["output_tokens"] == 5000
    assert turn["text_preview"] == "thinking after the dispatch"
    assert turn["model"] == "claude-sonnet-4-6"
    assert turn["started_at"] is not None


def test_orchestrator_thinking_before_any_dispatch_lands_in_orchestration(tmp_path):
    """A top-level assistant turn that fires before any Skill dispatch has
    no current_phase yet — its cost belongs in the global Orchestration
    bucket so it still reconciles with the session total.
    """
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "pre_dispatch.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":50000,"output_tokens":1000},"content":['
        '{"type":"text","text":"orchestrator setup"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)

    orch_phase = next(p for p in tree["phases"] if p["name"] == "_orchestration")
    assert orch_phase["estimated_cost_usd"] == tree["session"]["estimated_cost_usd"]
    synthetic = next(c for c in orch_phase["children"]
                     if c["kind"] == "skill" and c["name"] == "(direct turns)")
    assert synthetic["tokens"]["input_tokens"] == 50000


def test_phase_wall_is_span_not_sum_when_orch_overlaps_tool(tmp_path):
    """Phase wall must use a span, not a sum. The synthetic "direct turns"
    row spans all top-level assistant turns; tool calls run *during* those
    turns. Summing both double-counts wall-clock seconds.
    """
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "overlap.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        # Three top-level assistant turns spanning 100s. Each ends with a
        # tool_use; each tool_result is +5s. With sum-based rollup the
        # phase wall would be ~100 (orch span) + 15 (3×tool 5s) = 115.
        # With span-based, the phase wall equals the actual elapsed time
        # (~100s).
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":100,"output_tokens":10},"content":['
        '{"type":"tool_use","id":"tA","name":"Bash","input":{"command":"ls"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:05Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tA",'
        '"content":"x"}]}}\n'
        '{"type":"assistant","uuid":"u3","timestamp":"2026-05-10T14:00:50Z",'
        '"message":{"id":"m3","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":100,"output_tokens":10},"content":['
        '{"type":"tool_use","id":"tB","name":"Bash","input":{"command":"ls"}}]}}\n'
        '{"type":"user","uuid":"u4","timestamp":"2026-05-10T14:00:55Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tB",'
        '"content":"x"}]}}\n'
        '{"type":"assistant","uuid":"u5","timestamp":"2026-05-10T14:01:40Z",'
        '"message":{"id":"m5","model":"claude-sonnet-4-6","usage":'
        '{"input_tokens":100,"output_tokens":10},"content":['
        '{"type":"text","text":"final"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    orch = next(p for p in tree["phases"] if p["name"] == "_orchestration")
    # Span is 14:00:00 → 14:01:40 = 100s exactly. Old sum-based rollup
    # would have produced ~110s (100s synthetic + ~5s + ~5s tools).
    assert orch["wall_time_seconds"] == 100, (
        f"expected 100s span, got {orch['wall_time_seconds']}s — "
        "sum-based rollup is leaking tool wall on top of the orch span"
    )


def test_tool_without_result_has_null_content_preview(tmp_path):
    """A tool_use without a matching tool_result leaves content_preview=None."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "no_result.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Bash","input":{"command":"ls"}}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    orch = next(p for p in tree["phases"] if p["name"] == "_orchestration")
    tool = next(c for c in orch["children"] if c["kind"] == "tool")
    assert tool["content_preview"] is None
