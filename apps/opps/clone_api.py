"""`/api/w/{workspace_slug}/opps/{slug}/runs/{run_id}/clone[s]` — copy a run
into another workspace, and list where a run has been cloned.

The caller must OWN both workspaces: a clone moves a run's content into a
workspace whose members will see it, and it is the first step before its
assets are rebuilt in that workspace's tenancy. A target the caller is not a
member of is a 404 (workspace existence is never leaked).

**The POST blocks for the whole Drive copy** (~150 ms per file), like the
fork endpoint. Spec: docs/specs/2026-09-28-clone-and-release-design.md § C.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member
from apps.api.errors import (
    TYPE_CONFLICT,
    TYPE_FORBIDDEN,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    ProblemError,
)
from apps.common.schemas import StrictModel

from .drive_client import get_drive_client
from .run_cloner import CloneError, clone_run

router = Router(auth=session_auth, tags=["opps"])


class RunCloneIn(StrictModel):
    to_workspace: str


class RunCloneOut(StrictModel):
    id: int
    source_workspace: str
    target_workspace: str
    opp_slug: str
    run_id: str
    status: str
    files_copied: int
    error: str
    created_by: str | None
    created_at: dt.datetime


def _out(c) -> dict:
    return RunCloneOut.model_validate(
        {
            "id": c.pk,
            "source_workspace": c.source_workspace_id,
            "target_workspace": c.target_workspace_id,
            "opp_slug": c.opp_slug,
            "run_id": c.run_id,
            "status": c.status,
            "files_copied": c.files_copied,
            "error": c.error,
            "created_by": c.created_by.email if c.created_by else None,
            "created_at": c.created_at,
        }
    ).model_dump(mode="json")


def _require_owner(request: HttpRequest, workspace) -> None:
    from apps.workspaces.permissions import role_for

    if role_for(request.user, workspace) != "owner":
        raise ProblemError(403, "Owner required", type_=TYPE_FORBIDDEN)


_CLONE_ERROR_STATUS = {
    "source-not-found": 404,
    "source-run-not-found": 404,
    "already-cloned": 409,
    "same-workspace": 400,
}


@router.post(
    "/{slug}/runs/{run_id}/clone",
    response={201: RunCloneOut},
    summary="Clone a run into another workspace (blocking)",
)
def clone_run_endpoint(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
    body: RunCloneIn,
) -> HttpResponse:
    from apps.opps import snapshot_cache
    from apps.workspaces.models import RunClone

    source = resolve_workspace_for_member(request, workspace_slug)
    target = resolve_workspace_for_member(request, body.to_workspace)
    _require_owner(request, source)
    _require_owner(request, target)

    try:
        drive = get_drive_client(workspace=target)
    except Exception as exc:  # noqa: BLE001 — surfaced as a problem, not a 500
        raise ProblemError(404, "Drive not configured", type_=TYPE_NOT_FOUND,
                           detail=str(exc)) from exc
    try:
        result = clone_run(drive=drive, source=source, target=target, opp_slug=slug,
                           run_id=run_id, owner=request.user)
    except CloneError as exc:
        status = _CLONE_ERROR_STATUS.get(exc.code, 400)
        type_ = {404: TYPE_NOT_FOUND, 409: TYPE_CONFLICT}.get(status, TYPE_VALIDATION)
        raise ProblemError(status, str(exc), type_=type_, detail=exc.code) from exc

    # The new opp folder is a new child of the target root — a listing the
    # Drive Changes feed does not reliably report (see
    # drive-changes-api-parent-folder-blind-spot.md).
    snapshot_cache.clear_workspace(target.pk)
    record = RunClone.objects.select_related("created_by").get(pk=result.clone_id)
    return JsonResponse(_out(record), status=201)


@router.get(
    "/{slug}/runs/{run_id}/clones",
    response={200: list[RunCloneOut]},
    summary="Where this run has been cloned",
)
def list_run_clones(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
) -> HttpResponse:
    from apps.workspaces.models import RunClone

    source = resolve_workspace_for_member(request, workspace_slug)
    rows = (
        RunClone.objects.filter(source_workspace=source, opp_slug=slug, run_id=run_id)
        .select_related("created_by")
        .order_by("-created_at")
    )
    return JsonResponse([_out(c) for c in rows], safe=False)
