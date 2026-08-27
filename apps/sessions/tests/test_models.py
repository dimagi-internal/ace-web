from unittest.mock import patch

import pytest
from django.db import IntegrityError

from apps.auth.models import User
from apps.sessions.models import (
    IngestUpload,
    Message,
    Session,
    SessionParticipant,
)


@pytest.fixture
def user(db):
    return User.objects.create_user(email="test@example.com")


@pytest.fixture
def session(user):
    return Session.objects.create(owner=user, title="Test session")


def test_session_slug_is_auto_generated(session):
    assert session.slug
    assert len(session.slug) >= 6


def test_session_default_backend_kind(session):
    assert session.backend_kind == "cli"


def test_session_participant_uniqueness(session, user):
    SessionParticipant.objects.create(session=session, user=user, role="owner")
    with pytest.raises(IntegrityError):
        SessionParticipant.objects.create(session=session, user=user, role="editor")


def test_message_turn_index_is_unique_per_session(session, user):
    Message.objects.create(
        session=session,
        turn_index=0,
        role="user",
        sender_user=user,
        content=[{"type": "text", "text": "hi"}],
        status="complete",
    )
    with pytest.raises(IntegrityError):
        Message.objects.create(
            session=session,
            turn_index=0,
            role="assistant",
            content=[{"type": "text", "text": "hello"}],
            status="complete",
        )


def test_message_turn_index_can_repeat_across_sessions(user):
    s1 = Session.objects.create(owner=user, title="A")
    s2 = Session.objects.create(owner=user, title="B")
    Message.objects.create(
        session=s1,
        turn_index=0,
        role="user",
        sender_user=user,
        content=[{"type": "text", "text": "hi"}],
        status="complete",
    )
    # Should not raise
    Message.objects.create(
        session=s2,
        turn_index=0,
        role="user",
        sender_user=user,
        content=[{"type": "text", "text": "hi"}],
        status="complete",
    )


def test_ingest_upload_creates_audit_row(session, user):
    record = IngestUpload.objects.create(
        session=session,
        uploaded_by=user,
        source_path="/tmp/test-upload.jsonl",
        raw_bytes=12345,
        line_count=42,
        cli_session_id="abc-123",
    )
    assert record.line_count == 42


def test_session_save_retries_on_slug_collision(user):
    """Session.save() should catch an IntegrityError from a duplicate slug
    and retry with a freshly generated one. 48 bits of entropy make a real
    collision essentially impossible, so we simulate one by constructing a
    Session with a slug that already exists in the DB.

    Note: we do NOT rely on patching the `slug` field default, because that
    default is captured as a direct function reference at class-definition
    time and isn't affected by ``patch("apps.sessions.models.generate_slug")``.
    Instead we pre-fill the colliding slug on the instance and verify that
    the retry branch in ``save()`` (which calls ``generate_slug()`` by name
    at runtime) picks up the patched version.
    """
    existing = Session.objects.create(owner=user, title="existing")
    taken_slug = existing.slug

    colliding = Session(owner=user, title="colliding", slug=taken_slug)

    with patch("apps.sessions.models.generate_slug", return_value="fresh1234"):
        colliding.save()

    assert colliding.slug == "fresh1234"
    assert Session.objects.filter(slug=taken_slug).count() == 1  # existing untouched
    assert Session.objects.filter(slug="fresh1234").count() == 1  # retried row landed


def test_session_carries_canopy_session_id(django_user_model):
    user = django_user_model.objects.create_user(email="owner@example.com")
    s = Session.create_with_owner(owner=user, title="t", opp_slug="o", opp_run_id="r")
    assert s.canopy_session_id == ""          # default: not yet dispatched
    s.canopy_session_id = "9f1c0e2a-0000-4000-8000-000000000001"
    s.save(update_fields=["canopy_session_id"])
    s.refresh_from_db()
    assert s.canopy_session_id == "9f1c0e2a-0000-4000-8000-000000000001"


def test_message_carries_canopy_turn_id(django_user_model):
    user = django_user_model.objects.create_user(email="owner2@example.com")
    s = Session.create_with_owner(owner=user, title="t")
    m = Message.objects.create(
        session=s, turn_index=0, role="assistant", content={"text": ""}, status="pending",
    )
    assert m.canopy_turn_id == ""
    m.canopy_turn_id = "9f1c0e2a-0000-4000-8000-000000000002"
    m.save(update_fields=["canopy_turn_id"])
    assert Message.objects.filter(canopy_turn_id=m.canopy_turn_id).count() == 1
