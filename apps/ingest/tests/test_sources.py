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


def _session(canopy_session_id="", email="o@dimagi.com"):
    user = User.objects.create_user(email=email)
    return user, Session.create_with_owner(
        owner=user, title="t", opp_slug="o", opp_run_id="r",
        canopy_session_id=canopy_session_id,
    )


def _turn(session, turn_index, canopy_turn_id):
    return Message.objects.create(
        session=session, turn_index=turn_index, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id=canopy_turn_id,
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


@override_settings(**ON)
def test_a_local_row_on_a_canopy_session_is_treated_as_stale_and_refetched():
    """A run that started locally and was later dispatched to canopy has a
    `source="local"` row whose bytes are only half the story. The turn-id list
    matching is not enough — the LABEL has to match too."""
    user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    IngestUpload.objects.create(
        session=s, uploaded_by=user, source=IngestUpload.SOURCE_LOCAL,
        canopy_turn_ids=["turn-a"], raw_jsonl_gz=gzip.compress(LINE_B),
    )
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        assert sources.session_raw_jsonl(s) == LINE_A
    assert IngestUpload.objects.get(session=s).source == "canopy"


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
        assert sources.session_raw_jsonl(s) == LINE_A   # stale, but never an exception


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
        assert sources.session_raw_jsonl(s) == LINE_A
    assert IngestUpload.objects.filter(session=s).count() == 2


def test_an_unreadable_blob_reads_as_no_transcript_not_an_exception():
    """A corrupt blob used to be caught by `get_structure_tree`'s own
    try/except, which now sits downstream of this call."""
    user, s = _session()
    IngestUpload.objects.create(session=s, uploaded_by=user, raw_jsonl_gz=b"not gzip at all")
    assert sources.session_raw_jsonl(s) is None


@override_settings(**ON)
def test_refresh_records_the_cache_metadata_the_structure_etag_reads():
    _user, s = _session(canopy_session_id="sess-1")
    _turn(s, 1, "turn-a")
    exchange, fetch = _canopy_up({"turn-a": LINE_A})
    with exchange, fetch:
        row = sources.refresh_canopy_cache(s)
    assert row is not None
    assert row.raw_bytes == len(LINE_A)
    assert row.line_count == 1
    assert row.content_sha256   # /structure's ETag is built from this
