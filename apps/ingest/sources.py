"""Where a session's raw JSONL comes from.

Before the run-execution convergence there was one answer: the local
`IngestUpload.raw_jsonl_gz` blob. Now there are two, and which one applies is a
property of the SESSION, not of the reader:

  * `source="local"`  — an uploaded transcript, or a locally-executed turn.
    SOURCE OF RECORD, always. Never refetched, never rewritten, never
    overwritten — see the hybrid case below.
  * `source="canopy"` — a cache of canopy's per-turn retained transcripts,
    keyed by the turn ids it was built from. canopy is the source of record;
    deleting this row is safe.

**A session can be BOTH**, and that case is why the two live in separate rows.
`dispatch_turn` stamps `canopy_session_id` onto an EXISTING session, and the
deploy hook resumes interrupted runs after every rollout — so the very deploy
that turns `CANOPY_RUN_EXECUTION` on takes runs that already executed locally
and gives them a canopy id. Their history is then local-prefix + canopy-suffix,
and canopy has never held the prefix: overwriting the local row with canopy's
bytes destroys it, with no copy anywhere and no error. So the canopy cache is a
SEPARATE row holding the COMPOSED bytes (local prefix + every canopy turn, in
turn order), and the local row is never written by this module at all.

Every read goes through `read_session_transcript` / `session_raw_jsonl`.
Nothing else may touch `raw_jsonl_gz` directly.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings

log = logging.getLogger(__name__)

# How long after a turn finishes its transcript is still treated as possibly
# growing. canopy allows appending to an already-TERMINAL turn by design (a
# runner may flush its last batch after calling /finish), so a turn-id list is
# not a complete cache key: it cannot change when a late flush lands. Inside
# this window the cache is provisional and every read refetches; outside it the
# turn set is the key again.
TRANSCRIPT_SETTLE_SECONDS = 120

_TERMINAL_MESSAGE_STATUSES = ("complete", "error")


@dataclass(frozen=True)
class TranscriptRead:
    """Bytes, WHY there are none, and whether they are the WHOLE run.

    `complete` is the one that guards money. A short transcript is not a
    smaller transcript — it parses fine, aggregates fine, and yields a cost
    that is simply too low, which no "refuse to lower" rule can see. So
    anything that knows the bytes might be partial says so here, and the cost
    writer refuses to persist a figure derived from a partial read.
    """

    raw: bytes | None
    # "" when raw is present. Otherwise one of the `unavailable_reason` values
    # the structure view renders.
    reason: str = ""
    # False when we know canopy holds transcript we could not get.
    complete: bool = True


def _actor_email(session) -> str:
    """Whose canopy identity a transcript fetch acts as.

    Mirrors `run_dispatch._actor_email`. A run dispatched under the fallback
    identity (an owner with no email — the exact case the fallback exists for)
    dispatches fine and reconciles fine; without the same fallback here it could
    never fetch its own transcript, and the failure is a log line.
    """
    email = (getattr(session.owner, "email", "") or "").strip()
    if email:
        return email
    return (settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL or "").strip()


def _canopy_turns(session) -> list[tuple[str, str]]:
    """(turn id, ace-web message status) in turn order.

    `turn_index` carries a DB unique constraint per session, so this ordering is
    total and cannot contain duplicates.
    """
    from apps.sessions.models import Message

    return list(
        Message.objects.filter(session=session, role="assistant")
        .exclude(canopy_turn_id="")
        .order_by("turn_index")
        .values_list("canopy_turn_id", "status")
    )


def _canopy_turn_ids(session) -> list[str]:
    return [tid for tid, _status in _canopy_turns(session)]


def _newest_row(session, source: str | None = None):
    from apps.sessions.models import IngestUpload

    qs = IngestUpload.objects.filter(session=session)
    if source is not None:
        qs = qs.filter(source=source)
    # `-id` breaks a `created_at` tie deterministically, so every reader of
    # "the newest row" (here and the structure view's ETag) resolves the same one.
    return qs.order_by("-created_at", "-id").first()


def local_row(session):
    """The session's local source-of-record row, if it has one."""
    from apps.sessions.models import IngestUpload

    return _newest_row(session, IngestUpload.SOURCE_LOCAL)


def _decompress(row) -> tuple[bytes | None, str]:
    """(bytes, reason). A corrupt blob reads as `parse-failed`, which is what it
    surfaced as before this seam existed (the gunzip used to sit inside
    `get_structure_tree`'s own try/except)."""
    if row is None or not row.raw_jsonl_gz:
        return None, "no-raw-jsonl"
    try:
        return gzip.decompress(bytes(row.raw_jsonl_gz)), ""
    except (OSError, EOFError):  # BadGzipFile is an OSError
        log.warning("unreadable raw_jsonl_gz on ingest row %s", row.pk, exc_info=True)
        return None, "parse-failed"


def _local_prefix(session) -> bytes:
    """Bytes this session produced BEFORE it was ever dispatched to canopy.

    Empty for a session that only ever ran on canopy. Non-empty exactly for the
    hybrid case, and those bytes exist nowhere else in the world.
    """
    raw, _reason = _decompress(local_row(session))
    return raw or b""


def _cache_is_provisional(session) -> bool:
    """True while the newest canopy turn's transcript may still be growing.

    The turn-id list cannot express this: it is identical before and after a
    late flush. So a turn that is still running, or finished within
    `TRANSCRIPT_SETTLE_SECONDS`, forces a refetch regardless of the key.
    """
    from django.utils import timezone

    from apps.sessions.models import Message

    message = (
        Message.objects.filter(session=session, role="assistant")
        .exclude(canopy_turn_id="")
        .order_by("-turn_index")
        .first()
    )
    if message is None:
        return False
    if message.status not in _TERMINAL_MESSAGE_STATUSES:
        # `completed_at` alone would not catch this: `reconcile_session` flips a
        # turn back to streaming/pending when canopy says it is alive again and
        # never clears the old timestamp, so a resumed turn looks settled by
        # clock while its transcript is actively growing.
        return True
    # `updated_at` is `auto_now` and therefore always present; falling back to
    # it means a terminal turn that never got a `completed_at` still settles,
    # rather than refetching from canopy on every read for the rest of time.
    stamp = message.completed_at or message.updated_at
    return (timezone.now() - stamp).total_seconds() < TRANSCRIPT_SETTLE_SECONDS


def refresh_canopy_cache(session):
    """Pull every turn's transcript from canopy and re-seat the CANOPY row.

    Returns the IngestUpload, or None when there is nothing to fetch or the
    fetch failed. Raises nothing: a canopy outage must degrade to stale bytes,
    never to a 500 on the structure view.

    Two invariants:
      * It never writes a `source="local"` row. The composed bytes go to the
        canopy row, which is created if absent — the local blob is read and
        left alone.
      * All-or-nothing. If any turn's fetch fails, nothing is written: a cache
        holding turns 1..n-1 while claiming to be the whole run is the
        silently-wrong-cost failure this seam exists to avoid.
    """
    from apps.canopy import client, transcripts
    from apps.sessions.models import IngestUpload

    turns = _canopy_turns(session)
    turn_ids = [tid for tid, _s in turns]
    if not turn_ids:
        return None
    try:
        token = client.exchange_token(_actor_email(session), ttl=300)["token"]
        blobs = [transcripts.fetch_turn_transcript(token, tid) for tid in turn_ids]
    except Exception:  # noqa: BLE001 — never let a canopy blip break a read
        # `error`, not `warning`: there is no Sentry on this deployment, and a
        # refused encoding or an over-ceiling transcript is a real incident that
        # otherwise surfaces only as a missing cost.
        log.error(
            "canopy transcript fetch FAILED for session %s (cost will be missing, not wrong)",
            session.slug, exc_info=True,
        )
        return None

    # An empty 200 is a normal answer for a turn that never produced output —
    # a cancelled or lost turn genuinely has nothing. It is NOT a normal answer
    # for a turn ace-web recorded as `complete`: that turn ran and said
    # something, so an empty body means the runner has not flushed yet (or
    # never will). Composing it as if it were finished yields a transcript that
    # is short rather than smaller, which is invisible to every downstream
    # check — so refuse the whole compose, exactly as a fetch error does.
    missing = [
        tid
        for (tid, status), blob in zip(turns, blobs, strict=True)
        if not blob and status == "complete"
    ]
    if missing:
        log.error(
            "canopy returned an EMPTY transcript for completed turn(s) %s on session %s; "
            "refusing to cache a short compose (cost will be missing, not wrong)",
            missing, session.slug,
        )
        return None

    # The local prefix leads, because it happened first. canopy's per-turn
    # transcripts are the CLI's per-invocation stdout, not a re-read of the
    # session file, so concatenating them cannot double-count — the same
    # assumption `store_session_transcript` has always made across turns.
    raw = _local_prefix(session) + b"".join(blobs)
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
    # Re-seat THE CANOPY ROW specifically — never `update_or_create(session=…)`,
    # which both raises MultipleObjectsReturned on a session with two rows and,
    # worse, would happily land on the local one.
    row = _newest_row(session, IngestUpload.SOURCE_CANOPY)
    if row is None:
        return IngestUpload.objects.create(session=session, **defaults)
    for field, value in defaults.items():
        setattr(row, field, value)
    row.save(update_fields=list(defaults))
    return row


def read_session_transcript(session, *, force_refresh: bool = False) -> TranscriptRead:
    """The session's full raw JSONL, why there is none, and whether it is whole.

    THE single read path for transcript bytes. `force_refresh` bypasses the
    cache entirely — used at the one moment we most want to be right (a turn
    going terminal) and by the explicit recompute command.
    """
    from apps.sessions.models import IngestUpload

    if not session.canopy_session_id:
        # Local source of record — an uploaded transcript or a pre-canopy run.
        raw, reason = _decompress(_newest_row(session))
        return TranscriptRead(raw, reason)

    wanted = _canopy_turn_ids(session)
    row = _newest_row(session, IngestUpload.SOURCE_CANOPY)
    prefix = _local_prefix(session)
    cached, cached_reason = _decompress(row)
    stale = (
        force_refresh
        or row is None
        or cached is None
        or list(row.canopy_turn_ids or []) != wanted
        # The composed bytes must still open with the CURRENT local prefix —
        # otherwise a local turn landed after this cache was seated and the
        # cache no longer covers the whole run.
        or not cached.startswith(prefix)
        or _cache_is_provisional(session)
    )
    fetch_failed = False
    if stale and wanted:
        refreshed = refresh_canopy_cache(session)
        if refreshed is not None:
            row = refreshed
            cached, cached_reason = _decompress(row)
        else:
            # We KNOW canopy holds transcript we could not get: an unreachable
            # canopy, a refused encoding, an over-ceiling turn, or a completed
            # turn that came back empty. Whatever we serve below is a prefix of
            # the run, not the run.
            fetch_failed = True

    if cached is not None:
        return TranscriptRead(cached, "", complete=not fetch_failed)
    if prefix:
        # canopy is unreachable and this session has local bytes. Half the run
        # beats none of it, and it is never MORE than the truth.
        return TranscriptRead(prefix, "", complete=not fetch_failed)
    if fetch_failed:
        return TranscriptRead(None, "canopy-unreachable", complete=False)
    if cached_reason == "parse-failed":
        return TranscriptRead(None, "parse-failed")
    return TranscriptRead(None, "no-raw-jsonl")


def session_raw_jsonl(session, *, force_refresh: bool = False) -> bytes | None:
    """The session's full raw JSONL, or None if there is none to be had."""
    return read_session_transcript(session, force_refresh=force_refresh).raw
