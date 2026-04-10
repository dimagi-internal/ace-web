from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_simple_session():
    from apps.ingest.parser import parse_session_file
    result = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.cli_session_id == "sess_simple_001"
    assert len(result.turns) == 1
    turn = result.turns[0]
    assert turn.role == "assistant"
    assert turn.plaintext == "Hello, world!"


def test_parse_tool_use_session():
    from apps.ingest.parser import parse_session_file
    result = parse_session_file(FIXTURES / "tool_use_session.jsonl")
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
    result = parse_session_file(FIXTURES / "multi_turn_session.jsonl")
    assert result.cli_session_id == "sess_multi_001"
    assert len(result.turns) == 2
    assert result.turns[0].plaintext == "Hi there!"
    assert result.turns[1].plaintext == "Sure, I can help."


def test_parse_returns_byte_count():
    from apps.ingest.parser import parse_session_file
    result = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.raw_bytes > 0


def test_parse_returns_line_count():
    from apps.ingest.parser import parse_session_file
    result = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.line_count == 4
