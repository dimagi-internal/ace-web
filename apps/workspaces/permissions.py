"""Membership + role helpers for workspace-scoped views.

Roles form a hierarchy: viewer < editor < owner. `require_role(user, ws, "editor")`
returns True for editors AND owners.
"""
from __future__ import annotations

from django.db.models import QuerySet

from apps.workspaces.models import Workspace, WorkspaceMembership

ROLE_LEVELS = {"viewer": 0, "editor": 1, "owner": 2}


def is_member(user, workspace: Workspace) -> bool:
    if not user.is_authenticated:
        return False
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user
    ).exists()


def role_for(user, workspace: Workspace) -> str | None:
    if not user.is_authenticated:
        return None
    m = (
        WorkspaceMembership.objects.filter(workspace=workspace, user=user)
        .only("role")
        .first()
    )
    return m.role if m else None


def require_role(user, workspace: Workspace, minimum: str) -> bool:
    """Return True iff user is a member of workspace with role >= minimum."""
    role = role_for(user, workspace)
    if role is None:
        return False
    return ROLE_LEVELS[role] >= ROLE_LEVELS[minimum]


def user_workspaces(user) -> QuerySet[Workspace]:
    """Workspaces the user is a member of, ordered by most-recent membership first."""
    if not user.is_authenticated:
        return Workspace.objects.none()
    return Workspace.objects.filter(memberships__user=user).order_by(
        "-memberships__joined_at"
    )
