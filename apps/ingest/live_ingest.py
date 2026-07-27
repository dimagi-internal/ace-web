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
    #
    # Scoped to the LOCAL row on purpose. A session that has also run on canopy
    # carries a second, `source="canopy"` row holding the composed transcript;
    # accumulating onto that would fold canopy's bytes into the local source of
    # record and double them on the next compose.
    from apps.ingest.sources import local_row

    existing = local_row(session)
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

    defaults = {
        "uploaded_by": session.owner,
        "source": IngestUpload.SOURCE_LOCAL,
        "source_path": f"<live:{session.slug}>",
        "raw_bytes": parsed.raw_bytes,
        "line_count": parsed.line_count,
        "cli_session_id": parsed.cli_session_id or (session.cli_session_id or ""),
        "content_sha256": parsed.content_sha256 or "",
        "workspace": session.workspace,
        "raw_jsonl_gz": gzip.compress(full_bytes),
    }
    # Re-seat the LOCAL row, never `update_or_create(session=…)`: a session with
    # both a local and a canopy row raises MultipleObjectsReturned on that, and
    # a session that has been to canopy now always has two.
    if existing is None:
        IngestUpload.objects.create(session=session, **defaults)
    else:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save(update_fields=list(defaults))
    return breakdown


def recompute_cost_from_source(session) -> dict:
    """Recompute `Session.cost_breakdown` from whatever the transcript source
    currently yields.

    The canopy-era counterpart to `store_session_transcript`. That function
    exists because the local turn driver held the bytes and had to persist them;
    this one runs when a canopy turn goes terminal, reads the bytes back from
    canopy (via `sources.session_raw_jsonl`, which seats the cache), and writes
    only the derived breakdown. It never touches `raw_jsonl_gz` — the cache is
    `sources`' business, not this module's.
    """
    from apps.ingest import cost_aggregator
    from apps.ingest.parser import parse_session_bytes
    from apps.ingest.sources import session_raw_jsonl

    raw = session_raw_jsonl(session)
    if not raw:
        return {}
    _parsed, cost_events = parse_session_bytes(raw)
    try:
        breakdown = cost_aggregator.aggregate(cost_events)
    except Exception:  # noqa: BLE001 — analytics must never break a run
        log.exception("cost aggregator failed for canopy session %s", session.slug)
        return {}
    if _would_under_report(session.cost_breakdown, breakdown):
        # A session's cost only ever accumulates. A newly-derived figure that is
        # SMALLER than the stored one therefore means we read fewer bytes than
        # last time — a truncated fetch, a lost local prefix, a partial cache.
        # Keep the larger number and say so loudly: an unchanged cost is
        # visible in the logs, a silently shrunken one is visible nowhere.
        log.error(
            "refusing to lower cost for session %s: stored totals %s, recomputed %s "
            "— the transcript source returned less than it did before",
            session.slug, session.cost_breakdown.get("totals"), breakdown.get("totals"),
        )
        return session.cost_breakdown
    session.cost_breakdown = breakdown
    session.save(update_fields=["cost_breakdown", "updated_at"])
    return breakdown


def _billable_tokens(breakdown) -> int:
    totals = (breakdown or {}).get("totals") or {}
    return sum(
        int(totals.get(k, 0) or 0)
        for k in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")
    )


def _would_under_report(stored, fresh) -> bool:
    """True when overwriting `stored` with `fresh` would lower a run's cost."""
    if not stored or not (stored.get("totals") or {}):
        return False
    return _billable_tokens(fresh) < _billable_tokens(stored)
