"""Contract tests for apps.activity.api."""
import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

_FAKE_ACTIVITY = {
    "items": [
        {
            "kind": "chat",
            "ts": "2026-05-14T09:00:00Z",
            "opp_slug": "my-opp",
            "step_skill": None,
            "title": "Session started",
            "session_slug": "sess-001",
            "meta": {"source": "web", "status": "active", "message_count": 3},
        }
    ],
    "total": 1,
}


@pytest.fixture
def member_client(db, client):
    user = User.objects.create_user(email="member@example.com")
    ws = Workspace.objects.create(
        slug="activity-ws",
        display_name="Activity WS",
        drive_root_folder_id="folder-activity",
        created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="editor")
    client.force_login(user)
    return client, ws, user


@pytest.fixture
def non_member_client(db, client):
    creator = User.objects.create_user(email="creator@example.com")
    ws = Workspace.objects.create(
        slug="activity-ws",
        display_name="Activity WS",
        drive_root_folder_id="folder-activity",
        created_by=creator,
    )
    outsider = User.objects.create_user(email="outsider@example.com")
    client.force_login(outsider)
    return client, ws, outsider


@pytest.fixture
def anon_client(db, client):
    user = User.objects.create_user(email="creator2@example.com")
    ws = Workspace.objects.create(
        slug="activity-ws",
        display_name="Activity WS",
        drive_root_folder_id="folder-activity",
        created_by=user,
    )
    return client, ws


# ---------------------------------------------------------------------------
# GET /w/{workspace_slug}/activity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_activity_feed_200(member_client, monkeypatch):
    client, ws, _ = member_client
    monkeypatch.setattr(
        "apps.activity.api.get_activity_feed",
        lambda workspace, user, request, **kwargs: _FAKE_ACTIVITY,
    )
    resp = client.get(f"/api/w/{ws.slug}/activity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "chat"


@pytest.mark.django_db
def test_activity_feed_non_member_404(non_member_client):
    client, ws, _ = non_member_client
    resp = client.get(f"/api/w/{ws.slug}/activity")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_activity_feed_anon_401(anon_client):
    client, ws = anon_client
    resp = client.get(f"/api/w/{ws.slug}/activity")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_activity_feed_opp_filter_passed_through(member_client, monkeypatch):
    client, ws, _ = member_client
    captured: dict = {}

    def _fake(workspace, user, request, opp_slug=None, event_types="chat,verdict", limit=200):
        captured["opp_slug"] = opp_slug
        return {"items": [], "total": 0}

    monkeypatch.setattr("apps.activity.api.get_activity_feed", _fake)
    client.get(f"/api/w/{ws.slug}/activity?opp=my-opp")
    assert captured["opp_slug"] == "my-opp"


# ---------------------------------------------------------------------------
# GET /w/{workspace_slug}/activity/runs
# ---------------------------------------------------------------------------


_FAKE_WORKSPACE_ACTIVITY = {
    "rows": [
        {
            "opp_slug": "rural-tb",
            "opp_display_name": "Rural TB Screening",
            "run_id": "20260515-1830",
            "last_activity_at": "2026-05-15T18:30:00Z",
            "current_phase_name": "scenarios-and-acceptance",
            "current_phase_display": "Scenarios & Acceptance",
            "current_step_name": "scenarios",
            "current_step_display": "Scenarios",
            "lifecycle_status": "in_progress",
            "last_actor": None,
            "source_hint": "ace-web",
            "source_actor_email": "jj@dimagi.com",
            "phase_url": "https://example/w/activity-ws/opps/rural-tb?run_id=20260515-1830",
        }
    ],
    "server_now": "2026-05-15T18:31:00Z",
}


@pytest.mark.django_db
def test_workspace_activity_runs_200(member_client, monkeypatch):
    client, ws, _ = member_client
    monkeypatch.setattr(
        "apps.activity.api.get_workspace_activity",
        lambda workspace, **kwargs: _FAKE_WORKSPACE_ACTIVITY,
    )
    resp = client.get(f"/api/w/{ws.slug}/activity/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert "server_now" in body
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["opp_slug"] == "rural-tb"
    assert row["source_hint"] == "ace-web"
    assert row["lifecycle_status"] == "in_progress"


@pytest.mark.django_db
def test_workspace_activity_runs_requires_membership(non_member_client, monkeypatch):
    client, ws, _ = non_member_client
    monkeypatch.setattr(
        "apps.activity.api.get_workspace_activity",
        lambda workspace, **kwargs: _FAKE_WORKSPACE_ACTIVITY,
    )
    resp = client.get(f"/api/w/{ws.slug}/activity/runs")
    # Non-members get 404 (per the workspace privacy convention: don't
    # leak existence). 403 also acceptable, but 200 is not.
    assert resp.status_code in (403, 404)


@pytest.mark.django_db
def test_workspace_activity_runs_rejects_anon(anon_client, monkeypatch):
    client, ws = anon_client
    monkeypatch.setattr(
        "apps.activity.api.get_workspace_activity",
        lambda workspace, **kwargs: _FAKE_WORKSPACE_ACTIVITY,
    )
    resp = client.get(f"/api/w/{ws.slug}/activity/runs")
    assert resp.status_code in (401, 403, 404)


@pytest.mark.django_db
def test_workspace_activity_runs_passes_include_completed(member_client, monkeypatch):
    client, ws, _ = member_client
    captured = {}

    def _spy(workspace, **kwargs):
        captured.update(kwargs)
        return _FAKE_WORKSPACE_ACTIVITY

    monkeypatch.setattr("apps.activity.api.get_workspace_activity", _spy)
    resp = client.get(
        f"/api/w/{ws.slug}/activity/runs?include_completed=false&limit=5"
    )
    assert resp.status_code == 200
    assert captured.get("include_completed") is False
    assert captured.get("limit") == 5
