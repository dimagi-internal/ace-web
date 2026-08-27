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

    parsed, _cost_events = parse_session_bytes(full_bytes)
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

    # Cost is derived AFTER the row is written, and from the SEAM — never from
    # `full_bytes`. For a purely local session those are the same bytes, so the
    # number is identical to what this function has always produced. For a
    # session that has also run on canopy they are not: `full_bytes` is the
    # local half, and writing a local-only cost over a composed one is the same
    # silent drop, in the other direction. One derivation, one writer.
    return recompute_cost_from_source(session)


def recompute_cost_from_source(
    session, *, force_refresh: bool = False, force: bool = False
) -> dict:
    """Recompute `Session.cost_breakdown` from whatever the transcript source
    currently yields. **THE ONLY WRITER of `Session.cost_breakdown`.**

    That is the invariant, and it is why `store_session_transcript` now ends by
    calling this instead of writing a number of its own: with two writers, each
    one's idea of "the transcript" wins in turn, and a session that has run on
    both sides gets whichever half wrote last.

    Two refusals, guarding two different failure shapes:

      * **incomplete** — the read is a known prefix of the run (canopy
        unreachable, a refused encoding, an over-ceiling turn, a completed turn
        that came back empty). The resulting figure is SHORT, not smaller, so
        the ratchet below cannot see it. Do not persist it at all.
      * **smaller** — a session's cost only accumulates, so a lower figure means
        we read fewer bytes than last time. Keep the larger one.

    `force_refresh` bypasses the transcript cache; `force` bypasses the
    refuse-smaller ratchet (see `manage.py recompute_session_cost`). Neither is
    reachable from a normal read path.
    """
    from apps.ingest import cost_aggregator
    from apps.ingest.parser import parse_session_bytes
    from apps.ingest.sources import read_session_transcript

    read = read_session_transcript(session, force_refresh=force_refresh)
    if not read.raw:
        return {}
    if not read.complete:
        # Short, not smaller. Nothing downstream can tell the difference, so
        # the only safe move is to leave the last known-good figure alone.
        log.error(
            "refusing to derive cost for session %s from an INCOMPLETE transcript "
            "(canopy holds bytes we could not read); keeping the stored figure",
            session.slug,
        )
        return session.cost_breakdown or {}
    _parsed, cost_events = parse_session_bytes(read.raw)
    try:
        breakdown = cost_aggregator.aggregate(cost_events)
    except Exception:  # noqa: BLE001 — analytics must never break a run
        log.exception("cost aggregator failed for canopy session %s", session.slug)
        return {}
    if not force and _would_under_report(session.cost_breakdown, breakdown):
        # A session's cost only ever accumulates. A newly-derived figure that is
        # SMALLER than the stored one therefore means we read fewer bytes than
        # last time — a truncated fetch, a lost local prefix, a partial cache.
        # Keep the larger number and say so loudly: an unchanged cost is
        # visible in the logs, a silently shrunken one is visible nowhere.
        log.error(
            "refusing to lower cost for session %s: stored totals %s, recomputed %s "
            "— the transcript source returned less than it did before. "
            "Override with `manage.py recompute_session_cost --slug %s --force`.",
            session.slug, session.cost_breakdown.get("totals"), breakdown.get("totals"),
            session.slug,
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
