import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Message, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="other@example.com", display_name="other"
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
    titles = [s["title"] for s in resp.json()["data"]["items"]]
    assert "mine" in titles
    assert "theirs" not in titles


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
    resp = client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "x"
    assert resp.json()["data"]["messages"] == []


def test_get_session_404_for_other_users_session(client, other_user):
    s = Session.objects.create(owner=other_user, title="hidden")
    resp = client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 404


def test_patch_session_updates_title(client, user):
    s = Session.objects.create(owner=user, title="old")
    resp = client.patch(f"/api/sessions/{s.slug}", {"title": "new"}, format="json")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.title == "new"


def test_patch_session_updates_status(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.patch(f"/api/sessions/{s.slug}", {"status": "archived"}, format="json")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.status == "archived"


def test_patch_session_rejects_unknown_field(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.patch(f"/api/sessions/{s.slug}", {"slug": "hacked"}, format="json")
    assert resp.status_code == 200  # ignored, slug is read-only
    s.refresh_from_db()
    assert s.slug != "hacked"


def test_post_message_creates_user_and_assistant_rows(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "hello"}, format="json")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "user_message_id" in body
    assert "assistant_message_id" in body

    user_msg = Message.objects.get(id=body["user_message_id"])
    asst_msg = Message.objects.get(id=body["assistant_message_id"])
    assert user_msg.role == "user"
    assert user_msg.plaintext == "hello"
    assert user_msg.status == "complete"
    assert asst_msg.role == "assistant"
    assert asst_msg.status == "pending"


def test_post_message_assigns_monotonic_turn_index(client, user):
    s = Session.objects.create(owner=user, title="x")
    Message.objects.create(
        session=s, turn_index=5, role="user",
        content={"text": "old"}, plaintext="old", status="complete",
    )
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "next"}, format="json")
    body = resp.json()["data"]
    user_msg = Message.objects.get(id=body["user_message_id"])
    asst_msg = Message.objects.get(id=body["assistant_message_id"])
    assert user_msg.turn_index == 6
    assert asst_msg.turn_index == 7


def test_post_message_404_for_other_users_session(client, other_user):
    s = Session.objects.create(owner=other_user)
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "x"}, format="json")
    assert resp.status_code == 404


def test_post_message_validates_empty_text(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "   "}, format="json")
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
    resp = client.delete(f"/api/sessions/{s.slug}")
    assert resp.status_code == 204
    assert not Session.objects.filter(slug=s.slug).exists()


def test_delete_session_cascades_messages(client, user):
    s = Session.objects.create(owner=user, title="has msgs")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    client.delete(f"/api/sessions/{s.slug}")
    assert Message.objects.count() == 0


def test_delete_session_403_for_non_owner(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="not mine")
    resp = client.delete(f"/api/sessions/{s.slug}")
    assert resp.status_code == 404
    assert Session.objects.filter(slug=s.slug).exists()


def test_delete_session_404_for_missing(client):
    resp = client.delete("/api/sessions/no-such-slug")
    assert resp.status_code == 404
