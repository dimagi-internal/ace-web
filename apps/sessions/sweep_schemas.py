"""Schemas for the cross-workspace sweep API (apps/sessions/sweep_api.py)."""
from __future__ import annotations

import datetime as dt

from pydantic import Field

from apps.common.schemas import StrictModel

from .schemas import SessionSource, SessionStatus


class SweepSessionRow(StrictModel):
    """One row in the sweep listing.

    Summary-sized — no message bodies, no JSONL, no opp display names.
    Enough for the plugin-side report renderer to group by workspace and
    annotate which sessions came from /ace:upload-transcript.
    """

    id: int
    slug: str
    title: str = ""
    source: SessionSource
    status: SessionStatus
    opp_slug: str = ""
    opp_run_id: str = ""
    workspace_slug: str
    message_count: int = Field(ge=0)
    upload_count: int = Field(ge=0)
    created_at: dt.datetime
    updated_at: dt.datetime


class SweepListOut(StrictModel):
    sessions: list[SweepSessionRow]
    total_raw_bytes: int = Field(ge=0)


class SweepDeleteIn(StrictModel):
    """Body of POST /sessions/sweep/delete."""

    session_ids: list[int] = Field(default_factory=list)


class FailedDeleteOut(StrictModel):
    session_id: int
    # `not_found`, `forbidden`, or `db_error: <msg>`
    reason: str
