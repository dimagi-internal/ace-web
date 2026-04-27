"""Model invariants for apps.workspaces."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from apps.workspaces.models import (
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)

User = get_user_model()


@pytest.mark.django_db
def test_workspace_creation_minimal():
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme",
        display_name="Acme Co",
        drive_root_folder_id="folder-1",
        created_by=user,
    )
    assert ws.slug == "acme"
    assert ws.created_by == user
    assert ws.settings == {}


@pytest.mark.django_db
def test_workspace_drive_root_folder_id_is_unique():
    user = User.objects.create_user(email="alice@example.com")
    Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    with pytest.raises(IntegrityError):
        Workspace.objects.create(
            slug="acme-2", display_name="Acme 2",
            drive_root_folder_id="folder-1", created_by=user,
        )


@pytest.mark.django_db
def test_workspace_str():
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme Co",
        drive_root_folder_id="folder-1", created_by=user,
    )
    assert str(ws) == "Acme Co (acme)"


@pytest.mark.django_db
def test_membership_creation():
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    m = WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    assert m.role == "owner"
    assert m.invited_by is None


@pytest.mark.django_db
def test_membership_unique_per_user_per_workspace():
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    with pytest.raises(IntegrityError):
        WorkspaceMembership.objects.create(workspace=ws, user=user, role="editor")


@pytest.mark.django_db
def test_membership_role_choices():
    owner = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=owner,
    )
    for role in ("owner", "editor", "viewer"):
        u = User.objects.create_user(email=f"{role}@example.com")
        m = WorkspaceMembership(workspace=ws, user=u, role=role)
        m.full_clean()  # raises ValidationError on bad choice


@pytest.mark.django_db
def test_invite_token_unique():
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=user, expires_at=timezone.now() + timedelta(days=7),
    )
    assert len(inv.token) >= 32
    with pytest.raises(IntegrityError):
        WorkspaceInvite.objects.create(
            workspace=ws, email="charlie@example.com", role="editor",
            invited_by=user, expires_at=timezone.now() + timedelta(days=7),
            token=inv.token,
        )


@pytest.mark.django_db
def test_invite_is_pending():
    user = User.objects.create_user(email="alice@example.com")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=user, expires_at=timezone.now() + timedelta(days=7),
    )
    assert inv.is_pending() is True
    inv.accepted_at = timezone.now()
    assert inv.is_pending() is False

    inv2 = WorkspaceInvite.objects.create(
        workspace=ws, email="dora@example.com", role="editor",
        invited_by=user, expires_at=timezone.now() - timedelta(days=1),
    )
    assert inv2.is_pending() is False
