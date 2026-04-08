import pytest

from apps.sessions.models import Message, Session
from apps.sessions.serializers import MessageSerializer, SessionSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )
    return Session.objects.create(owner=user, title="my chat")


def test_session_serializer_basic(session):
    data = SessionSerializer(session).data
    assert data["slug"] == session.slug
    assert data["title"] == "my chat"
    assert data["status"] == "active"
    assert data["backend_kind"] == "cli"
    assert "created_at" in data
    assert "message_count" in data
    assert data["message_count"] == 0


def test_session_serializer_includes_message_count(session):
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    data = SessionSerializer(session).data
    assert data["message_count"] == 1


def test_message_serializer_basic(session):
    msg = Message.objects.create(
        session=session, turn_index=1, role="assistant",
        content={"text": "hello"}, plaintext="hello", status="complete",
    )
    data = MessageSerializer(msg).data
    assert data["turn_index"] == 1
    assert data["role"] == "assistant"
    assert data["plaintext"] == "hello"
    assert data["status"] == "complete"
