"""Compute + persist a cost breakdown for a live (web-source) CLI session.

The upload path (`apps.ingest.api.process_ingest_upload`) computes a
`cost_breakdown` and stores the raw JSONL on an `IngestUpload` row for sessions
created from an uploaded transcript file. Web-source sessions (the seeded-run
action spawning `claude -p`) never went through that path, so they showed up in
the analyzer with an empty breakdown and no structure tree.

`store_session_transcript` closes that gap: the turn driver captures the raw
JSONL streamed from the subprocess and hands it here at turn end. We append it
to whatever transcript we've already stored for the session (so multi-turn
sessions accumulate), re-run the same parse + aggregate pipeline the upload path
uses, and persist `Session.cost_breakdown` plus an `IngestUpload.raw_jsonl_gz`
(which also powers the `/structure` endpoint). The Session row already exists,
so we update it in place rather than creating one.
"""
from __future__ import annotations

import gzip
import logging

log = logging.getLogger(__name__)


def store_session_transcript(session, new_raw_jsonl: str) -> dict:
    """Append this turn's raw JSONL, recompute the breakdown, persist both.

    Returns the computed cost breakdown (``{}`` on parse/aggregate failure —
    analytics must never break a turn).
    """
    from apps.ingest.cost_aggregator import aggregate
    from apps.ingest.parser import parse_session_bytes
    from apps.sessions.models import IngestUpload

    if not new_raw_jsonl:
        return {}

    # Accumulate across turns: a long-lived subprocess only streams the current
    # turn's events on stdout (prior history is loaded internally via --resume),
    # so the cumulative transcript is the concatenation of each turn's capture.
    existing = IngestUpload.objects.filter(session=session).order_by("-created_at").first()
    prior = (existing.read_raw_jsonl() if existing else "") or ""
    full_bytes = (prior + new_raw_jsonl).encode("utf-8")

    parsed, cost_events = parse_session_bytes(full_bytes)
    try:
        breakdown = aggregate(cost_events)
    except Exception:  # noqa: BLE001 — never let analytics break a turn
        log.exception("cost aggregator failed for live session %s", session.slug)
        breakdown = {}

    session.cost_breakdown = breakdown
    session.save(update_fields=["cost_breakdown", "updated_at"])

    IngestUpload.objects.update_or_create(
        session=session,
        defaults={
            "uploaded_by": session.owner,
            "source_path": f"<live:{session.slug}>",
            "raw_bytes": parsed.raw_bytes,
            "line_count": parsed.line_count,
            "cli_session_id": parsed.cli_session_id or (session.cli_session_id or ""),
            "content_sha256": parsed.content_sha256 or "",
            "workspace": session.workspace,
            "raw_jsonl_gz": gzip.compress(full_bytes),
        },
    )
    return breakdown
