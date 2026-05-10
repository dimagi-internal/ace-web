"""Public workspace + Drive access helpers for the opps Workbench.

These were previously private helpers (`_resolve_workspace`, `_require_drive`,
etc.) inside `apps/opps/views.py`. They were reached into from
`apps/activity/views.py` (which is a smell — private symbols becoming a
de-facto public API). Pulling them into a public module:

- gives sibling apps (activity, future readers) a clean import path
- keeps the symbol names stable when `views.py` is later split into
  `views_read.py` / `views_write.py` / etc.
- isolates the workspace/Drive boundary so it can be tested independently

`apps/opps/views.py` re-imports each of these under its original
underscore-prefixed name so existing internal call sites and ``mock.patch``
calls in tests against ``apps.opps.views._resolve_*`` keep working without
churn.
"""
from __future__ import annotations

import hashlib
import json

from rest_framework.response import Response

from apps.common.envelope import error_response
from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import get_drive_client
from apps.opps.models import OppWorkspace
from apps.opps.serializers import serialize_opp_snapshot
from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member, user_workspaces


def resolve_ace_root_folder_id(workspace) -> str | None:
    """Return the Drive folder id of the workspace's ACE root folder.

    Each Workspace pins its own `drive_root_folder_id` (post-2026-04-27
    multi-tenancy). Returns None when no workspace is provided —
    callers treat that as "no workspace context" and return an empty
    list / 404 as appropriate.
    """
    if workspace is None:
        return None
    return workspace.drive_root_folder_id or None


def resolve_workspace(request):
    """Return ``(workspace, error_response)``. Reads workspace identity from
    (in priority order): URL kwarg ``workspace_slug``, request header
    ``X-ACE-Workspace``, or — as a backward-compat fallback for the
    legacy ``/api/opps/`` paths — the user's first workspace.

    Membership is enforced; non-members get a 404 (not 403) so workspace
    existence isn't leaked.
    """
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )

    slug = request.headers.get("X-ACE-Workspace") or None

    if slug:
        try:
            ws = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist:
            return None, Response(
                error_response("workspace not found", code="not-found"),
                status=404,
            )
        if not is_member(request.user, ws):
            return None, Response(
                error_response("workspace not found", code="not-found"),
                status=404,
            )
        return ws, None

    # Legacy fallback: bare /api/opps/ paths default to the user's most-recent
    # workspace. Phase B retires this once the frontend always provides
    # `workspace_slug` in the URL.
    ws = user_workspaces(request.user).first()
    if ws is None:
        return None, Response(
            error_response(
                "no workspace — create or join one first",
                code="no-workspace",
            ),
            status=403,
        )
    return ws, None


def require_drive(request):
    """Return ``(workspace, drive_client, error_response)``. On error, the
    first two are None.

    The returned client is wrapped in :class:`CachedDriveClient` so repeated
    list/content reads within the cache TTL hit Redis instead of Drive.
    Pass ``?force=1`` on the request to bypass the cache for a hard refresh
    (writes still populate the cache so subsequent reads get the fresh data).
    """
    ws, err = resolve_workspace(request)
    if err is not None:
        return None, None, err
    try:
        inner = get_drive_client(workspace=ws)
    except ServiceAccountNotFound as exc:
        return ws, None, Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )
    bypass = request.GET.get("force") == "1"
    return ws, CachedDriveClient(inner, bypass=bypass), None


def overlay_workspace_display_name(manifest, slug: str, workspace=None) -> None:
    """Layer OppWorkspace DB metadata (display_name + tags) onto the
    Drive-derived manifest in place.

    Since 2026-04-20, display_name lives only on the OppWorkspace DB row —
    no longer in a Drive state.yaml (that ownership moved to the ACE plugin
    per docs/plans/2026-04-20-drop-multi-run-simplify.md). Tags are also
    DB-only (free-form grouping across sibling opps). Views that render
    opp metadata layer both over the Drive snapshot at the boundary so the
    sync module stays pure.

    The `workspace` arg scopes the lookup to the active Workspace —
    multiple Workspaces can have an opp with the same slug, so a global
    .get(slug=...) is no longer well-defined.
    """
    try:
        q = OppWorkspace.objects.only("display_name", "tags")
        if workspace is not None:
            q = q.filter(workspace=workspace)
        opp_ws = q.get(slug=slug)
    except OppWorkspace.DoesNotExist:
        return
    if opp_ws.display_name and opp_ws.display_name != slug:
        manifest.display_name = opp_ws.display_name
    manifest.tags = list(opp_ws.tags or [])


def snapshot_etag(snap, *, pairs=None) -> str:
    """Compute the ETag for an OppSnapshot.

    Always hashes the serialized JSON payload so the ETag is stable
    across the cold-load and cached-hit paths. The ``pairs`` argument
    is accepted for forward-compat with any caller that supplies it, but
    is not used — json-body hashing is simpler and produces a
    consistent ETag regardless of which Drive modified_time values the
    client happened to see.
    """
    body = json.dumps(serialize_opp_snapshot(snap), sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
