"""Tests for the stream-json parser. Reads captured fixtures and asserts on
the StreamEvent sequence the parser produces."""
from pathlib import Path

from apps.common.chat_backend import StreamEventType
from apps.common.cli_event_parser import parse_stream_json_lines

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list[str]:
    return [line for line in (FIXTURES / name).read_text().splitlines() if line]


def test_session_init_emits_session_id_first():
    events = list(parse_stream_json_lines(_load("stream_json_session_init.txt")))
    assert events[0].type is StreamEventType.SESSION_ID
    assert events[0].session_id == "sess_abc123"


def test_simple_text_emits_deltas_then_done():
    events = list(parse_stream_json_lines(_load("stream_json_simple.txt")))
    assert [e.type for e in events] == [
        StreamEventType.DELTA,
        StreamEventType.DELTA,
        StreamEventType.DONE,
    ]
    assert events[0].text == "The answer "
    assert events[1].text == "is 42."


def test_tool_use_sequence():
    events = list(parse_stream_json_lines(_load("stream_json_tool_use.txt")))
    types = [e.type for e in events]
    assert types == [
        StreamEventType.DELTA,        # "Let me read that file."
        StreamEventType.TOOL_USE,     # the Read call
        StreamEventType.TOOL_RESULT,  # the Read result
        StreamEventType.DELTA,        # "It contains a localhost entry."
        StreamEventType.DONE,
    ]
    assert events[1].tool_block["name"] == "Read"
    assert events[1].tool_block["input"] == {"file_path": "/etc/hosts"}
    assert events[2].tool_block["tool_use_id"] == "toolu_01"


def test_error_terminal_emits_error_event():
    events = list(parse_stream_json_lines(_load("stream_json_error.txt")))
    assert events[-1].type is StreamEventType.ERROR
    assert "max_turns" in events[-1].error


def test_blank_lines_are_ignored():
    lines = ["", "{\"type\":\"result\",\"subtype\":\"success\"}", ""]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE


def test_invalid_json_line_is_skipped_with_log(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    lines = ["not json at all", "{\"type\":\"result\",\"subtype\":\"success\"}"]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE
    assert any("invalid json" in r.message.lower() for r in caplog.records)


def test_unknown_event_type_is_skipped():
    lines = [
        '{"type":"weather_report","data":"sunny"}',
        '{"type":"result","subtype":"success"}',
    ]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE


def test_assistant_with_empty_content_is_skipped():
    events = list(parse_stream_json_lines(['{"type":"assistant","message":{"content":[]}}']))
    assert events == []


def test_assistant_with_missing_message_key_is_skipped():
    events = list(parse_stream_json_lines(['{"type":"assistant"}']))
    assert events == []


def test_assistant_with_multiple_blocks_yields_each():
    """A real Claude CLI assistant frame can contain multiple blocks in one
    content array (e.g., text followed by tool_use). The parser must yield
    one StreamEvent per block, not just the first."""
    lines = [
        '{"type":"assistant","message":{"content":['
        '{"type":"text","text":"Let me check"},'
        '{"type":"tool_use","id":"toolu_99","name":"Bash","input":{"command":"ls"}}'
        ']}}'
    ]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 2
    assert events[0].type is StreamEventType.DELTA
    assert events[0].text == "Let me check"
    assert events[1].type is StreamEventType.TOOL_USE
    assert events[1].tool_block["name"] == "Bash"


def test_unknown_result_subtype_is_treated_as_success_with_warning(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    lines = ['{"type":"result","subtype":"canceled_by_user","duration_ms":100}']
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE
    assert any("unknown result subtype" in r.message.lower() for r in caplog.records)
