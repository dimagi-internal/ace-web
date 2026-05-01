"""Tests for the auto-titling background task."""
from unittest.mock import AsyncMock, patch

import pytest

from apps.common.chat_backend import StreamEvent
from apps.sessions.auto_title import generate_title_for_session
from apps.sessions.models import Message, Session

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )
    s = Session.objects.create(owner=user, title="")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "explain quicksort to me"},
        plaintext="explain quicksort to me", status="complete",
    )
    return s


class FakeBackend:
    def __init__(self, title_text):
        self._text = title_text

    async def stream_completion(self, *, session, new_user_message, force_fresh_session=False):
        for chunk in self._text.split():
            yield StreamEvent.delta(text=chunk + " ")
        yield StreamEvent.done()


async def test_generates_and_persists_title(session):
    fake = FakeBackend("Quicksort algorithm explained simply for beginners")
    with patch("apps.sessions.auto_title._get_backend", return_value=fake):
        await generate_title_for_session(session)

    from asgiref.sync import sync_to_async
    await sync_to_async(session.refresh_from_db)()
    assert session.title == "Quicksort algorithm explained simply for beginners"


async def test_does_nothing_if_title_already_set(session):
    from asgiref.sync import sync_to_async
    session.title = "manually set"
    await sync_to_async(session.save)()
    fake = FakeBackend("would be auto generated")
    with patch("apps.sessions.auto_title._get_backend", return_value=fake):
        await generate_title_for_session(session)

    await sync_to_async(session.refresh_from_db)()
    assert session.title == "manually set"


async def test_failure_leaves_title_blank(session):
    from apps.common.cli_backend import CLIBackendError

    class FailingBackend:
        async def stream_completion(self, *, session, new_user_message, force_fresh_session=False):
            raise CLIBackendError("boom")
            yield  # unreachable; makes this an async generator

    with patch("apps.sessions.auto_title._get_backend", return_value=FailingBackend()):
        await generate_title_for_session(session)  # should not raise

    from asgiref.sync import sync_to_async
    await sync_to_async(session.refresh_from_db)()
    assert session.title == ""


async def test_broadcasts_title_to_session_group(session):
    """After persisting the title, push it to every open chat tab.

    Without this broadcast the chat header and the recent-sessions
    sidebar stay 'Untitled' until the user reloads — even though the DB
    row already has the right title and `/sessions` lists it correctly.
    """
    fake = FakeBackend("Quicksort explained simply")
    fake_layer = AsyncMock()
    with patch("apps.sessions.auto_title._get_backend", return_value=fake), \
         patch(
             "apps.sessions.auto_title.get_channel_layer",
             return_value=fake_layer,
         ):
        await generate_title_for_session(session)

    fake_layer.group_send.assert_awaited_once()
    group, payload = fake_layer.group_send.await_args.args
    assert group == f"session.{session.slug}"
    assert payload["type"] == "session.title_updated"
    assert payload["title"] == "Quicksort explained simply"


async def test_no_broadcast_when_title_already_set(session):
    """Idempotent path skips both DB write AND broadcast — important so a
    second turn doesn't re-fire the title-updated event with the same
    value (UI flicker, sidebar churn)."""
    from asgiref.sync import sync_to_async
    session.title = "manually set"
    await sync_to_async(session.save)()
    fake = FakeBackend("would be auto generated")
    fake_layer = AsyncMock()
    with patch("apps.sessions.auto_title._get_backend", return_value=fake), \
         patch(
             "apps.sessions.auto_title.get_channel_layer",
             return_value=fake_layer,
         ):
        await generate_title_for_session(session)

    fake_layer.group_send.assert_not_awaited()


async def test_no_broadcast_when_backend_fails(session):
    """If the backend errors before producing a title, don't broadcast a
    blank string — that would clobber the sidebar with 'Untitled'."""
    from apps.common.cli_backend import CLIBackendError

    class FailingBackend:
        async def stream_completion(self, *, session, new_user_message, force_fresh_session=False):
            raise CLIBackendError("boom")
            yield  # unreachable; makes this an async generator

    fake_layer = AsyncMock()
    with patch(
        "apps.sessions.auto_title._get_backend", return_value=FailingBackend()
    ), patch(
        "apps.sessions.auto_title.get_channel_layer", return_value=fake_layer
    ):
        await generate_title_for_session(session)

    fake_layer.group_send.assert_not_awaited()
