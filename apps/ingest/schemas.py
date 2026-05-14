"""Pydantic v2 schemas for the ingest surface.

The ingest endpoint accepts multipart form-data (file + optional fields);
Django Ninja handles multipart natively at the route level in Phase 2, so
there is no ``In`` schema here for the upload body itself.  These are the
response shapes only.

Field-name note: the DRF view returns ``message_count`` (not
``messages_imported``).  The Phase 2 view will normalize to
``messages_imported`` as the v2 public name; this schema uses the v2 name.
"""
from __future__ import annotations

from apps.common.schemas import StrictModel
from apps.sessions.schemas import CostBreakdownOut


class IngestUploadOut(StrictModel):
    """201 response from POST /api/v2/ingest/upload.

    ``cost_breakdown`` is null for sessions where the JSONL contained no
    cost-bearing assistant turns (empty or tool-only transcripts).
    ``opp_slug``, ``opp_run_id``, and ``opp_step_skill`` are null when the
    upload is an orphan (no opp linkage provided in the multipart body).
    """

    session_slug: str
    messages_imported: int
    cli_session_id: str | None = None
    opp_slug: str | None = None
    opp_run_id: str | None = None
    opp_step_skill: str | None = None
    cost_breakdown: CostBreakdownOut | None = None


class IngestDuplicateOut(StrictModel):
    """409 error body when a duplicate transcript is detected.

    Phase 2 wraps this in the RFC 7807 Problem envelope; the schema itself
    just captures the structured fields so the view can construct it cleanly.
    """

    code: str  # "duplicate"
    message: str
    cli_session_id: str | None = None
