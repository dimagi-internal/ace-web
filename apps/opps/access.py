"""Public workspace + Drive access helpers for the opps Workbench."""
from __future__ import annotations

import hashlib
import json

from apps.opps.models import OppWorkspace
from apps.opps.serializers import serialize_opp_snapshot


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
