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
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(_CANOPY_TURN, ""),
    ):
        breakdown = live_ingest.recompute_cost_from_source(session)

    session.refresh_from_db()
    assert session.cost_breakdown == breakdown
    assert breakdown["totals"]["input_tokens"] == 10
    assert breakdown["totals"]["output_tokens"] == 5


@pytest.mark.django_db
def test_recompute_cost_is_a_noop_when_there_is_no_transcript():
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(None, "no-raw-jsonl"),
    ):
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
    from apps.ingest.sources import TranscriptRead
    from apps.sessions.models import IngestUpload

    user, session = _canopy_session()
    row = IngestUpload.objects.create(
        session=session, uploaded_by=user, source="canopy",
        canopy_turn_ids=["turn-a"], raw_jsonl_gz=b"sentinel-bytes",
    )
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(_CANOPY_TURN, ""),
    ):
        live_ingest.recompute_cost_from_source(session)
    row.refresh_from_db()
    assert bytes(row.raw_jsonl_gz) == b"sentinel-bytes"


@pytest.mark.django_db
def test_recompute_cost_survives_an_aggregator_failure():
    """Analytics must never break a run — the same contract
    store_session_transcript has held since it was written."""
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(_CANOPY_TURN, ""),
    ), mock.patch("apps.ingest.cost_aggregator.aggregate", side_effect=RuntimeError("boom")):
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
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    big = (_INIT + _assistant_line(5) + _assistant_line(7)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript", return_value=TranscriptRead(big, "")
    ):
        full = live_ingest.recompute_cost_from_source(session)
    assert full["totals"]["output_tokens"] == 12

    small = (_INIT + _assistant_line(5)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript", return_value=TranscriptRead(small, "")
    ):
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
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead((_INIT + _assistant_line(5)).encode(), ""),
    ):
        live_ingest.recompute_cost_from_source(session)
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead((_INIT + _assistant_line(5) + _assistant_line(7)).encode(), ""),
    ):
        grown = live_ingest.recompute_cost_from_source(session)
    assert grown["totals"]["output_tokens"] == 12
    session.refresh_from_db()
    # Bound to a local first: django-stubs types the attribute as JSONField,
    # which basedpyright refuses to subscript (see test_stores_breakdown…).
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 12


@pytest.mark.django_db
def test_a_local_turn_after_a_canopy_turn_neither_folds_bytes_nor_lowers_cost():
    """The mirror of the hybrid bug: a flag ROLLBACK plus the deploy's
    resume-interrupted hook runs a local turn on a session that already has a
    composed canopy transcript.

    Two distinct damages, and the earlier version of this test asserted only the
    first — so it stayed green while `store_session_transcript` wrote its
    LOCAL-ONLY cost over the composed one (measured: 105 -> 6). Bytes were the
    symptom; `cost_breakdown` is the damage.
    """
    import gzip
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.sessions.models import IngestUpload, Message

    _user, session = _canopy_session()
    canopy_bytes = (_INIT + _assistant_line(7)).encode()
    IngestUpload.objects.create(
        session=session, uploaded_by=session.owner, source="canopy",
        canopy_turn_ids=["turn-a"], raw_jsonl_gz=gzip.compress(canopy_bytes),
    )
    Message.objects.create(
        session=session, turn_index=1, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript", return_value=canopy_bytes
         ):
        composed = live_ingest.recompute_cost_from_source(session)
    assert composed["totals"]["output_tokens"] == 7

    # …now a local turn lands on the same session.
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript", return_value=canopy_bytes
         ):
        after = live_ingest.store_session_transcript(session, _INIT + _assistant_line(5))

    # 1. The bytes (the symptom): each row keeps its own half.
    local = IngestUpload.objects.get(session=session, source="local")
    assert local.read_raw_jsonl() == _INIT + _assistant_line(5)
    canopy = IngestUpload.objects.get(session=session, source="canopy")
    assert canopy.read_raw_jsonl().startswith(_INIT + _assistant_line(5))   # recomposed

    # 2. The cost (the damage): it covers BOTH halves and never drops.
    assert after["totals"]["output_tokens"] == 12   # 5 local + 7 canopy, not 5
    session.refresh_from_db()
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 12


@pytest.mark.django_db
def test_cost_is_not_derived_from_an_incomplete_transcript():
    """An incomplete read is SHORT, not smaller — it parses and aggregates
    cleanly to a number that is simply too low, which the refuse-smaller
    ratchet cannot see. It must never be persisted at all."""
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead((_INIT + _assistant_line(5)).encode(), ""),
    ):
        live_ingest.recompute_cost_from_source(session)

    # DELIBERATELY LARGER than the stored figure, so the refuse-smaller ratchet
    # cannot be what stops it — only the completeness flag can. A known-partial
    # read must not publish a number at all, in either direction.
    bigger_but_partial = (_INIT + _assistant_line(5) + _assistant_line(7)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(bigger_but_partial, "", complete=False),
    ):
        kept = live_ingest.recompute_cost_from_source(session)
    assert kept["totals"]["output_tokens"] == 5
    session.refresh_from_db()
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 5


@pytest.mark.django_db
def test_an_incomplete_transcript_does_not_seed_a_cost_on_a_fresh_session():
    """The ratchet only protects a session that already HAS a figure. A brand
    new run's first read must not seed a short one, which every later read
    would then be measured against."""
    from unittest import mock

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    short = (_INIT + _assistant_line(5)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead(short, "", complete=False),
    ):
        assert live_ingest.recompute_cost_from_source(session) == {}
    session.refresh_from_db()
    assert session.cost_breakdown == {}


@pytest.mark.django_db
def test_the_terminal_reconcile_forces_a_transcript_refresh():
    """canopy permits a post-terminal append, so the cached compose may predate
    the run's final lines. The one moment we know the turn is over is the one
    moment worth paying a refetch for."""
    from unittest import mock

    from apps.canopy import run_state
    from apps.sessions.models import Message

    _user, session = _canopy_session()
    Message.objects.create(
        session=session, turn_index=1, role="assistant", content={"text": ""},
        status="pending", canopy_turn_id="turn-1",
    )
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.client.get_turn", return_value={"status": "done"}), \
         mock.patch("apps.canopy.client.list_unclaimable", return_value=[]), \
         mock.patch("apps.ingest.live_ingest.recompute_cost_from_source") as recompute:
        run_state.reconcile_session(session)
    assert recompute.call_args.kwargs.get("force_refresh") is True


# ---------------------------------------------------------------------------
# manage.py recompute_session_cost — the ratchet's only way back down
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_recompute_command_can_lower_a_cost_and_says_so():
    """Refuse-smaller is one-way, so any over-count would otherwise be
    permanent. The reset is explicit, and it prints before -> after."""
    from io import StringIO
    from unittest import mock

    from django.core.management import call_command

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    big = (_INIT + _assistant_line(5) + _assistant_line(7)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript", return_value=TranscriptRead(big, "")
    ):
        live_ingest.recompute_cost_from_source(session)

    small = (_INIT + _assistant_line(5)).encode()
    out = StringIO()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript", return_value=TranscriptRead(small, "")
    ):
        call_command("recompute_session_cost", slug=session.slug, force=True, stdout=out)
    session.refresh_from_db()
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 5
    assert "->" in out.getvalue()     # the change is printed, never silent


@pytest.mark.django_db
def test_the_recompute_command_respects_the_ratchet_without_force():
    from io import StringIO
    from unittest import mock

    from django.core.management import call_command

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    big = (_INIT + _assistant_line(5) + _assistant_line(7)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript", return_value=TranscriptRead(big, "")
    ):
        live_ingest.recompute_cost_from_source(session)

    small = (_INIT + _assistant_line(5)).encode()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript", return_value=TranscriptRead(small, "")
    ):
        call_command("recompute_session_cost", slug=session.slug, stdout=StringIO())
    session.refresh_from_db()
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 12


@pytest.mark.django_db
def test_the_recompute_command_refuses_a_bare_invocation():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("recompute_session_cost")


@pytest.mark.django_db
def test_force_does_not_let_an_incomplete_transcript_through():
    """`--force` exists to undo an OVER-count. It is not a licence to publish a
    figure we already know is derived from a partial read."""
    from io import StringIO
    from unittest import mock

    from django.core.management import call_command

    from apps.ingest import live_ingest
    from apps.ingest.sources import TranscriptRead

    _user, session = _canopy_session()
    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead((_INIT + _assistant_line(5) + _assistant_line(7)).encode(), ""),
    ):
        live_ingest.recompute_cost_from_source(session)

    with mock.patch(
        "apps.ingest.sources.read_session_transcript",
        return_value=TranscriptRead((_INIT + _assistant_line(5)).encode(), "", complete=False),
    ):
        call_command("recompute_session_cost", slug=session.slug, force=True, stdout=StringIO())
    session.refresh_from_db()
    stored: dict = session.cost_breakdown
    assert stored["totals"]["output_tokens"] == 12
