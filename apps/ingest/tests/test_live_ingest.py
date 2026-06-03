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
    assert session.cost_breakdown["totals"]["output_tokens"] == 5

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
