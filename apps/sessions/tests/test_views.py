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


def test_list_sessions_returns_all_sessions(client, user, other_user):
    """Sessions are visible to every authed Dimagi user for now — the
    list endpoint is not filtered by owner (see apps/sessions/views.py
    `_list_sessions` for the deferred sharing/ACL story)."""
    Session.objects.create(owner=user, title="mine")
    Session.objects.create(owner=other_user, title="theirs")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["data"]["items"]]
    assert "mine" in titles
    assert "theirs" in titles


def test_list_sessions_owner_filter(client, user, other_user):
    Session.objects.create(owner=user, title="mine")
    Session.objects.create(owner=other_user, title="theirs")

    resp = client.get(f"/api/sessions?owner={user.id}")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["data"]["items"]]
    assert titles == ["mine"]


def test_list_sessions_filters_by_status(client, user):
    Session.objects.create(owner=user, title="active")
    Session.objects.create(owner=user, title="archived", status="archived")

    resp = client.get("/api/sessions?status=archived")
    titles = [s["title"] for s in resp.json()["data"]["items"]]
    assert titles == ["archived"]


def test_list_sessions_respects_limit(client, user):
    for i in range(15):
        Session.objects.create(owner=user, title=f"s{i}")
    resp = client.get("/api/sessions?page_size=5")
    assert len(resp.json()["data"]["items"]) == 5


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


def test_messages_list_allows_any_authed_user(client, user, other_user):
    """Any authed Dimagi user can read any session's messages for now
    (see apps/sessions/views.py `_load_session_for_participant` — the
    helper no longer gates on participant role). Sharing/ACL is a
    deferred layer."""
    s = Session.objects.create(owner=other_user, title="notmine")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi from other"}, plaintext="hi from other",
        status="complete",
    )
    resp = client.get(f"/api/sessions/{s.slug}/messages")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert rows[0]["plaintext"] == "hi from other"


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


def test_list_sessions_search_by_title(client, user):
    Session.objects.create(owner=user, title="Phase 4 library design")
    Session.objects.create(owner=user, title="CLI debugging session")
    Session.objects.create(owner=user, title="Another Phase 4 chat")
    resp = client.get("/api/sessions?q=phase+4")
    body = resp.json()["data"]
    assert body["total"] == 2
    titles = [s["title"] for s in body["items"]]
    assert "Phase 4 library design" in titles
    assert "Another Phase 4 chat" in titles
    assert "CLI debugging session" not in titles


def test_list_sessions_search_is_case_insensitive(client, user):
    Session.objects.create(owner=user, title="UPPERCASE Title")
    resp = client.get("/api/sessions?q=uppercase")
    assert resp.json()["data"]["total"] == 1


def test_list_sessions_filter_by_source(client, user):
    Session.objects.create(owner=user, title="web1", source="web")
    Session.objects.create(owner=user, title="upload1", source="upload")
    resp = client.get("/api/sessions?source=upload")
    body = resp.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["title"] == "upload1"


def test_list_sessions_pagination(client, user):
    for i in range(25):
        Session.objects.create(owner=user, title=f"s{i:02d}")
    resp = client.get("/api/sessions?page=2&page_size=10")
    body = resp.json()["data"]
    assert body["total"] == 25
    assert body["page"] == 2
    assert body["page_size"] == 10
    assert len(body["items"]) == 10


def test_list_sessions_pagination_last_page(client, user):
    for i in range(25):
        Session.objects.create(owner=user, title=f"s{i:02d}")
    resp = client.get("/api/sessions?page=3&page_size=10")
    body = resp.json()["data"]
    assert len(body["items"]) == 5


def test_list_sessions_pagination_defaults(client, user):
    Session.objects.create(owner=user, title="x")
    resp = client.get("/api/sessions")
    body = resp.json()["data"]
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_delete_session_by_owner(client, user):
    s = Session.objects.create(owner=user, title="to delete")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    resp = client.delete(f"/api/sessions/{s.slug}")
    assert resp.status_code == 204
    assert not Session.objects.filter(slug=s.slug).exists()


def test_delete_session_cascades_messages(client, user):
    s = Session.objects.create(owner=user, title="has msgs")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    client.delete(f"/api/sessions/{s.slug}")
    assert Message.objects.count() == 0


def test_delete_session_403_for_non_owner(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="not mine")
    SessionParticipant.objects.create(session=s, user=other_user, role="owner")
    SessionParticipant.objects.create(session=s, user=user, role="editor")
    resp = client.delete(f"/api/sessions/{s.slug}")
    assert resp.status_code == 403
    assert Session.objects.filter(slug=s.slug).exists()


def test_delete_session_404_for_missing(client):
    resp = client.delete("/api/sessions/no-such-slug")
    assert resp.status_code == 404


def test_activate_imported_session_helper(user):
    """Unit test for the consumer helper that auto-activates imported sessions."""
    from apps.sessions.consumers import _activate_imported_session

    s = Session.objects.create(
        owner=user, title="imported", source="upload", status="imported"
    )
    _activate_imported_session(s)
    s.refresh_from_db()
    assert s.status == "active"


def test_activate_imported_session_noop_for_active(user):
    """Active sessions are not affected by the activation helper."""
    from apps.sessions.consumers import _activate_imported_session

    s = Session.objects.create(owner=user, title="active", status="active")
    _activate_imported_session(s)
    s.refresh_from_db()
    assert s.status == "active"
