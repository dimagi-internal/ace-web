"""Django Ninja v2 router for the activity feed surface."""
from __future__ import annotations

from typing import Annotated

from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member

from .schemas import ActivityFeedOut, WorkspaceActivityOut

router = Router(auth=session_auth, tags=["activity"])


# ---------------------------------------------------------------------------
# GET /w/{workspace_slug}/activity — workspace timeline feed
# ---------------------------------------------------------------------------


def get_activity_feed(
    workspace,
    user,
    request,
    opp_slug: str | None = None,
    event_types: str = "chat,verdict",
    limit: int = 200,
) -> dict:
    """Aggregate chat + verdict events for the workspace.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.activity.views import (
        MAX_LIMIT,
        _chat_events,
        _drive_events_cached,
    )
    from apps.opps.access import resolve_ace_root_folder_id

    requested_types = {t.strip() for t in event_types.split(",") if t.strip()}
    limit = max(1, min(MAX_LIMIT, limit))
    needs_drive = "verdict" in requested_types

    events: list[dict] = []

    if "chat" in requested_types:
        events.extend(_chat_events(request, workspace.slug, opp_slug))

    if needs_drive:
        # Build a fake request-like object that require_drive can use
        # (it reads X-ACE-Workspace header). We already resolved the workspace,
        # so just pass the Drive client resolution directly.
        try:
            from apps.opps.drive_client import get_drive_client
            from apps.service_accounts.exceptions import ServiceAccountNotFound

            client = get_drive_client()
            ace_folder_id = resolve_ace_root_folder_id(workspace)
            if ace_folder_id is not None:
                drive_events = _drive_events_cached(
                    workspace.slug,
                    ace_folder_id,
                    opp_slug,
                    client,
                )
                events.extend(drive_events)
        except (ServiceAccountNotFound, Exception):  # noqa: BLE001
            # Drive not configured or error — degrade gracefully
            pass

    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    events = events[:limit]
    return {"items": events, "total": len(events)}


@router.get(
    "",
    response={200: ActivityFeedOut},
    summary="Workspace activity feed",
)
def activity_feed(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    opp: str | None = None,
    type: str = "chat,verdict",
    limit: int = 200,
) -> HttpResponse:
    from django.http import JsonResponse

    workspace = resolve_workspace_for_member(request, workspace_slug)
    result = get_activity_feed(
        workspace=workspace,
        user=request.user,
        request=request,
        opp_slug=opp,
        event_types=type,
        limit=limit,
    )
    payload = ActivityFeedOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /w/{workspace_slug}/activity/runs — workspace "what's running" view
# ---------------------------------------------------------------------------


def get_workspace_activity(
    workspace,
    include_completed: bool = True,
    limit: int = 20,
) -> dict:
    """Aggregate one row per opp's most recent run, with source hints.

    Module-level so contract tests / Slack handlers can monkeypatch."""
    import datetime as dt

    from apps.activity.workspace_activity import list_workspace_activity

    rows = list_workspace_activity(
        workspace, include_completed=include_completed, limit=limit,
    )
    return {
        "rows": [r.to_dict() for r in rows],
        "server_now": dt.datetime.now(dt.UTC).isoformat().replace(
            "+00:00", "Z"
        ),
    }


@router.get(
    "/runs",
    response={200: WorkspaceActivityOut},
    summary="Workspace 'what's running' view",
)
def workspace_activity(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    include_completed: bool = True,
    limit: int = 20,
) -> HttpResponse:
    from django.http import JsonResponse

    workspace = resolve_workspace_for_member(request, workspace_slug)
    result = get_workspace_activity(
        workspace=workspace,
        include_completed=include_completed,
        limit=limit,
    )
    payload = WorkspaceActivityOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)
