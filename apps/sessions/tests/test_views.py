import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Message, Session, SessionParticipant

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


def test_create_session_returns_slug(client):
    resp = client.post("/api/sessions", {}, format="json")
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert "slug" in body["data"]
    assert body["data"]["status"] == "active"


def test_create_session_creates_owner_participant(client, user):
    resp = client.post("/api/sessions", {}, format="json")
    slug = resp.json()["data"]["slug"]
    s = Session.objects.get(slug=slug)
    assert s.participants.filter(user=user, role="owner").exists()


def test_list_sessions_only_returns_current_user(client, user, other_user):
    Session.objects.create(owner=user, title="mine")
    Session.objects.create(owner=other_user, title="theirs")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["data"]]
    assert "mine" in titles
    assert "theirs" not in titles


def test_list_sessions_filters_by_status(client, user):
    Session.objects.create(owner=user, title="active")
    Session.objects.create(owner=user, title="archived", status="archived")

    resp = client.get("/api/sessions?status=archived")
    titles = [s["title"] for s in resp.json()["data"]]
    assert titles == ["archived"]


def test_list_sessions_respects_limit(client, user):
    for i in range(15):
        Session.objects.create(owner=user, title=f"s{i}")
    resp = client.get("/api/sessions?limit=5")
    assert len(resp.json()["data"]) == 5


def test_get_session_by_slug(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "x"
    assert resp.json()["data"]["messages"] == []


def test_patch_session_title(client, user):
    s = Session.objects.create(owner=user, title="old")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.patch(
        f"/api/sessions/{s.slug}",
        {"title": "new"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "new"


def test_messages_list_returns_ordered_messages(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    Message.objects.create(
        session=s, turn_index=2, role="assistant",
        content={"text": "hello"}, plaintext="hello", status="complete",
    )
    resp = client.get(f"/api/sessions/{s.slug}/messages")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["turn_index"] for r in rows] == [1, 2]


def test_messages_list_rejects_non_participant(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="notmine")
    resp = client.get(f"/api/sessions/{s.slug}/messages")
    assert resp.status_code == 404


def test_messages_list_allows_editor_participant(client, user, other_user):
    """An editor participant (not the session owner) can read the messages
    list. This locks in the Phase 3 auth broadening from owner-only to
    any-participant — the whole point of _load_session_for_participant."""
    s = Session.objects.create(owner=other_user, title="theirs")
    SessionParticipant.objects.create(session=s, user=other_user, role="owner")
    SessionParticipant.objects.create(session=s, user=user, role="editor")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    # `client` is authenticated as `user`, who is only an editor here.
    resp = client.get(f"/api/sessions/{s.slug}/messages")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["plaintext"] == "hi"


def test_add_participant_by_email(client, user, other_user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "bob@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["error"] is None
    assert SessionParticipant.objects.filter(session=s, user=other_user).exists()


def test_add_participant_rejects_non_dimagi_email(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "anyone@example.com"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_add_participant_rejects_unknown_email(client, user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "ghost@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_add_participant_rejects_duplicate(client, user, other_user):
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    SessionParticipant.objects.create(session=s, user=other_user, role="editor")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "bob@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_add_participant_rejects_non_owner(client, user, other_user, django_user_model):
    s = Session.objects.create(owner=other_user, title="x")
    SessionParticipant.objects.create(session=s, user=other_user, role="owner")
    SessionParticipant.objects.create(session=s, user=user, role="editor")
    # `client` is authenticated as `user`, who is only an editor here.
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "alice@dimagi.com"},
        format="json",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    # Ensure no extra participant row was created — regression guard in
    # case the 403 path ever reorders below the create.
    assert SessionParticipant.objects.filter(session=s).count() == 2


def test_add_participant_rejects_double_at_email(client, user):
    """Defense in depth: even though the downstream user lookup would
    404 on 'alice@dimagi.com@evil.com', the validation path should
    reject it at the 400 stage rather than leaking the existence (or
    non-existence) of the target user via the 404 branch."""
    s = Session.objects.create(owner=user, title="x")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.post(
        f"/api/sessions/{s.slug}/participants",
        {"email": "alice@dimagi.com@evil.com"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"
