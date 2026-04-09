"""Draft state machine for Phase 3 multi-player collaboration.

All operations are synchronous Django ORM. The WebSocket consumer wraps
them in `sync_to_async` calls. Keeping this module sync-only simplifies
testing (no pytest-asyncio gymnastics) and lets us reuse Django's
transaction + select_for_update primitives directly.

The soft lock is derived, not stored — there is no separate lock table.
The "holder" is Draft.last_editor; the lock is idle when
    now() - Draft.updated_at > LOCK_IDLE_SECONDS
OR the holder is not present in the session (checked by the caller via
apps.sessions.presence.is_present, passed in as `holder_is_present`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Draft, Message, Session

LOCK_IDLE_SECONDS = 2


class DraftVersionMismatch(Exception):
    """Raised when an update carries a stale version."""

    def __init__(self, current_version: int, current_body: str) -> None:
        self.current_version = current_version
        self.current_body = current_body
        super().__init__(f"stale version; current is {current_version}")


class DraftLockHeld(Exception):
    """Raised when take_over is attempted against a live lock."""

    def __init__(self, holder_user_id: int, expires_at: float) -> None:
        self.holder_user_id = holder_user_id
        self.expires_at = expires_at
        super().__init__(f"lock held by user {holder_user_id} until {expires_at}")


@dataclass
class CommitResult:
    user_message_id: int
    assistant_message_id: int
    old_draft_id: int
    new_draft_id: int


def get_or_create_active_draft(session: Session, user) -> Draft:
    """Return the open slot='next' draft for this session, creating one
    if none exists. `user` is used as creator/last_editor on creation.

    Serializes concurrent callers via a row-lock on the session row so
    two simultaneous connects cannot both try to create a draft and
    violate the one_next_per_session partial unique constraint.
    """
    with transaction.atomic():
        locked_session = Session.objects.select_for_update().get(pk=session.pk)
        draft = Draft.objects.filter(
            session=locked_session, slot="next", status="open"
        ).first()
        if draft is not None:
            return draft
        return Draft.objects.create(
            session=locked_session,
            slot="next",
            status="open",
            body="",
            version=0,
            creator_user=user,
            last_editor=user,
        )


def update_body(*, draft_id: int, user, expected_version: int, new_body: str) -> Draft:
    """Apply an update from a user's client. Version-guarded.

    Raises DraftVersionMismatch if expected_version does not match the
    current row version.
    """
    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft_id)
        if draft.version != expected_version:
            raise DraftVersionMismatch(
                current_version=draft.version, current_body=draft.body
            )
        draft.body = new_body
        draft.version += 1
        draft.last_editor = user
        draft.save(update_fields=["body", "version", "last_editor", "updated_at"])
        return draft


def claim_lock(*, draft_id: int, user, holder_is_present: bool) -> Draft:
    """Transfer the soft lock to `user`. Allowed if the lock is idle or
    the current holder is not in the presence set.

    Raises DraftLockHeld otherwise.
    """
    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft_id)
        idle_cutoff = timezone.now() - timedelta(seconds=LOCK_IDLE_SECONDS)
        is_idle = draft.updated_at < idle_cutoff
        if not is_idle and holder_is_present:
            expires_at = (
                draft.updated_at + timedelta(seconds=LOCK_IDLE_SECONDS)
            ).timestamp()
            raise DraftLockHeld(
                holder_user_id=draft.last_editor_id,
                expires_at=expires_at,
            )
        draft.last_editor = user
        draft.save(update_fields=["last_editor", "updated_at"])
        return draft


def discard(*, draft_id: int, user) -> Draft:
    """Clear the body. Keeps slot='next', status='open', bumps version."""
    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft_id)
        draft.body = ""
        draft.version += 1
        draft.last_editor = user
        draft.save(update_fields=["body", "version", "last_editor", "updated_at"])
        return draft


def commit_active_draft(*, session: Session, user) -> CommitResult | None:
    """Commit the active draft as a user Message, create the assistant
    placeholder, open a fresh next-draft. Idempotent guard: returns None
    if no open draft exists OR the draft body is empty.
    """
    with transaction.atomic():
        locked_session = Session.objects.select_for_update().get(pk=session.pk)
        draft = (
            Draft.objects.select_for_update()
            .filter(session=locked_session, slot="next", status="open")
            .first()
        )
        if draft is None or not draft.body.strip():
            return None

        body = draft.body

        last_turn = (
            Message.objects.filter(session=locked_session)
            .order_by("-turn_index")
            .values_list("turn_index", flat=True)
            .first()
        )
        next_turn = (last_turn or 0) + 1

        user_msg = Message.objects.create(
            session=locked_session,
            turn_index=next_turn,
            role="user",
            sender_user=user,
            content={"text": body},
            plaintext=body,
            status="complete",
            completed_at=timezone.now(),
        )
        assistant_msg = Message.objects.create(
            session=locked_session,
            turn_index=next_turn + 1,
            role="assistant",
            content={"text": ""},
            plaintext="",
            status="pending",
        )

        draft.status = "sent"
        draft.sent_message = assistant_msg
        draft.sent_at = timezone.now()
        draft.save(update_fields=["status", "sent_message", "sent_at", "updated_at"])

        new_draft = Draft.objects.create(
            session=locked_session,
            slot="next",
            status="open",
            body="",
            version=0,
            creator_user=user,
            last_editor=user,
        )

        return CommitResult(
            user_message_id=user_msg.id,
            assistant_message_id=assistant_msg.id,
            old_draft_id=draft.id,
            new_draft_id=new_draft.id,
        )
