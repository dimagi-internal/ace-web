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


def test_parse_handles_string_content_user_message():
    """Real-world transcripts: a user message's `content` is sometimes a
    plain string (the user's prompt) instead of a list of content blocks.
    Iterating the string used to crash with AttributeError."""
    from apps.ingest.parser import parse_session_file
    session, events = parse_session_file(FIXTURES / "string_content_session.jsonl")
    # No tool_results in this fixture; just an assistant text turn.
    assert session.cli_session_id == "sess_string_001"
    assert any(t.role == "assistant" for t in session.turns)
    # Aggregator path: should not raise; should produce a single assistant_turn event.
    assistant = [e for e in events if e.kind == "assistant_turn"]
    assert len(assistant) == 1
    assert assistant[0].usage["input_tokens"] == 50


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


def test_parse_claude_code_interactive_session_extracts_session_id():
    """Claude Code interactive transcripts (~/.claude/projects/<slug>/<uuid>.jsonl)
    don't emit a `system/init` envelope — instead, every line carries a
    top-level camelCase `sessionId`. The parser must fall back to that
    so the dedup branch in views.upload (cli_session_id-keyed) actually
    fires for re-uploads of interactive transcripts. See issue #274 Bug 2."""
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "interactive_session.jsonl")
    assert result.cli_session_id == "7c2be22b-5630-40f7-a201-f53fe2daeb64"


def test_parse_session_returns_content_sha256():
    """Every parse returns a sha256 of the raw file bytes so views.upload
    can dedup on content hash when no cli_session_id is available
    (issue #274 hardening)."""
    from apps.ingest.parser import parse_session_file
    result, _events = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.content_sha256
    assert len(result.content_sha256) == 64
    # Stable across re-parses of the same file.
    again, _ = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert again.content_sha256 == result.content_sha256


def test_extract_cost_events_marks_sidechain_with_parent_uuid():
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / "cost_session.jsonl")
    sidechain = [e for e in events if e.is_sidechain]
    assert len(sidechain) == 2
    assert sidechain[0].parent_uuid == "u-5"
    assert sidechain[1].parent_uuid == "u-6"


def test_cost_event_captures_tool_result_is_error(tmp_path):
    from apps.ingest.parser import parse_session_file

    jsonl = tmp_path / "errors.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"toolu_1","name":"Bash","input":{"command":"false"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1",'
        '"is_error":true,"content":"exit code 1"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    results = [e for e in events if e.kind == "tool_result"]
    assert len(results) == 1
    assert results[0].is_error is True
    assert results[0].content_preview == "exit code 1"


def test_cost_event_content_preview_truncates_long_results(tmp_path):
    from apps.ingest.parser import parse_session_file

    long_body = "x" * 500
    jsonl = tmp_path / "long.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"toolu_1","name":"Read","input":{}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1",'
        f'"content":"{long_body}"' + "}]}}\n"
    )
    _session, events = parse_session_file(jsonl)
    result = next(e for e in events if e.kind == "tool_result")
    assert result.is_error is False
    assert result.content_preview == long_body[:200]
    assert len(result.content_preview) == 200


def test_parse_session_bytes_matches_parse_session_file():
    """parse_session_bytes produces the same output as parse_session_file
    for the same content — the file variant just delegates."""
    from apps.ingest.parser import parse_session_bytes, parse_session_file

    path = FIXTURES / "tool_use_session.jsonl"
    raw = path.read_bytes()
    session_a, events_a = parse_session_file(path)
    session_b, events_b = parse_session_bytes(raw)

    assert session_a.cli_session_id == session_b.cli_session_id
    assert session_a.raw_bytes == session_b.raw_bytes
    assert session_a.line_count == session_b.line_count
    assert session_a.content_sha256 == session_b.content_sha256
    assert len(session_a.turns) == len(session_b.turns)
    assert len(events_a) == len(events_b)
    for ea, eb in zip(events_a, events_b, strict=True):
        assert ea.kind == eb.kind
        assert ea.tool_use_id == eb.tool_use_id
        assert ea.matched_tool_use_id == eb.matched_tool_use_id


def test_nul_bytes_stripped_from_turns():
    """Postgres jsonb/text reject U+0000 — the parser must strip it so
    bulk_create can't 500 on a transcript carrying a NUL in tool output."""
    import json
    from apps.ingest.parser import parse_session_bytes

    rows = [
        {"type": "system", "subtype": "init", "session_id": "sess_nul_001"},
        {
            "type": "assistant",
            "message": {"id": "m1", "content": [{"type": "text", "text": "a\x00b"}]},
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "x\x00y"}]},
        },
    ]
    raw = ("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8")
    result, _events = parse_session_bytes(raw)

    for turn in result.turns:
        assert "\x00" not in turn.plaintext
        assert "\x00" not in json.dumps(turn.content)
    assert result.turns[0].plaintext == "ab"
