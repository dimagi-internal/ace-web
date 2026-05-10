"""Shared workspace access helpers for views across apps.

Membership gating was reimplemented in 4+ places (apps/opps/access.py,
apps/workspaces/views.py, apps/ingest/views.py, apps/sessions/views.py).
The pieces that's actually shared is small but load-bearing: how to
turn ``(user, workspace)`` into a 404 / 403 / OK Response.

This module isolates that decision so per-app lookup code (by slug, by
header, by session_id, by drive_root_folder_id) stays where it makes
sense, but the response shape stays uniform.
"""
from __future__ import annotations

from rest_framework.response import Response

from apps.common.envelope import error_response


def gate_membership(user, workspace, *, hidden_existence: bool = True):
    """Return None if the caller may read the workspace, else an error Response.

    ``hidden_existence`` (default True) returns a 404 envelope when the
    user isn't a member, so workspace existence isn't leaked. Set to
    False to return a 403 instead — appropriate when the workspace
    identifier is already known to the caller (e.g., they uploaded a
    file claiming a specific drive_root_folder_id, so existence-hiding
    is moot).
    """
    if not user or not user.is_authenticated:
        return Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )

    # Local import to avoid app-init ordering surprises during ``manage.py
    # migrate`` and to keep this module dependency-light.
    from apps.workspaces.permissions import is_member

    if not is_member(user, workspace):
        if hidden_existence:
            return Response(
                error_response("workspace not found", code="not-found"),
                status=404,
            )
        return Response(
            error_response(
                "you are not a member of this workspace",
                code="not-a-member",
            ),
            status=403,
        )
    return None
