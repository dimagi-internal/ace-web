import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Message, Session, SessionParticipant, ShareToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def session_with_messages(user):
    s = Session.objects.create(owner=user, title="Test session")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"type": "text", "text": "Hello"}, plaintext="Hello",
        status="complete",
    )
    Message.objects.create(
        session=s, turn_index=2, role="assistant",
        content={"type": "text", "text": "Hi there"},
        plaintext="Hi there", status="complete",
    )
    return s


# --- create share token ---

def test_create_share_token(client, session_with_messages):
    resp = client.post(f"/api/sessions/{session_with_messages.slug}/share")
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert "token" in body["data"]
    assert "url" in body["data"]
    assert ShareToken.objects.filter(session=session_with_messages).count() == 1


def test_create_share_token_non_participant_404(client, other_user):
    s = Session.objects.create(owner=other_user, title="not mine")
    resp = client.post(f"/api/sessions/{s.slug}/share")
    assert resp.status_code == 404


def test_create_share_token_viewer_forbidden(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="theirs")
    SessionParticipant.objects.create(session=s, user=other_user, role="owner")
    SessionParticipant.objects.create(session=s, user=user, role="viewer")
    resp = client.post(f"/api/sessions/{s.slug}/share")
    assert resp.status_code == 403


# --- list share tokens ---

def test_list_share_tokens(client, session_with_messages):
    ShareToken.objects.create(
        session=session_with_messages, created_by=session_with_messages.owner,
    )
    resp = client.get(f"/api/sessions/{session_with_messages.slug}/share")
    assert resp.status_code == 200
    tokens = resp.json()["data"]
    assert len(tokens) == 1
    assert tokens[0]["revoked_at"] is None


def test_list_share_tokens_excludes_revoked(client, session_with_messages):
    from django.utils import timezone

    ShareToken.objects.create(
        session=session_with_messages,
        created_by=session_with_messages.owner,
        revoked_at=timezone.now(),
    )
    ShareToken.objects.create(
        session=session_with_messages, created_by=session_with_messages.owner,
    )
    resp = client.get(f"/api/sessions/{session_with_messages.slug}/share")
    tokens = resp.json()["data"]
    assert len(tokens) == 1


# --- revoke share token ---

def test_revoke_share_token(client, session_with_messages):
    token = ShareToken.objects.create(
        session=session_with_messages, created_by=session_with_messages.owner,
    )
    resp = client.delete(
        f"/api/sessions/{session_with_messages.slug}/share/{token.token}"
    )
    assert resp.status_code == 200
    token.refresh_from_db()
    assert token.revoked_at is not None


def test_revoke_nonexistent_token_404(client, session_with_messages):
    resp = client.delete(
        f"/api/sessions/{session_with_messages.slug}/share/bogus-token"
    )
    assert resp.status_code == 404


# --- public share view ---

def test_public_share_view(session_with_messages):
    token = ShareToken.objects.create(
        session=session_with_messages,
        created_by=session_with_messages.owner,
    )
    anon_client = APIClient()
    resp = anon_client.get(f"/api/share/{token.token}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["title"] == "Test session"
    assert len(body["messages"]) == 2
    for msg in body["messages"]:
        assert "sender" not in msg
        assert "role" in msg
        assert "plaintext" in msg


def test_public_share_view_revoked_token(session_with_messages):
    from django.utils import timezone

    token = ShareToken.objects.create(
        session=session_with_messages,
        created_by=session_with_messages.owner,
        revoked_at=timezone.now(),
    )
    anon_client = APIClient()
    resp = anon_client.get(f"/api/share/{token.token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "revoked"


def test_public_share_view_invalid_token():
    anon_client = APIClient()
    resp = anon_client.get("/api/share/totally-bogus-token")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
