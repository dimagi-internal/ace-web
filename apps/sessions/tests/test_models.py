from unittest.mock import patch

import pytest
from django.db import IntegrityError

from apps.auth.models import User
from apps.sessions.models import (
    Draft,
    IngestUpload,
    Message,
    Session,
    SessionParticipant,
    ShareToken,
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


def test_only_one_open_next_draft_per_session(session, user):
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="next",
        status="open",
        body="first",
    )
    with pytest.raises(IntegrityError):
        Draft.objects.create(
            session=session,
            creator_user=user,
            last_editor=user,
            slot="next",
            status="open",
            body="second",
        )


def test_can_have_multiple_queued_drafts(session, user):
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="queued",
        queue_position=0,
        body="A",
    )
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="queued",
        queue_position=1,
        body="B",
    )
    assert Draft.objects.filter(session=session, slot="queued").count() == 2


def test_sent_draft_does_not_block_new_next(session, user):
    """A draft with status='sent' should not block creating a new open 'next' draft."""
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="next",
        status="sent",
        body="old",
    )
    # Should not raise — the partial unique index is on status='open'
    Draft.objects.create(
        session=session,
        creator_user=user,
        last_editor=user,
        slot="next",
        status="open",
        body="new",
    )


def test_share_token_is_auto_generated(session, user):
    token = ShareToken.objects.create(session=session, created_by=user)
    assert token.token
    assert len(token.token) >= 24


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


def test_open_next_draft_constraint_is_per_session(user):
    """The one_next_per_session partial unique constraint applies per session,
    not globally — different sessions can each have an open next draft."""
    s1 = Session.objects.create(owner=user, title="A")
    s2 = Session.objects.create(owner=user, title="B")
    Draft.objects.create(
        session=s1, creator_user=user, last_editor=user,
        slot="next", status="open", body="A-next",
    )
    Draft.objects.create(
        session=s2, creator_user=user, last_editor=user,
        slot="next", status="open", body="B-next",
    )
    assert Draft.objects.filter(slot="next", status="open").count() == 2


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
