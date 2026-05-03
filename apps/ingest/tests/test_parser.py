from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_simple_session():
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.cli_session_id == "sess_simple_001"
    assert len(result.turns) == 1
    turn = result.turns[0]
    assert turn.role == "assistant"
    assert turn.plaintext == "Hello, world!"


def test_parse_tool_use_session():
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "tool_use_session.jsonl")
    assert result.cli_session_id == "sess_tool_001"
    assert len(result.turns) == 4
    assert result.turns[0].role == "assistant"
    assert result.turns[0].plaintext == "Let me check."
    assert result.turns[1].role == "tool_use"
    assert result.turns[2].role == "tool_result"
    assert result.turns[3].role == "assistant"
    assert result.turns[3].plaintext == "It has localhost."


def test_parse_multi_turn_session():
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "multi_turn_session.jsonl")
    assert result.cli_session_id == "sess_multi_001"
    assert len(result.turns) == 2
    assert result.turns[0].plaintext == "Hi there!"
    assert result.turns[1].plaintext == "Sure, I can help."


def test_parse_returns_byte_count():
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.raw_bytes > 0


def test_parse_returns_line_count():
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.line_count == 4


def test_extract_cost_events_emits_assistant_turns():
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / "cost_session.jsonl")
    assistant = [e for e in events if e.kind == "assistant_turn"]
    # 9 assistant lines in the fixture (m-1, m-2, m-3, m-5, m-6, m-7, m-9, m-10, m-12)
    assert len(assistant) == 9
    first = assistant[0]
    assert first.uuid == "u-1"
    assert first.model == "claude-opus-4-7"
    assert first.usage["input_tokens"] == 100
    assert first.usage["cache_read_input_tokens"] == 1000
    assert first.is_sidechain is False


def test_extract_cost_events_emits_tool_use_with_skill_name():
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / "cost_session.jsonl")
    skill_uses = [e for e in events if e.kind == "tool_use" and e.tool_name == "Skill"]
    assert len(skill_uses) == 2
    assert skill_uses[0].tool_use_id == "tu-skill-1"
    assert skill_uses[0].tool_input == {"skill": "ace:idea-to-pdd"}


def test_extract_cost_events_emits_agent_subagent_type():
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / "cost_session.jsonl")
    agent_uses = [e for e in events if e.kind == "tool_use" and e.tool_name == "Agent"]
    assert len(agent_uses) == 1
    assert agent_uses[0].tool_use_id == "tu-agent-1"
    assert agent_uses[0].tool_input["subagent_type"] == "ace:design-review"


def test_extract_cost_events_pairs_tool_results_with_tool_use_id():
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / "cost_session.jsonl")
    results = [e for e in events if e.kind == "tool_result"]
    matched_ids = {e.matched_tool_use_id for e in results}
    assert matched_ids == {"tu-skill-1", "tu-agent-1", "tu-skill-2"}


def test_extract_cost_events_marks_sidechain_with_parent_uuid():
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / "cost_session.jsonl")
    sidechain = [e for e in events if e.is_sidechain]
    assert len(sidechain) == 2
    assert sidechain[0].parent_uuid == "u-5"
    assert sidechain[1].parent_uuid == "u-6"
