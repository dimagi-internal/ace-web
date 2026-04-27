"""Permission helpers: is_member, role_for, require_role, user_workspaces."""
import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.workspaces.permissions import (
    is_member,
    require_role,
    role_for,
    user_workspaces,
)

User = get_user_model()


def make_user(email):
    return User.objects.create_user(email=email)


def make_ws(slug, owner):
    return Workspace.objects.create(
        slug=slug, display_name=slug.title(),
        drive_root_folder_id=f"folder-{slug}", created_by=owner,
    )


@pytest.mark.django_db
def test_is_member_true_when_member():
    alice = make_user("alice@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    assert is_member(alice, ws) is True


@pytest.mark.django_db
def test_is_member_false_when_not_member():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    assert is_member(bob, ws) is False


@pytest.mark.django_db
def test_role_for_returns_role_or_none():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="editor")
    assert role_for(alice, ws) == "editor"
    assert role_for(bob, ws) is None


@pytest.mark.django_db
def test_user_workspaces_returns_only_member_workspaces():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws_a = make_ws("acme", alice)
    ws_b = make_ws("beta", alice)
    WorkspaceMembership.objects.create(workspace=ws_a, user=alice, role="owner")
    WorkspaceMembership.objects.create(workspace=ws_a, user=bob, role="viewer")
    WorkspaceMembership.objects.create(workspace=ws_b, user=alice, role="owner")
    slugs_for_bob = set(user_workspaces(bob).values_list("slug", flat=True))
    assert slugs_for_bob == {"acme"}


@pytest.mark.django_db
def test_require_role_passes_when_role_meets_minimum():
    alice = make_user("alice@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="editor")
    assert require_role(alice, ws, "viewer") is True
    assert require_role(alice, ws, "editor") is True
    assert require_role(alice, ws, "owner") is False


@pytest.mark.django_db
def test_require_role_false_for_non_member():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    assert require_role(bob, ws, "viewer") is False
