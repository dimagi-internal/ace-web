"""Receipt-time stamping of captured stream-json lines.

The CLI's stdout envelopes have no per-event timestamp, so a cost breakdown
built from them had a correct total but zero per-phase wall. _stamp_receipt_time
injects one as we read each line, restoring the timeline the aggregator needs."""
import json

from apps.common.cli_backend import _stamp_receipt_time


def test_adds_timestamp_when_missing():
    line = '{"type":"assistant","message":{"role":"assistant","content":[]}}\n'
    out = _stamp_receipt_time(line)
    obj = json.loads(out)
    assert "timestamp" in obj
    # Payload preserved.
    assert obj["type"] == "assistant"
    assert obj["message"]["role"] == "assistant"


def test_preserves_existing_timestamp():
    line = '{"type":"assistant","timestamp":"2026-01-01T00:00:00+00:00"}'
    out = _stamp_receipt_time(line)
    assert json.loads(out)["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_non_json_passthrough():
    assert _stamp_receipt_time("not json at all\n") == "not json at all\n"


def test_non_object_passthrough():
    # A bare JSON array/scalar isn't an envelope — leave it alone.
    assert _stamp_receipt_time("[1, 2, 3]") == "[1, 2, 3]"


def test_stamped_line_parses_into_cost_event_with_timestamp():
    """End-to-end with the parser: a stamped assistant line yields a
    CostEvent carrying the timestamp the aggregator reads for wall time."""
    from apps.ingest.parser import _extract_cost_events

    line = _stamp_receipt_time(
        '{"type":"assistant","message":{"role":"assistant",'
        '"usage":{"input_tokens":1,"output_tokens":1},'
        '"content":[{"type":"text","text":"hi"}]}}'
    )
    events = _extract_cost_events([line])
    assert events
    assert events[0].timestamp is not None
