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
