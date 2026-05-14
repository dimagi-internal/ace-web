"""Round-trip tests for apps.ingest.schemas."""
from __future__ import annotations

from apps.ingest.schemas import IngestDuplicateOut, IngestUploadOut
from apps.sessions.schemas import CostBreakdownOut


def test_ingest_upload_out_minimal():
    """Minimal response — no cost breakdown, no opp linkage."""
    obj = IngestUploadOut(session_slug="abc-123", messages_imported=7)
    d = obj.model_dump()
    assert d["session_slug"] == "abc-123"
    assert d["messages_imported"] == 7
    assert d["cost_breakdown"] is None
    assert d["opp_slug"] is None


def test_ingest_upload_out_with_cost_breakdown():
    """Response with a cost breakdown attached."""
    breakdown = CostBreakdownOut(schema_version=2, totals=None, phases=[])
    obj = IngestUploadOut(
        session_slug="slug-xyz",
        messages_imported=42,
        cli_session_id="cli-sess-1",
        opp_slug="my-opp",
        opp_run_id="run-001",
        opp_step_skill="idea-to-pdd",
        cost_breakdown=breakdown,
    )
    d = obj.model_dump()
    assert d["cli_session_id"] == "cli-sess-1"
    assert d["opp_slug"] == "my-opp"
    assert d["cost_breakdown"]["schema_version"] == 2


def test_ingest_duplicate_out_round_trip():
    obj = IngestDuplicateOut(
        code="duplicate",
        message="Session abc already uploaded",
        cli_session_id="abc",
    )
    assert obj.code == "duplicate"
    assert obj.cli_session_id == "abc"
