"""apps.ingest.sources — where a session's raw JSONL comes from."""

import gzip
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.ingest import sources
from apps.sessions.models import IngestUpload, Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db

ON = dict(
    CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c",
    CANOPY_WORKSPACE="connect", CANOPY_AGENT_SLUG="ace", CANOPY_RUN_EXECUTION=True,
)

LINE_A = b'{"type":"assistant","uuid":"a"}\n'
LINE_B = b'{"type":"assistant","uuid":"b"}\n'


_SETTLED = object()   # sentinel — resolved per call, see `_turn`


def _settled():
    """A completion timestamp far enough in the past that the transcript is no
    longer treated as possibly still growing."""
    from datetime import timedelta

    from django.utils import timezone

    return timezone.now() - timedelta(seconds=sources.TRANSCRIPT_SETTLE_SECONDS + 60)


def _session(canopy_session_id="", email="o@dimagi.com"):
    user = User.objects.create_user(email=email)
    return user, Session.create_with_owner(
        owner=user, title="t", opp_slug="o", opp_run_id="r",
        canopy_session_id=canopy_session_id,
    )


def _turn(session, turn_index, canopy_turn_id, *, status="complete", completed_at=_SETTLED):
    """An assistant turn that canopy has finished with, long enough ago that
    its transcript has settled (see `sources.TRANSCRIPT_SETTLE_SECONDS`)."""
    return Message.objects.create(
        session=session, turn_index=turn_index, role="assistant", content={"text": ""},
        status=status, canopy_turn_id=canopy_turn_id,
        completed_at=_settled() if completed_at is _SETTLED else completed_at,
    )


def _canopy_up(fetched):
    """Patch the two canopy calls `refresh_canopy_cache` makes."""
    return (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}),
        mock.patch(
            "apps.canopy.transcripts.fetch_turn_transcript",
            side_effect=lambda tok, tid, **kw: fetched[tid],
        ),
    )


def test_a_local_upload_is_still_read_from_the_local_blob():
    user, s = _session()
    IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_A), line_count=1,
    )
    assert sources.session_raw_jsonl(s) == LINE_A


def test_a_row_with_no_source_defaults_to_local():
    user, s = _session()
    row = IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_A),
    )
    assert row.source == "local"


def test_a_session_with_no_transcript_anywhere_reads_as_none():
    _user, s = _session()
    assert sources.session_raw_jsonl(s) is None


@override_settings(**ON)
def test_a_local_session_never_calls_canopy_even_when_a_turn_id_exists():
    """`canopy_session_id` is the discriminator, not the presence of a turn id.
    A pre-migration run's bytes are its own; going to canopy for them would
    replace a source of record with an empty fetch."""
    user, s = _session()
    _turn(s, 1, "turn-a")
    IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_A), line_count=1,
    )
    with mock.patch("apps.canopy.client.exchange_token") as exchange:
        assert sources.session_raw_jsonl(s) == LINE_A
    exchange.assert_not_called()


@override_settings(**ON)
def test_a_canopy_session_concatenates_its_turns_transcripts_in_turn_order():
    _user, s = _session(canopy_session_id="sess-1")
    for idx, turn in ((1, "turn-a"), (3, "turn-b")):
        _turn(s, idx, turn)
    exchange, fetch = _canopy_up({"turn-a": LINE_A, "turn-b": LINE_B})
    with exchange, fetch:
        out = sources.session_raw_jsonl(s)
    assert out == LINE_A + LINE_B


@override_settings(**ON)
def test_turn_order_follows_turn_index_not_row_creation_order():
    """A resumed run writes its assistant rows out of creation order. The
    transcript must still concatenate in the order the turns RAN, or cost's
    per-phase attribution reads a rearranged run."""
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 5, "turn-b")   # created first, ran second
    _turn(s, 1, "turn-a")
    exchange, fetch = _canopy_up({"turn-a": LINE_A, "turn-b": LINE_B})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_A + LINE_B


@override_settings(**ON)
def test_the_canopy_fetch_is_cached_and_not_refetched():
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as fetch:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)
    assert fetch.call_count == 1
    row = IngestUpload.objects.get(session=s)
    assert row.source == "canopy"
    assert row.canopy_turn_ids == ["turn-a"]


@override_settings(**ON)
def test_a_new_turn_invalidates_the_cache_and_refetches():
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        sources.session_raw_jsonl(s)
    _turn(s, 3, "turn-b")
    exchange, fetch = _canopy_up({"turn-a": LINE_A, "turn-b": LINE_B})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_A + LINE_B
    assert IngestUpload.objects.get(session=s).canopy_turn_ids == ["turn-a", "turn-b"]


# ---------------------------------------------------------------------------
# The hybrid session: ran locally, then dispatched to canopy.
#
# `dispatch_turn` stamps `canopy_session_id` onto an EXISTING session and the
# deploy hook resumes interrupted runs after every rollout, so the deploy that
# flips the flag manufactures these. Their local prefix exists nowhere else.
# ---------------------------------------------------------------------------


def _hybrid(user, s):
    """A session with local bytes that has since acquired a canopy turn."""
    local = IngestUpload.objects.create(
        session=s, uploaded_by=user, source=IngestUpload.SOURCE_LOCAL,
        source_path="<live:x>", raw_jsonl_gz=gzip.compress(LINE_B), line_count=1,
    )
    _turn(s, 5, "turn-a")
    return local


@override_settings(**ON)
def test_a_hybrid_sessions_local_bytes_are_never_overwritten():
    """THE regression. canopy has never held the local prefix, so writing
    canopy's bytes over the local row destroys it — no copy anywhere, no error,
    and the run's cost silently drops to the canopy-only figure."""
    user, s = _session(canopy_session_id="sess-1")
    local = _hybrid(user, s)

    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        sources.session_raw_jsonl(s)

    local.refresh_from_db()
    assert local.source == IngestUpload.SOURCE_LOCAL
    assert gzip.decompress(bytes(local.raw_jsonl_gz)) == LINE_B   # untouched
    # …and the canopy bytes went to a SEPARATE row.
    assert IngestUpload.objects.filter(session=s).count() == 2
    canopy_row = IngestUpload.objects.get(session=s, source=IngestUpload.SOURCE_CANOPY)
    assert canopy_row.pk != local.pk


@override_settings(**ON)
def test_a_hybrid_sessions_transcript_is_the_local_prefix_plus_canopys_turns():
    """A hybrid run's history is local-then-canopy. Reading only canopy's half
    is what made the cost drop; reading both is what makes it right."""
    user, s = _session(canopy_session_id="sess-1")
    _hybrid(user, s)
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_B + LINE_A


@override_settings(**ON)
def test_a_hybrid_session_falls_back_to_its_local_bytes_when_canopy_is_down():
    """Half the run beats none of it, and it is never MORE than the truth."""
    from apps.canopy.client import CanopyError

    user, s = _session(canopy_session_id="sess-1")
    _hybrid(user, s)
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        assert sources.session_raw_jsonl(s) == LINE_B


@override_settings(**ON)
def test_a_local_turn_landing_after_the_cache_invalidates_it():
    """The turn-id list is unchanged when the LOCAL half grows, so the composed
    cache has to be checked against the current prefix as well."""
    user, s = _session(canopy_session_id="sess-1")
    local = _hybrid(user, s)
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_B + LINE_A

    local.raw_jsonl_gz = gzip.compress(LINE_B + LINE_B)
    local.save(update_fields=["raw_jsonl_gz"])
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_B + LINE_B + LINE_A


@override_settings(**ON)
def test_a_canopy_failure_falls_back_to_the_cached_bytes_and_never_raises():
    from apps.canopy.client import CanopyError

    user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    IngestUpload.objects.create(
        session=s, uploaded_by=user, source="canopy", canopy_turn_ids=["turn-a"],
        raw_jsonl_gz=gzip.compress(LINE_A),
    )
    _turn(s, 3, "turn-b")
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        read = sources.read_session_transcript(s)
    assert read.raw == LINE_A   # stale, but never an exception
    # …and it must SAY it is stale. These bytes are missing turn-b, so a cost
    # derived from them is short — and short is invisible to every later check.
    assert read.complete is False


@override_settings(**ON)
def test_a_canopy_failure_with_no_cache_reads_as_none_not_an_exception():
    from apps.canopy.client import CanopyError

    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        assert sources.session_raw_jsonl(s) is None


@override_settings(**ON)
def test_a_fetch_failure_never_seats_a_cache_claiming_turns_it_does_not_hold():
    """If turn B's fetch blows up, the cache row must not come back saying it
    holds turn B. A row keyed ["turn-a","turn-b"] whose bytes are turn A only
    is INDISTINGUISHABLE FROM COMPLETE — every later read sees a matching key,
    skips the refetch, and the run's cost is short forever with no symptom.

    (This is the invariant, not "all-or-nothing": a hypothetical implementation
    that seated turn A's bytes under the key ["turn-a"] would also satisfy it,
    because that row is honestly labelled and the next read refetches.)"""
    from apps.canopy.transcripts import TranscriptTooLarge

    user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    _turn(s, 3, "turn-b")
    IngestUpload.objects.create(
        session=s, uploaded_by=user, source="canopy", canopy_turn_ids=["turn-a"],
        raw_jsonl_gz=gzip.compress(LINE_A),
    )

    def _boom(tok, tid, **kw):
        if tid == "turn-b":
            raise TranscriptTooLarge("too big")
        return LINE_A

    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", side_effect=_boom):
        assert sources.session_raw_jsonl(s) == LINE_A
    row = IngestUpload.objects.get(session=s)
    assert "turn-b" not in (row.canopy_turn_ids or [])
    assert gzip.decompress(bytes(row.raw_jsonl_gz)) == LINE_A

    # …and because the row does not claim turn B, the next read retries it.
    exchange, fetch = _canopy_up({"turn-a": LINE_A, "turn-b": LINE_B})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_A + LINE_B


@override_settings(**ON)
def test_a_dispatched_session_with_no_turn_ids_yet_reads_as_none():
    """Dispatch failed before canopy returned a turn id. There is nothing to
    fetch; there must also be nothing invented."""
    _user, s = _session(canopy_session_id="sess-1")
    Message.objects.create(
        session=s, turn_index=1, role="assistant", content={"text": ""}, status="pending",
    )
    with mock.patch("apps.canopy.client.exchange_token") as exchange:
        assert sources.session_raw_jsonl(s) is None
    exchange.assert_not_called()


@override_settings(**ON)
def test_a_session_carrying_more_than_one_ingest_row_still_refreshes():
    """`IngestUpload` is not unique per session — the upload path `create()`s.
    A refresh must re-seat the newest row, not raise MultipleObjectsReturned
    from inside a read path that is documented never to raise."""
    user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    for _ in range(2):
        IngestUpload.objects.create(
            session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_B),
        )
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_B + LINE_A
    # Both local rows survive; the canopy bytes went to a third, new row.
    assert IngestUpload.objects.filter(session=s, source="local").count() == 2
    assert IngestUpload.objects.filter(session=s, source="canopy").count() == 1


def test_an_unreadable_blob_reads_as_no_transcript_not_an_exception():
    """A corrupt blob used to be caught by `get_structure_tree`'s own
    try/except, which now sits downstream of this call."""
    user, s = _session()
    IngestUpload.objects.create(session=s, uploaded_by=user, raw_jsonl_gz=b"not gzip at all")
    assert sources.session_raw_jsonl(s) is None


@override_settings(**ON)
def test_refresh_records_the_cache_metadata_over_the_bytes_it_actually_stored():
    import hashlib

    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        row = sources.refresh_canopy_cache(s)
    assert row is not None
    assert row.raw_bytes == len(LINE_A)
    assert row.line_count == 1
    # The hash must be over THESE bytes — a hash over the wrong content is a
    # cache key that silently agrees with everything.
    assert row.content_sha256 == hashlib.sha256(LINE_A).hexdigest()


# ---------------------------------------------------------------------------
# Identity + freshness
# ---------------------------------------------------------------------------


@override_settings(**ON, CANOPY_RUN_ACTOR_FALLBACK_EMAIL="ace@dimagi-ai.com")
def test_a_fetch_acts_as_the_fallback_identity_when_the_owner_has_no_email():
    """A run dispatched under the fallback identity — the exact case the
    fallback exists for — must be able to fetch its own transcript. Without the
    same fallback here it dispatches fine, reconciles fine, and can never read
    a transcript; the failure is one log line."""
    user, s = _session(canopy_session_id="sess-1")
    User.objects.filter(pk=user.pk).update(email="")
    s.refresh_from_db()
    _turn(s, 1, "turn-a")
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}) as ex, \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A):
        assert sources.session_raw_jsonl(s) == LINE_A
    assert ex.call_args.args[0] == "ace@dimagi-ai.com"


@override_settings(**ON)
def test_a_turn_that_only_just_finished_is_refetched_even_though_its_id_is_cached():
    """canopy allows appending to an already-TERMINAL turn (a runner may flush
    its last batch after /finish). The turn-id list is identical before and
    after that flush, so keying on it alone freezes a short transcript — and a
    short transcript is a permanently wrong cost."""
    from django.utils import timezone

    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a", completed_at=timezone.now())   # just now
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as f:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)
    assert f.call_count == 2


@override_settings(**ON)
def test_a_still_running_turn_is_refetched_every_read():
    """`completed_at` alone is not enough: `reconcile_session` flips a turn's
    status back to streaming/pending when canopy says it is alive again, and
    never clears the old `completed_at`. A resumed turn therefore looks settled
    by timestamp while its transcript is actively growing."""
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a", status="streaming")   # settled timestamp, live turn
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as f:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)
    assert f.call_count == 2


@override_settings(**ON)
def test_a_terminal_turn_with_no_completed_at_still_settles():
    """A turn completed by the legacy driver carries no `completed_at`. If that
    meant "provisional forever", such a session would refetch every turn from
    canopy on every page view, permanently."""
    _user, s = _session(canopy_session_id="sess-1")
    msg = _turn(s, 1, "turn-a", completed_at=None)
    # `.update()` bypasses auto_now, which `.save()` would overwrite.
    Message.objects.filter(pk=msg.pk).update(updated_at=_settled())
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as f:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)
    assert f.call_count == 1


@override_settings(**ON)
def test_a_terminal_turn_with_no_completed_at_is_provisional_while_it_is_fresh():
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a", completed_at=None)   # updated_at is now
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as f:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)
    assert f.call_count == 2


@override_settings(**ON)
def test_a_canopy_read_reports_why_it_has_nothing():
    """`/structure` used to distinguish "never recorded" from "unreadable"; the
    seam must keep those apart, and add "canopy could not be reached"."""
    from apps.canopy.client import CanopyError

    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        assert sources.read_session_transcript(s).reason == "canopy-unreachable"


def test_a_corrupt_local_blob_reports_parse_failed_not_no_raw_jsonl():
    user, s = _session()
    IngestUpload.objects.create(session=s, uploaded_by=user, raw_jsonl_gz=b"not gzip at all")
    read = sources.read_session_transcript(s)
    assert read.raw is None
    assert read.reason == "parse-failed"


# ---------------------------------------------------------------------------
# Short is not smaller: a compose that is missing content must never look done
# ---------------------------------------------------------------------------


@override_settings(**ON)
def test_an_empty_transcript_for_a_completed_turn_is_not_treated_as_success():
    """canopy answers 200-with-nothing for a turn whose runner has not flushed.
    Composing that as if it were finished yields a transcript that is SHORT —
    it parses, it aggregates, and the cost is simply too low. No downstream
    check can see that, so refuse the compose instead."""
    user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")            # status="complete"
    _turn(s, 3, "turn-b")
    blobs = {"turn-a": LINE_A, "turn-b": b""}
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=lambda tok, tid, **kw: blobs[tid],
         ):
        read = sources.read_session_transcript(s)
    assert read.complete is False
    assert not IngestUpload.objects.filter(session=s, source="canopy").exists()


@override_settings(**ON)
def test_an_empty_transcript_for_a_turn_that_never_ran_is_fine():
    """A cancelled or lost turn genuinely produced nothing. Treating THAT as a
    failure would block the session's cost forever for no reason."""
    user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    _turn(s, 3, "turn-b", status="error")   # canopy:cancelled — never executed
    blobs = {"turn-a": LINE_A, "turn-b": b""}
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=lambda tok, tid, **kw: blobs[tid],
         ):
        read = sources.read_session_transcript(s)
    assert read.complete is True
    assert read.raw == LINE_A


@override_settings(**ON)
def test_a_permanently_404ing_turn_reads_as_incomplete_not_as_the_whole_run():
    """One unfetchable turn used to wedge the read at local-prefix-only and say
    nothing about it. It still serves the prefix — half a run beats none — but
    it no longer claims to be the run."""
    from apps.canopy.client import CanopyError

    user, s = _session(canopy_session_id="sess-1")
    _hybrid(user, s)
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=CanopyError(404, "no such turn"),
         ):
        read = sources.read_session_transcript(s)
    assert read.raw == LINE_B     # the local prefix
    assert read.complete is False


@override_settings(**ON)
def test_a_permanently_404ing_turn_recovers_by_itself_once_canopy_answers():
    """Nothing bad is cached, so the read self-heals — no repair step."""
    from apps.canopy.client import CanopyError

    user, s = _session(canopy_session_id="sess-1")
    _hybrid(user, s)
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=CanopyError(404, "no such turn"),
         ):
        sources.read_session_transcript(s)
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        read = sources.read_session_transcript(s)
    assert read.raw == LINE_B + LINE_A
    assert read.complete is True


@override_settings(**ON)
def test_force_refresh_bypasses_a_cache_that_looks_perfectly_fresh():
    """canopy permits appending to an ALREADY-TERMINAL turn, so a settled cache
    can still be short. The terminal reconcile forces a refetch for exactly
    that reason."""
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as f:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)                       # cached
        assert f.call_count == 1
        sources.session_raw_jsonl(s, force_refresh=True)   # not cached
        assert f.call_count == 2


@override_settings(**ON)
def test_a_local_session_is_always_complete():
    """Its bytes are its own; there is no elsewhere for them to be."""
    user, s = _session()
    IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_A),
    )
    assert sources.read_session_transcript(s).complete is True
