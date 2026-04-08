"""Tests for the auto-titling background task."""
from unittest.mock import patch

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
