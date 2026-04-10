"""Unit tests for the draft state machine. Each helper is a sync DB
operation — no WebSocket, no Redis."""
from datetime import timedelta

import pytest

from apps.sessions import drafts
from apps.sessions.models import Draft, Message, Session, SessionParticipant

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def session(alice, bob):
    s = Session.objects.create(owner=alice, title="x")
    SessionParticipant.objects.create(session=s, user=alice, role="owner")
    SessionParticipant.objects.create(session=s, user=bob, role="editor")
    return s


def test_get_or_create_active_draft_creates_empty(session, alice):
    draft = drafts.get_or_create_active_draft(session, alice)
    assert draft.slot == "next"
    assert draft.status == "open"
    assert draft.body == ""
    assert draft.version == 0
    assert draft.last_editor_id == alice.id


def test_get_or_create_active_draft_returns_existing(session, alice):
    first = drafts.get_or_create_active_draft(session, alice)
    second = drafts.get_or_create_active_draft(session, alice)
    assert first.pk == second.pk


def test_update_body_bumps_version_and_last_editor(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    updated = drafts.update_body(
        draft_id=draft.pk, user=bob, expected_version=0, new_body="hello"
    )
    assert updated.version == 1
    assert updated.body == "hello"
    assert updated.last_editor_id == bob.id


def test_update_body_raises_on_stale_version(session, alice):
    draft = drafts.get_or_create_active_draft(session, alice)
    drafts.update_body(
        draft_id=draft.pk, user=alice, expected_version=0, new_body="hi"
    )
    with pytest.raises(drafts.DraftVersionMismatch) as exc_info:
        drafts.update_body(
            draft_id=draft.pk,
            user=alice,
            expected_version=0,
            new_body="wrong",
        )
    assert exc_info.value.current_version == 1
    assert exc_info.value.current_body == "hi"


def test_claim_lock_succeeds_when_idle(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    # Backdate updated_at to simulate 10s idle.
    Draft.objects.filter(pk=draft.pk).update(
        updated_at=_ten_seconds_ago()
    )
    result = drafts.claim_lock(
        draft_id=draft.pk, user=bob, holder_is_present=True
    )
    assert result.last_editor_id == bob.id


def test_claim_lock_succeeds_when_holder_absent(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    # Draft was just updated but holder has disconnected.
    result = drafts.claim_lock(
        draft_id=draft.pk, user=bob, holder_is_present=False
    )
    assert result.last_editor_id == bob.id


def test_claim_lock_fails_when_holder_active(session, alice, bob):
    draft = drafts.get_or_create_active_draft(session, alice)
    with pytest.raises(drafts.DraftLockHeld) as exc_info:
        drafts.claim_lock(
            draft_id=draft.pk, user=bob, holder_is_present=True
        )
    assert exc_info.value.holder_user_id == alice.id


def test_commit_creates_user_message_assistant_placeholder_and_new_draft(
    session, alice
):
    draft = drafts.get_or_create_active_draft(session, alice)
    drafts.update_body(
        draft_id=draft.pk, user=alice, expected_version=0, new_body="hello"
    )
    result = drafts.commit_active_draft(session=session, user=alice)

    user_msg = Message.objects.get(pk=result.user_message_id)
    asst_msg = Message.objects.get(pk=result.assistant_message_id)
    assert user_msg.role == "user"
    assert user_msg.plaintext == "hello"
    assert user_msg.status == "complete"
    assert asst_msg.role == "assistant"
    assert asst_msg.status == "pending"
    assert asst_msg.turn_index == user_msg.turn_index + 1

    old = Draft.objects.get(pk=draft.pk)
    assert old.status == "sent"
    assert old.sent_message_id == asst_msg.id

    new_draft = Draft.objects.get(pk=result.new_draft_id)
    assert new_draft.status == "open"
    assert new_draft.slot == "next"
    assert new_draft.body == ""
    assert new_draft.version == 0


def test_commit_is_noop_when_body_is_empty(session, alice):
    drafts.get_or_create_active_draft(session, alice)
    result = drafts.commit_active_draft(session=session, user=alice)
    assert result is None
    assert Message.objects.filter(session=session).count() == 0


def test_discard_resets_body_and_bumps_version(session, alice):
    draft = drafts.get_or_create_active_draft(session, alice)
    drafts.update_body(
        draft_id=draft.pk, user=alice, expected_version=0, new_body="oops"
    )
    cleared = drafts.discard(draft_id=draft.pk, user=alice)
    assert cleared.body == ""
    assert cleared.version == 2  # +1 for update, +1 for discard
    assert cleared.status == "open"


def _ten_seconds_ago():
    from django.utils import timezone as tz
    return tz.now() - timedelta(seconds=10)
