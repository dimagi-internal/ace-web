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
