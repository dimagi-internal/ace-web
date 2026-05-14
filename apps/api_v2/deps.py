"""Shared route dependencies.

These functions are called from inside Ninja handlers (not as
`Depends()` — Ninja uses path/query params directly). They raise
`ProblemError` on failure so the v2 error handler renders
problem+json.

Workspace existence is never leaked: non-members get 404, not 403.
This matches the policy enforced in `apps/common/access.py`.
"""
from __future__ import annotations

from django.http import HttpRequest

from apps.workspaces.models import Workspace, WorkspaceMembership

from .errors import TYPE_FORBIDDEN, TYPE_NOT_FOUND, ProblemError


def resolve_workspace_for_member(request: HttpRequest, slug: str) -> Workspace:
    """Resolve `slug` to a Workspace iff request.user is a member.

    Raises ProblemError(404) for anyone else (including authenticated
    users who aren't in this workspace — workspace existence is hidden).
    """
    workspace = Workspace.objects.filter(slug=slug).first()
    if workspace is None:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    is_member = WorkspaceMembership.objects.filter(
        workspace=workspace, user=request.user
    ).exists()
    if not is_member:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return workspace


def require_write_global(request: HttpRequest) -> None:
    """Raise ProblemError(403) if the user cannot perform global write operations.

    Mirrors ``apps.common.auth_views._can_write_global``: staff users and
    accounts in the ``@dimagi-ai.com`` automation domain are permitted;
    everyone else gets 403.
    """
    from apps.common.auth_views import _can_write_global

    if not _can_write_global(request.user):
        raise ProblemError(403, "Forbidden", type_=TYPE_FORBIDDEN)
