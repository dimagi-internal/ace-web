"""Where a session's raw JSONL comes from.

Before the run-execution convergence there was one answer: the local
`IngestUpload.raw_jsonl_gz` blob. Now there are two, and which one applies is a
property of the SESSION, not of the reader:

  * `source="local"`  — an uploaded transcript, or a pre-canopy live capture.
    Source of record. Never refetched, never rewritten.
  * `source="canopy"` — a cache of canopy's per-turn retained transcripts,
    concatenated in turn order and keyed by the turn ids it was built from.
    canopy is the source of record; deleting this row is safe.

The discriminator is `Session.canopy_session_id`: a session ace-web executed
itself keeps its own bytes forever, whatever else is true of it.

Every read goes through `session_raw_jsonl`. Nothing else may touch
`raw_jsonl_gz` directly.
"""

from __future__ import annotations

import gzip
import hashlib
import logging

log = logging.getLogger(__name__)


def _canopy_turn_ids(session) -> list[str]:
    from apps.sessions.models import Message

    return [
        t
        for t in Message.objects.filter(session=session, role="assistant")
        .exclude(canopy_turn_id="")
        .order_by("turn_index")
        .values_list("canopy_turn_id", flat=True)
    ]


def _cached_row(session):
    from apps.sessions.models import IngestUpload

    return IngestUpload.objects.filter(session=session).order_by("-created_at").first()


def _decompress(row) -> bytes | None:
    """The row's bytes, or None if it has none / they are unreadable.

    A corrupt blob must read as "no transcript", not as a 500 on the structure
    view — that used to be covered by `get_structure_tree`'s own try/except,
    which now sits downstream of this call.
    """
    if row is None or not row.raw_jsonl_gz:
        return None
    try:
        return gzip.decompress(bytes(row.raw_jsonl_gz))
    except (OSError, EOFError):  # BadGzipFile is an OSError
        log.warning("unreadable raw_jsonl_gz on ingest row %s", row.pk, exc_info=True)
        return None


def refresh_canopy_cache(session):
    """Pull every turn's transcript from canopy and re-seat the cache row.

    Returns the IngestUpload, or None when there is nothing to fetch. Raises
    nothing: a canopy outage must degrade to stale bytes, never to a 500 on the
    structure view.

    All-or-nothing on purpose. If any turn's fetch fails, nothing is written —
    a cache holding turns 1..n-1 while claiming to be the whole run is the
    silently-wrong-cost failure this whole seam exists to avoid.
    """
    from apps.canopy import client, transcripts
    from apps.sessions.models import IngestUpload

    turn_ids = _canopy_turn_ids(session)
    if not turn_ids:
        return None
    try:
        email = (getattr(session.owner, "email", "") or "").strip()
        token = client.exchange_token(email, ttl=300)["token"]
        blobs = [transcripts.fetch_turn_transcript(token, tid) for tid in turn_ids]
    except Exception:  # noqa: BLE001 — never let a canopy blip break a read
        log.warning("canopy transcript fetch failed for session %s", session.slug, exc_info=True)
        return None

    raw = b"".join(blobs)
    defaults = {
        "uploaded_by": session.owner,
        "source": IngestUpload.SOURCE_CANOPY,
        "canopy_turn_ids": turn_ids,
        "source_path": f"<canopy:{session.canopy_session_id}>",
        "raw_bytes": len(raw),
        "line_count": raw.count(b"\n"),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_jsonl_gz": gzip.compress(raw),
        "workspace": session.workspace,
    }
    # Re-seat the row `_cached_row` reads rather than `update_or_create`: a
    # session may legitimately carry more than one IngestUpload (the upload
    # path `create()`s), and update_or_create raises MultipleObjectsReturned
    # on that — from inside a read path that is supposed to never raise.
    row = _cached_row(session)
    if row is None:
        return IngestUpload.objects.create(session=session, **defaults)
    for field, value in defaults.items():
        setattr(row, field, value)
    row.save(update_fields=list(defaults))
    return row


def session_raw_jsonl(session) -> bytes | None:
    """The session's full raw JSONL, or None if there is none to be had.

    THE single read path for transcript bytes. `apps/sessions/api.py::
    get_structure_tree` and `apps/ingest/live_ingest.py` both go through it.
    """
    from apps.sessions.models import IngestUpload

    row = _cached_row(session)
    if not session.canopy_session_id:
        # Local source of record — an uploaded transcript or a pre-canopy run.
        return _decompress(row)

    wanted = _canopy_turn_ids(session)
    stale = (
        row is None
        or row.source != IngestUpload.SOURCE_CANOPY
        or list(row.canopy_turn_ids or []) != wanted
    )
    if stale and wanted:
        refreshed = refresh_canopy_cache(session)
        if refreshed is not None:
            row = refreshed
    return _decompress(row)
