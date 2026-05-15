"""Contract tests for apps.sessions.api.

Pattern mirrors apps/opps/tests/test_api.py:
- Each helper is patched at its module-level name.
- member_client / non_member_client fixtures for workspace access control.
- anon_client fixture for 401 tests.
"""
import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

# ---------------------------------------------------------------------------
# Fake data
# ---------------------------------------------------------------------------

_FAKE_SESSION_LIST = {
    "slug": "sess-0001",
    "title": "My session",
    "status": "active",
    "backend_kind": "cli",
    "source": "web",
    "cli_session_id": None,
    "created_at": "2026-05-14T09:00:00Z",
    "updated_at": "2026-05-14T10:00:00Z",
    "message_count": 0,
    "preview": "",
    "opp_slug": "",
    "opp_run_id": "",
    "opp_step_skill": "",
    "opp_display_name": "",
    "opp_step_skill_display": "",
}

_FAKE_TURN_STATE = {
    "running": False,
    "last_message_at": None,
    "cli": None,
}

_FAKE_COST_BREAKDOWN = {
    "schema_version": 0,
    "totals": None,
    "phases": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def member_client(db, client):
    creator = User.objects.create_user(email="creator@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def non_member_client(db, client):
    creator = User.objects.create_user(email="creator2@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="outsider@example.com")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def anon_client(db, client):
    creator = User.objects.create_user(email="creator3@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    return client, workspace


# ---------------------------------------------------------------------------
# 2.2.2 — GET / — list sessions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_sessions_returns_page(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.list_sessions_in_workspace",
        lambda ws, **kwargs: [_FAKE_SESSION_LIST],
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "sess-0001"


@pytest.mark.django_db
def test_list_sessions_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_sessions_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_sessions_opp_filter_passed_through(member_client, monkeypatch):
    client, workspace, _ = member_client
    captured: dict = {}

    def _fake(ws, *, opp_slug, archived):
        captured["opp_slug"] = opp_slug
        return []

    monkeypatch.setattr("apps.sessions.api.list_sessions_in_workspace", _fake)
    resp = client.get(f"/api/w/{workspace.slug}/sessions?opp_slug=some-opp")
    assert resp.status_code == 200
    assert captured["opp_slug"] == "some-opp"


# ---------------------------------------------------------------------------
# 2.2.3 — POST / — create session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_session_201(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.create_session_in_workspace",
        lambda ws, user, body: {**_FAKE_SESSION_LIST, "title": body.title},
    )
    resp = client.post(
        f"/api/w/{workspace.slug}/sessions",
        {"title": "New chat"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "New chat"


@pytest.mark.django_db
def test_create_session_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.post(
        f"/api/w/{workspace.slug}/sessions",
        {"title": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_session_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.post(
        f"/api/w/{workspace.slug}/sessions",
        {"title": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2.2.4 — GET /{slug} — session detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_session_detail_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    detail = {**_FAKE_SESSION_LIST, "messages": []}
    monkeypatch.setattr(
        "apps.sessions.api.get_session_detail",
        lambda ws, slug: detail if slug == "sess-0001" else None,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "sess-0001"
    assert "messages" in resp.json()


@pytest.mark.django_db
def test_get_session_detail_unknown_slug_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.get_session_detail", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_session_detail_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_session_detail_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2.2.5 — PATCH /{slug} — update session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_session_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.patch_session_in_workspace",
        lambda ws, slug, updates: {**_FAKE_SESSION_LIST, **updates},
    )
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/sess-0001",
        {"title": "Updated"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"


@pytest.mark.django_db
def test_patch_session_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.patch_session_in_workspace", lambda *a, **k: None)
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/no-such",
        {"title": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_patch_session_invalid_status_422(member_client, monkeypatch):
    """Pydantic validates the Literal type before the handler runs; expect 422."""
    client, workspace, _ = member_client
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/sess-0001",
        {"status": "deleted"},
        content_type="application/json",
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_patch_session_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.patch(
        f"/api/w/{workspace.slug}/sessions/s",
        {},
        content_type="application/json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.6 — DELETE /{slug} — delete session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_session_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.delete_session_in_workspace", lambda ws, slug: True)
    resp = client.delete(f"/api/w/{workspace.slug}/sessions/sess-0001")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_delete_session_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.delete_session_in_workspace", lambda ws, slug: False
    )
    resp = client.delete(f"/api/w/{workspace.slug}/sessions/no-such")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_session_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.delete(f"/api/w/{workspace.slug}/sessions/s")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.7 — GET /{slug}/messages — message history
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_messages_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_msgs = [
        {
            "id": 1,
            "turn_index": 0,
            "role": "user",
            "content": {"type": "text", "text": "hi"},
            "plaintext": "hi",
            "status": "complete",
            "error_detail": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-05-14T09:00:00Z",
        }
    ]
    monkeypatch.setattr(
        "apps.sessions.api.list_messages_for_session",
        lambda ws, slug: fake_msgs,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["role"] == "user"


@pytest.mark.django_db
def test_list_messages_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.list_messages_for_session", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/messages")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_messages_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/messages")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.8 — GET /{slug}/participants — participant list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_participants_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_parts = [
        {
            "user_id": 1,
            "email": "a@example.com",
            "display_name": "Alice",
            "role": "owner",
            "joined_at": "2026-05-14T09:00:00Z",
            "last_seen_at": None,
        }
    ]
    monkeypatch.setattr(
        "apps.sessions.api.list_participants_for_session",
        lambda ws, slug: fake_parts,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/participants")
    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "a@example.com"


@pytest.mark.django_db
def test_list_participants_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.list_participants_for_session", lambda ws, slug: None
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/participants")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_participants_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/participants")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.9 — GET /{slug}/turn-state — polling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_turn_state_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_turn_state",
        lambda ws, slug: _FAKE_TURN_STATE,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/turn-state")
    assert resp.status_code == 200
    assert resp.json()["running"] is False


@pytest.mark.django_db
def test_turn_state_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.get_turn_state", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/turn-state")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_turn_state_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/turn-state")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.10 — GET /{slug}/cost — cost breakdown
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cost_breakdown_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_cost_breakdown",
        lambda ws, slug: _FAKE_COST_BREAKDOWN,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/cost")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == 0
    assert body["totals"] is None


@pytest.mark.django_db
def test_cost_breakdown_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.get_cost_breakdown", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/cost")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cost_breakdown_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/cost")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.11 — GET /{slug}/structure — structure tree
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_structure_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_tree = {
        "schema_version": 1,
        "session": None,
        "phases": [],
        "unavailable_reason": "no-raw-jsonl",
    }
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: (fake_tree, None, False),
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/structure")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_structure_304_when_etag_matches(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: ({}, '"v1:abc"', True),
    )
    resp = client.get(
        f"/api/w/{workspace.slug}/sessions/sess-0001/structure",
        HTTP_IF_NONE_MATCH='"v1:abc"',
    )
    assert resp.status_code == 304


@pytest.mark.django_db
def test_structure_etag_in_response(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_tree = {"schema_version": 1, "session": None, "phases": []}
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: (fake_tree, '"v1:abc123"', False),
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/structure")
    assert resp.status_code == 200
    assert resp["ETag"] == '"v1:abc123"'


@pytest.mark.django_db
def test_structure_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.get_structure_tree",
        lambda ws, slug, if_none_match=None: (None, None, False),
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/structure")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_structure_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/structure")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2.2.12 — GET /{slug}/share — share tokens
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_share_tokens_empty(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.sessions.api.list_share_tokens",
        lambda ws, slug: [],
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/share")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_list_share_tokens_returns_tokens(member_client, monkeypatch):
    client, workspace, _ = member_client
    fake_tokens = [
        {
            "token": "tok123",
            "created_at": "2026-05-14T09:00:00Z",
            "revoked_at": None,
            "url": None,
        }
    ]
    monkeypatch.setattr(
        "apps.sessions.api.list_share_tokens",
        lambda ws, slug: fake_tokens,
    )
    resp = client.get(f"/api/w/{workspace.slug}/sessions/sess-0001/share")
    assert resp.status_code == 200
    assert resp.json()[0]["token"] == "tok123"


@pytest.mark.django_db
def test_list_share_tokens_not_found_404(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr("apps.sessions.api.list_share_tokens", lambda ws, slug: None)
    resp = client.get(f"/api/w/{workspace.slug}/sessions/no-such/share")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_share_tokens_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/share")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_share_tokens_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.get(f"/api/w/{workspace.slug}/sessions/s/share")
    assert resp.status_code == 401
