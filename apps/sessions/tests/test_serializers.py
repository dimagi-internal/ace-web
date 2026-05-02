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


def test_preview_is_first_user_message_plaintext(session):
    Message.objects.create(
        session=session, turn_index=0, role="user",
        content={"text": "What is the capital of France?"},
        plaintext="What is the capital of France?", status="complete",
    )
    Message.objects.create(
        session=session, turn_index=1, role="assistant",
        content={"text": "Paris."}, plaintext="Paris.", status="complete",
    )
    data = SessionSerializer(session).data
    assert data["preview"] == "What is the capital of France?"


def test_session_serializer_exposes_opp_pointers(session):
    """Opp linkage fields must round-trip on the wire so the chat UI can
    render the opp breadcrumb, group the recent-sessions sidebar by opp,
    and drive the ?opp= filter on /sessions. They default to "" when the
    session is not opp-linked."""
    data = SessionSerializer(session).data
    assert data["opp_slug"] == ""
    assert data["opp_run_id"] == ""
    assert data["opp_step_skill"] == ""

    session.opp_slug = "malaria-pilot"
    session.opp_run_id = "2026-04-06-002"
    session.opp_step_skill = "app-deploy"
    session.save(update_fields=["opp_slug", "opp_run_id", "opp_step_skill"])

    data = SessionSerializer(session).data
    assert data["opp_slug"] == "malaria-pilot"
    assert data["opp_run_id"] == "2026-04-06-002"
    assert data["opp_step_skill"] == "app-deploy"


def test_preview_is_empty_when_no_user_messages(session):
    Message.objects.create(
        session=session, turn_index=0, role="assistant",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    assert SessionSerializer(session).data["preview"] == ""


def test_preview_truncates_long_plaintext(session):
    long_text = "alpha " * 80  # > 120 chars
    Message.objects.create(
        session=session, turn_index=0, role="user",
        content={"text": long_text}, plaintext=long_text, status="complete",
    )
    preview = SessionSerializer(session).data["preview"]
    assert len(preview) <= 120
    assert preview.endswith("…")


def test_preview_collapses_internal_whitespace(session):
    Message.objects.create(
        session=session, turn_index=0, role="user",
        content={"text": "line one\n\nline two"},
        plaintext="line one\n\nline two", status="complete",
    )
    assert SessionSerializer(session).data["preview"] == "line one line two"


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
