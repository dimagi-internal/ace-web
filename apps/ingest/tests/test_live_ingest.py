"""Live (web-source) session cost ingest — the seeded-run equivalent of upload."""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

_INIT = '{"type":"system","subtype":"init","session_id":"live-1"}\n'


def _assistant_line(out_tokens: int) -> str:
    return (
        '{"type":"assistant","timestamp":"2026-01-01T00:00:00.000Z","message":'
        '{"role":"assistant","model":"claude-sonnet-4-6",'
        '"content":[{"type":"text","text":"hi"}],'
        '"usage":{"input_tokens":10,"output_tokens":' + str(out_tokens) + ','
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
    )


def _session():
    from apps.sessions.models import Session

    user = User.objects.create_user(email="live@example.com")
    return Session.create_with_owner(
        owner=user, source="web", status="active",
        cli_session_id="live-1", title="seeded-run",
    )


@pytest.mark.django_db
def test_stores_breakdown_and_raw_transcript():
    from apps.ingest.live_ingest import store_session_transcript
    from apps.sessions.models import IngestUpload

    session = _session()
    jsonl = _INIT + _assistant_line(5)

    breakdown = store_session_transcript(session, jsonl)

    assert breakdown["totals"]["output_tokens"] == 5
    session.refresh_from_db()
    # Equality (not subscripting) so the model's JSONField attribute isn't
    # indexed directly — django-stubs types it as JSONField, which trips
    # basedpyright's reportIndexIssue. Persisted breakdown == computed one.
    assert session.cost_breakdown == breakdown

    upload = IngestUpload.objects.get(session=session)
    assert upload.raw_jsonl_gz  # powers the /structure endpoint
    assert upload.read_raw_jsonl() == jsonl


@pytest.mark.django_db
def test_accumulates_across_turns():
    """A long-lived subprocess streams only the current turn's events; the
    stored transcript must accumulate so the breakdown covers the whole run."""
    from apps.ingest.live_ingest import store_session_transcript
    from apps.sessions.models import IngestUpload

    session = _session()
    store_session_transcript(session, _INIT + _assistant_line(5))
    breakdown = store_session_transcript(session, _assistant_line(7))  # turn 2, no init

    assert breakdown["totals"]["output_tokens"] == 12  # 5 + 7
    assert IngestUpload.objects.filter(session=session).count() == 1
    upload = IngestUpload.objects.get(session=session)
    assert upload.read_raw_jsonl() == _INIT + _assistant_line(5) + _assistant_line(7)


@pytest.mark.django_db
def test_empty_transcript_is_noop():
    from apps.ingest.live_ingest import store_session_transcript
    from apps.sessions.models import IngestUpload

    session = _session()
    assert store_session_transcript(session, "") == {}
    assert not IngestUpload.objects.filter(session=session).exists()


# ---------------------------------------------------------------------------
# recompute_cost_from_source — the canopy-era counterpart of
# store_session_transcript. It reads bytes back through apps.ingest.sources
# and writes ONLY the derived breakdown; the cache row is sources' business.
# ---------------------------------------------------------------------------

_CANOPY_TURN = (
    b'{"type":"assistant","timestamp":"2026-01-01T00:00:00.000Z","uuid":"u1","message":'
    b'{"role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"hi"}],'
    b'"usage":{"input_tokens":10,"output_tokens":5,'
    b'"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
)


def _canopy_session():
    from apps.sessions.models import Session

    user = User.objects.create_user(email="canopy-run@example.com")
    return user, Session.create_with_owner(
        owner=user, source="web", status="active", title="seeded-run",
        opp_slug="o", opp_run_id="r", canopy_session_id="sess-1",
    )


@pytest.mark.django_db
def test_recompute_cost_from_source_uses_the_canopy_transcript():
    from unittest import mock

    from apps.ingest import live_ingest

    _user, session = _canopy_session()
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=_CANOPY_TURN):
        breakdown = live_ingest.recompute_cost_from_source(session)

    session.refresh_from_db()
    assert session.cost_breakdown == breakdown
    assert breakdown["totals"]["input_tokens"] == 10
    assert breakdown["totals"]["output_tokens"] == 5


@pytest.mark.django_db
def test_recompute_cost_is_a_noop_when_there_is_no_transcript():
    from unittest import mock

    from apps.ingest import live_ingest

    _user, session = _canopy_session()
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=None):
        assert live_ingest.recompute_cost_from_source(session) == {}
    session.refresh_from_db()
    assert session.cost_breakdown == {}


@pytest.mark.django_db
def test_recompute_cost_never_touches_the_transcript_bytes():
    """The cache row belongs to `sources`. If this function ever writes
    raw_jsonl_gz it becomes a second writer of the thing canopy is the source
    of record for."""
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.sessions.models import IngestUpload

    user, session = _canopy_session()
    row = IngestUpload.objects.create(
        session=session, uploaded_by=user, source="canopy",
        canopy_turn_ids=["turn-a"], raw_jsonl_gz=b"sentinel-bytes",
    )
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=_CANOPY_TURN):
        live_ingest.recompute_cost_from_source(session)
    row.refresh_from_db()
    assert bytes(row.raw_jsonl_gz) == b"sentinel-bytes"


@pytest.mark.django_db
def test_recompute_cost_survives_an_aggregator_failure():
    """Analytics must never break a run — the same contract
    store_session_transcript has held since it was written."""
    from unittest import mock

    from apps.ingest import live_ingest

    _user, session = _canopy_session()
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=_CANOPY_TURN), \
         mock.patch("apps.ingest.cost_aggregator.aggregate", side_effect=RuntimeError("boom")):
        assert live_ingest.recompute_cost_from_source(session) == {}


@pytest.mark.django_db
def test_a_pre_migration_runs_cost_is_identical_through_the_new_seam():
    """THE regression that matters. A run recorded before any of this existed
    has `source="local"` bytes and no canopy_session_id; deriving its cost
    through the new seam must produce the same number the old write-time path
    produced, to the field. A silently different cost is indistinguishable from
    a real change."""
    from apps.ingest import live_ingest

    session = _session()
    write_time = live_ingest.store_session_transcript(
        session, _INIT + _assistant_line(5) + _assistant_line(7)
    )
    assert write_time["totals"]["output_tokens"] == 12

    session.cost_breakdown = {}
    session.save(update_fields=["cost_breakdown"])

    through_the_seam = live_ingest.recompute_cost_from_source(session)

    # `computed_at` is a wall clock and is expected to move; everything that is
    # actually the cost must not.
    assert through_the_seam.keys() == write_time.keys()
    assert {k: v for k, v in through_the_seam.items() if k != "computed_at"} == {
        k: v for k, v in write_time.items() if k != "computed_at"
    }
    assert through_the_seam["totals"] == write_time["totals"]
    assert through_the_seam["phases"] == write_time["phases"]
    session.refresh_from_db()
    assert session.cost_breakdown == through_the_seam


# ---------------------------------------------------------------------------
# The hybrid session's cost, and the refusal to under-report
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_hybrid_sessions_cost_covers_its_local_turns_as_well_as_canopys():
    """A run that executed locally and was later dispatched to canopy: its cost
    must be the sum of both halves. Reading only canopy's half is exactly the
    silent drop this whole PR exists to prevent."""
    import gzip
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.sessions.models import IngestUpload, Message

    _user, session = _canopy_session()
    local_bytes = (_INIT + _assistant_line(5)).encode()
    IngestUpload.objects.create(
        session=session, uploaded_by=session.owner, source="local",
        raw_jsonl_gz=gzip.compress(local_bytes),
    )
    Message.objects.create(
        session=session, turn_index=9, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    canopy_bytes = _assistant_line(7).encode()
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=canopy_bytes):
        breakdown = live_ingest.recompute_cost_from_source(session)
    assert breakdown["totals"]["output_tokens"] == 12   # 5 local + 7 canopy


@pytest.mark.django_db
def test_a_multi_turn_canopy_session_sums_its_turns_tokens():
    """Bytes concatenating is not the same claim as cost adding up."""
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.sessions.models import Message

    _user, session = _canopy_session()
    for idx, turn in ((1, "turn-a"), (3, "turn-b")):
        Message.objects.create(
            session=session, turn_index=idx, role="assistant", content={"text": ""},
            status="complete", canopy_turn_id=turn,
        )
    blobs = {"turn-a": _assistant_line(5).encode(), "turn-b": _assistant_line(7).encode()}
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=lambda tok, tid, **kw: blobs[tid],
         ):
        breakdown = live_ingest.recompute_cost_from_source(session)
    assert breakdown["totals"]["output_tokens"] == 12   # 5 + 7
    assert breakdown["totals"]["input_tokens"] == 20    # 10 + 10


@pytest.mark.django_db
def test_recompute_refuses_to_lower_a_runs_cost():
    """A session's cost only accumulates, so a smaller recomputed figure means
    we read FEWER bytes than last time — a truncation, a lost prefix, a partial
    cache. Keep the larger number: a stuck cost is visible in the logs, a
    silently shrunken one is visible nowhere."""
    from unittest import mock

    from apps.ingest import live_ingest

    _user, session = _canopy_session()
    big = (_INIT + _assistant_line(5) + _assistant_line(7)).encode()
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=big):
        full = live_ingest.recompute_cost_from_source(session)
    assert full["totals"]["output_tokens"] == 12

    small = (_INIT + _assistant_line(5)).encode()
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=small):
        kept = live_ingest.recompute_cost_from_source(session)
    assert kept["totals"]["output_tokens"] == 12   # NOT 5
    session.refresh_from_db()
    # Bound to a local first: django-stubs types the attribute as JSONField,
    # which basedpyright refuses to subscript (see test_stores_breakdown…).
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 12


@pytest.mark.django_db
def test_recompute_still_raises_a_runs_cost_as_it_grows():
    """The refusal must not freeze a run: a growing transcript still writes."""
    from unittest import mock

    from apps.ingest import live_ingest

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.session_raw_jsonl", return_value=(_INIT + _assistant_line(5)).encode()
    ):
        live_ingest.recompute_cost_from_source(session)
    with mock.patch(
        "apps.ingest.sources.session_raw_jsonl",
        return_value=(_INIT + _assistant_line(5) + _assistant_line(7)).encode(),
    ):
        grown = live_ingest.recompute_cost_from_source(session)
    assert grown["totals"]["output_tokens"] == 12
    session.refresh_from_db()
    # Bound to a local first: django-stubs types the attribute as JSONField,
    # which basedpyright refuses to subscript (see test_stores_breakdown…).
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 12


@pytest.mark.django_db
def test_a_local_turn_after_a_canopy_turn_does_not_fold_canopys_bytes_into_the_local_row():
    """`store_session_transcript` accumulates onto the newest row. With a canopy
    row present that would copy canopy's bytes into the local source of record
    and double them on the next compose."""
    import gzip

    from apps.ingest import live_ingest
    from apps.sessions.models import IngestUpload

    _user, session = _canopy_session()
    IngestUpload.objects.create(
        session=session, uploaded_by=session.owner, source="canopy",
        canopy_turn_ids=["turn-a"],
        raw_jsonl_gz=gzip.compress((_INIT + _assistant_line(7)).encode()),
    )
    live_ingest.store_session_transcript(session, _INIT + _assistant_line(5))

    local = IngestUpload.objects.get(session=session, source="local")
    assert local.read_raw_jsonl() == _INIT + _assistant_line(5)
    canopy = IngestUpload.objects.get(session=session, source="canopy")
    assert canopy.read_raw_jsonl() == _INIT + _assistant_line(7)   # untouched
