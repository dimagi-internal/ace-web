"""GET /api/workspaces/ list, detail, drive-config endpoint tests."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


def make_user(email):
    return User.objects.create_user(email=email)


def make_ws(slug, owner, **extra):
    ws = Workspace.objects.create(
        slug=slug, display_name=extra.get("display_name", slug.title()),
        drive_root_folder_id=extra.get("drive_root_folder_id", f"folder-{slug}"),
        created_by=owner,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return ws


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


@pytest.fixture
def auth_client(alice):
    c = APIClient()
    c.force_authenticate(alice)
    return c


@pytest.mark.django_db
def test_list_workspaces_returns_only_member_workspaces(auth_client, alice, bob):
    make_ws("acme", alice)
    make_ws("beta", bob)  # alice is NOT a member
    resp = auth_client.get("/api/workspaces/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    slugs = {w["slug"] for w in body}
    assert slugs == {"acme"}


@pytest.mark.django_db
def test_list_workspaces_includes_my_role(auth_client, alice):
    make_ws("acme", alice)
    resp = auth_client.get("/api/workspaces/")
    body = resp.json()["data"]
    assert body[0]["role"] == "owner"


@pytest.mark.django_db
def test_workspace_detail_for_member(auth_client, alice):
    ws = make_ws("acme", alice)
    resp = auth_client.get(f"/api/workspaces/{ws.slug}/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["slug"] == "acme"
    assert body["my_role"] == "owner"
    assert len(body["members"]) == 1
    assert body["members"][0]["user_email"] == "alice@example.com"


@pytest.mark.django_db
def test_workspace_detail_returns_404_for_non_member(auth_client, alice, bob):
    make_ws("acme", alice)
    ws_b = make_ws("beta", bob)
    resp = auth_client.get(f"/api/workspaces/{ws_b.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_workspaces_unauth_401():
    c = APIClient()
    resp = c.get("/api/workspaces/")
    assert resp.status_code in (401, 403)


# ─────────────────────────── Phase B: workspace creation ───────────────────────────

@pytest.mark.django_db
def test_create_workspace_basic(auth_client, alice):
    resp = auth_client.post("/api/workspaces/", {
        "display_name": "Acme Co",
        "drive_root_folder_id": "folder-1",
    }, format="json")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["slug"] == "acme-co"
    assert body["my_role"] == "owner"
    ws = Workspace.objects.get(slug="acme-co")
    assert ws.created_by == alice
    assert ws.memberships.filter(user=alice, role="owner").exists()


@pytest.mark.django_db
def test_create_workspace_parses_drive_url(auth_client):
    resp = auth_client.post("/api/workspaces/", {
        "display_name": "Beta",
        "drive_root_folder_id":
            "https://drive.google.com/drive/folders/1HThsA_0Lr5p1OdI5r-aQ446HlNBaySLz",
    }, format="json")
    assert resp.status_code == 201
    ws = Workspace.objects.get(slug="beta")
    assert ws.drive_root_folder_id == "1HThsA_0Lr5p1OdI5r-aQ446HlNBaySLz"


@pytest.mark.django_db
def test_create_workspace_rejects_duplicate_folder(auth_client, alice, bob):
    Workspace.objects.create(
        slug="other", display_name="Other",
        drive_root_folder_id="folder-claimed", created_by=bob,
    )
    resp = auth_client.post("/api/workspaces/", {
        "display_name": "Mine",
        "drive_root_folder_id": "folder-claimed",
    }, format="json")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "folder-already-claimed"


@pytest.mark.django_db
def test_create_workspace_appends_suffix_on_slug_collision(auth_client, alice, bob):
    Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-other", created_by=bob,
    )
    resp = auth_client.post("/api/workspaces/", {
        "display_name": "Acme",
        "drive_root_folder_id": "folder-mine",
    }, format="json")
    assert resp.status_code == 201
    assert resp.json()["data"]["slug"] == "acme-2"


@pytest.mark.django_db
def test_create_workspace_requires_fields(auth_client):
    resp = auth_client.post("/api/workspaces/", {"display_name": "x"}, format="json")
    assert resp.status_code == 400


# ─────────────────────────── Phase B: members ───────────────────────────

@pytest.mark.django_db
def test_invite_member_creates_invite(auth_client, alice):
    ws = make_ws("acme", alice)
    resp = auth_client.post(
        f"/api/workspaces/{ws.slug}/members/",
        {"email": "bob@example.com", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["email"] == "bob@example.com"
    assert body["role"] == "editor"
    assert body["token"]
    from apps.workspaces.models import WorkspaceInvite
    assert WorkspaceInvite.objects.filter(workspace=ws, email="bob@example.com").exists()


@pytest.mark.django_db
def test_invite_member_rejects_already_member(auth_client, alice):
    ws = make_ws("acme", alice)
    resp = auth_client.post(
        f"/api/workspaces/{ws.slug}/members/",
        {"email": "alice@example.com", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already-member"


@pytest.mark.django_db
def test_invite_member_requires_owner(alice, bob):
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=bob, role="editor")
    c = APIClient()
    c.force_authenticate(bob)
    resp = c.post(
        f"/api/workspaces/{ws.slug}/members/",
        {"email": "carol@example.com", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_remove_member_owner_only(alice, bob):
    ws = make_ws("acme", alice)
    bob_m = WorkspaceMembership.objects.create(workspace=ws, user=bob, role="editor")
    c_alice = APIClient()
    c_alice.force_authenticate(alice)
    resp = c_alice.delete(f"/api/workspaces/{ws.slug}/members/{bob.id}/")
    assert resp.status_code == 204
    assert not WorkspaceMembership.objects.filter(id=bob_m.id).exists()


@pytest.mark.django_db
def test_cannot_remove_last_owner(auth_client, alice):
    ws = make_ws("acme", alice)
    resp = auth_client.delete(f"/api/workspaces/{ws.slug}/members/{alice.id}/")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "last-owner"


@pytest.mark.django_db
def test_change_member_role(alice, bob, auth_client):
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=bob, role="viewer")
    resp = auth_client.patch(
        f"/api/workspaces/{ws.slug}/members/{bob.id}/",
        {"role": "editor"}, format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "editor"


# ─────────────────────────── Phase B: invite preview + accept ───────────────────────────


@pytest.mark.django_db
def test_invite_preview_unauthenticated_works():
    """Public preview — visible without login."""
    from datetime import timedelta

    from apps.workspaces.models import WorkspaceInvite
    alice = make_user("alice@example.com")
    ws = make_ws("acme", alice)
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=alice,
        expires_at=__import__("django.utils.timezone", fromlist=["now"]).now()
            + timedelta(days=7),
    )
    c = APIClient()
    resp = c.get(f"/api/invites/{inv.token}/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["workspace_slug"] == "acme"
    assert body["role"] == "editor"
    assert body["email"] == "bob@example.com"


@pytest.mark.django_db
def test_invite_accept_creates_membership():
    from datetime import timedelta

    from apps.workspaces.models import WorkspaceInvite
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=alice,
        expires_at=__import__("django.utils.timezone", fromlist=["now"]).now()
            + timedelta(days=7),
    )
    c = APIClient()
    c.force_authenticate(bob)
    resp = c.post(f"/api/invites/{inv.token}/accept/")
    assert resp.status_code == 200
    assert resp.json()["data"]["newly_joined"] is True
    assert WorkspaceMembership.objects.filter(workspace=ws, user=bob, role="editor").exists()
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_invite_accept_email_mismatch_403():
    from datetime import timedelta

    from apps.workspaces.models import WorkspaceInvite
    alice = make_user("alice@example.com")
    eve = make_user("eve@example.com")
    ws = make_ws("acme", alice)
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=alice,
        expires_at=__import__("django.utils.timezone", fromlist=["now"]).now()
            + timedelta(days=7),
    )
    c = APIClient()
    c.force_authenticate(eve)
    resp = c.post(f"/api/invites/{inv.token}/accept/")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email-mismatch"


# ─────────────────────────── Phase C: leave-workspace ───────────────────────────


@pytest.mark.django_db
def test_leave_workspace_self_remove(alice, bob):
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=bob, role="editor")
    c = APIClient()
    c.force_authenticate(bob)
    resp = c.post(f"/api/workspaces/{ws.slug}/leave/")
    assert resp.status_code == 204
    assert not WorkspaceMembership.objects.filter(workspace=ws, user=bob).exists()


@pytest.mark.django_db
def test_leave_workspace_last_owner_blocked(auth_client, alice):
    ws = make_ws("acme", alice)
    resp = auth_client.post(f"/api/workspaces/{ws.slug}/leave/")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "last-owner"


@pytest.mark.django_db
def test_activity_owner_only(auth_client, alice, bob):
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=bob, role="editor")
    # Owner can fetch
    resp = auth_client.get(f"/api/workspaces/{ws.slug}/activity/")
    assert resp.status_code == 200

    # Non-owner forbidden
    c = APIClient()
    c.force_authenticate(bob)
    resp = c.get(f"/api/workspaces/{ws.slug}/activity/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_activity_returns_workspace_scoped_logs(auth_client, alice):
    """Audit log is read-through to AccessLog.context.workspace_slug."""
    from apps.service_accounts.models import AccessLog, ServiceAccount
    ws = make_ws("acme", alice)
    sa = ServiceAccount.objects.create(
        name="t-sa", credential_type="api_key", credential_encrypted="x",
    )
    AccessLog.objects.create(
        service_account=sa, action="direct_access",
        scopes_used=[], context={"workspace_slug": "acme"},
    )
    AccessLog.objects.create(
        service_account=sa, action="direct_access",
        scopes_used=[], context={"workspace_slug": "other"},
    )
    resp = auth_client.get(f"/api/workspaces/{ws.slug}/activity/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 1
    assert body[0]["context"]["workspace_slug"] == "acme"
