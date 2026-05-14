"""Contract tests for apps.workspaces.api_v2."""

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

# ---------------------------------------------------------------------------
# Fake data
# ---------------------------------------------------------------------------

_FAKE_WORKSPACE = {
    "slug": "test-ws",
    "name": "Test Workspace",
    "drive_root_folder_id": "folder-abc",
    "role": "owner",
    "member_count": 1,
    "created_at": "2026-05-01T00:00:00Z",
    "updated_at": "2026-05-01T00:00:00Z",
}

_FAKE_MEMBER = {
    "id": 1,
    "user": {"id": 1, "email": "owner@example.com", "display_name": "Owner"},
    "role": "owner",
    "joined_at": "2026-05-01T00:00:00Z",
}

_FAKE_INVITE = {
    "token": "tok-123",
    "email": "invited@example.com",
    "role": "editor",
    "accepted": False,
    "accepted_at": None,
    "created_at": "2026-05-01T00:00:00Z",
    "updated_at": "2026-05-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def owner_client(db, client):
    user = User.objects.create_user(email="owner@example.com")
    workspace = Workspace.objects.create(
        slug="test-ws",
        display_name="Test Workspace",
        drive_root_folder_id="folder-abc",
        created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="owner")
    client.force_login(user)
    return client, workspace, user


@pytest.fixture
def member_client(db, client):
    owner = User.objects.create_user(email="owner2@example.com")
    workspace = Workspace.objects.create(
        slug="test-ws",
        display_name="Test Workspace",
        drive_root_folder_id="folder-abc",
        created_by=owner,
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role="owner")
    member = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role="editor")
    client.force_login(member)
    return client, workspace, member


@pytest.fixture
def non_member_client(db, client):
    owner = User.objects.create_user(email="owner3@example.com")
    workspace = Workspace.objects.create(
        slug="test-ws",
        display_name="Test Workspace",
        drive_root_folder_id="folder-abc",
        created_by=owner,
    )
    outsider = User.objects.create_user(email="outsider@example.com")
    client.force_login(outsider)
    return client, workspace, outsider


@pytest.fixture
def anon_client(db, client):
    owner = User.objects.create_user(email="owner4@example.com")
    workspace = Workspace.objects.create(
        slug="test-ws",
        display_name="Test Workspace",
        drive_root_folder_id="folder-abc",
        created_by=owner,
    )
    return client, workspace


# ---------------------------------------------------------------------------
# GET /workspaces — list my workspaces
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_workspaces_returns_list(owner_client, monkeypatch):
    client, workspace, user = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.list_my_workspaces",
        lambda u: [_FAKE_WORKSPACE],
    )
    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["slug"] == "test-ws"


@pytest.mark.django_db
def test_list_workspaces_anon_401(anon_client):
    client, _ = anon_client
    resp = client.get("/api/workspaces")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /workspaces — create workspace
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_workspace_201(owner_client, monkeypatch):
    client, _, user = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.create_workspace",
        lambda u, body: {**_FAKE_WORKSPACE, "name": body.name},
    )
    resp = client.post(
        "/api/workspaces",
        {"slug": "new-ws", "name": "New WS", "drive_root_folder_id": "folder-new"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "New WS"


@pytest.mark.django_db
def test_create_workspace_anon_401(anon_client):
    client, _ = anon_client
    resp = client.post(
        "/api/workspaces",
        {"slug": "x", "name": "X", "drive_root_folder_id": "folder-x"},
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /workspaces/{slug} — workspace detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_workspace_detail_happy(owner_client, monkeypatch):
    client, workspace, _ = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2._workspace_to_dict",
        lambda ws, user: _FAKE_WORKSPACE,
    )
    resp = client.get(f"/api/workspaces/{workspace.slug}")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "test-ws"


@pytest.mark.django_db
def test_workspace_detail_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/workspaces/{workspace.slug}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_workspace_detail_anon_401(anon_client):
    client, workspace = anon_client
    resp = client.get(f"/api/workspaces/{workspace.slug}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /workspaces/{slug} — update workspace
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_workspace_owner(owner_client, monkeypatch):
    client, workspace, _ = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2._workspace_to_dict",
        lambda ws, user: {**_FAKE_WORKSPACE, "name": ws.display_name},
    )
    resp = client.patch(
        f"/api/workspaces/{workspace.slug}",
        {"name": "Updated"},
        content_type="application/json",
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_patch_workspace_member_403(member_client, monkeypatch):
    client, workspace, _ = member_client
    resp = client.patch(
        f"/api/workspaces/{workspace.slug}",
        {"name": "Nope"},
        content_type="application/json",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /workspaces/{slug}/members — list members
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_members_happy(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.list_members_in_workspace",
        lambda ws: [_FAKE_MEMBER],
    )
    resp = client.get(f"/api/workspaces/{workspace.slug}/members")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["role"] == "owner"


@pytest.mark.django_db
def test_list_members_non_member_404(non_member_client):
    client, workspace, _ = non_member_client
    resp = client.get(f"/api/workspaces/{workspace.slug}/members")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/members/invite — invite
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_member_owner_201(owner_client, monkeypatch):
    client, workspace, _ = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.invite_member_to_workspace",
        lambda ws, inviter, email, role: {**_FAKE_INVITE, "email": email},
    )
    resp = client.post(
        f"/api/workspaces/{workspace.slug}/members/invite",
        {"email": "new@example.com", "role": "editor"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@example.com"


@pytest.mark.django_db
def test_invite_member_non_owner_403(member_client, monkeypatch):
    client, workspace, _ = member_client
    resp = client.post(
        f"/api/workspaces/{workspace.slug}/members/invite",
        {"email": "x@example.com", "role": "editor"},
        content_type="application/json",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /workspaces/{slug}/members/{user_id} — remove member
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_remove_member_owner_204(owner_client, monkeypatch):
    client, workspace, user = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.remove_member_from_workspace",
        lambda ws, requester, uid: None,
    )
    resp = client.delete(f"/api/workspaces/{workspace.slug}/members/999")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_remove_member_non_owner_403(member_client, monkeypatch):
    client, workspace, _ = member_client
    resp = client.delete(f"/api/workspaces/{workspace.slug}/members/999")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/leave — leave workspace
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_leave_workspace_204(member_client, monkeypatch):
    client, workspace, _ = member_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.leave_workspace_op",
        lambda ws, user: None,
    )
    resp = client.post(f"/api/workspaces/{workspace.slug}/leave")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# GET /workspaces/{slug}/activity — audit log
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_workspace_activity_owner(owner_client, monkeypatch):
    client, workspace, _ = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.get_workspace_activity",
        lambda ws, user: [],
    )
    resp = client.get(f"/api/workspaces/{workspace.slug}/activity")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["total"] == 0


@pytest.mark.django_db
def test_workspace_activity_member_403(member_client, monkeypatch):
    client, workspace, _ = member_client
    resp = client.get(f"/api/workspaces/{workspace.slug}/activity")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/drive-config/verify — verify drive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_drive_happy(owner_client, monkeypatch):
    client, workspace, _ = owner_client
    monkeypatch.setattr(
        "apps.workspaces.api_v2.verify_drive_access_for_workspace",
        lambda ws: {"ok": True, "sample_files": [], "total_visible": 0},
    )
    resp = client.post(f"/api/workspaces/{workspace.slug}/drive-config/verify")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
