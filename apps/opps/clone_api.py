"""`/api/w/{workspace_slug}/opps/{slug}/runs/{run_id}/clone[s]` — copy a run
into another workspace, and list where a run has been cloned.

The caller must OWN both workspaces: a clone moves a run's content into a
workspace whose members will see it, and it is the first step before its
assets are rebuilt in that workspace's tenancy. A target the caller is not a
member of is a 404 (workspace existence is never leaked).

**The POST validates, records the clone and returns 202; the Drive copy runs
on a background thread.** It is one Drive call per file — the first real clone
(347 files) took ~14 min, and the in-request version 504'd at the load
balancer at 10 min (ace-web#823). Callers poll ``GET …/clones`` until the
record is ``done`` or ``error``. Spec:
docs/specs/2026-09-28-clone-and-release-design.md § C.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
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
from .run_cloner import CloneError, start_clone

log = logging.getLogger(__name__)

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
    # True once a release of the clone forwards THIS run's public summary to it.
    forwards_public_link: bool = False


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
            "forwards_public_link": _forwards(c),
        }
    ).model_dump(mode="json")


def _forwards(clone) -> bool:
    from apps.workspaces.models import RunRelease

    return RunRelease.objects.filter(forwards_from=clone).exists()


def _require_owner(request: HttpRequest, workspace) -> None:
    from apps.workspaces import permissions as perms

    if not perms.can(request.user, workspace, perms.OWN):
        raise ProblemError(403, "Owner required", type_=TYPE_FORBIDDEN)


_CLONE_ERROR_STATUS = {
    "source-not-found": 404,
    "source-run-not-found": 404,
    "already-cloned": 409,
    "same-workspace": 400,
}


def _run_in_background(fn) -> None:
    """Run ``fn`` on a daemon thread (tests replace this to run inline)."""

    def _runner():
        from django.db import close_old_connections

        try:
            fn()
        except Exception:  # noqa: BLE001 — the RunClone row already carries the error
            log.exception("background clone failed")
        finally:
            close_old_connections()

    threading.Thread(target=_runner, daemon=True).start()


@router.post(
    "/{slug}/runs/{run_id}/clone",
    response={202: RunCloneOut},
    summary="Clone a run into another workspace (async — poll …/clones)",
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
        record, copy = start_clone(drive=drive, source=source, target=target, opp_slug=slug,
                                   run_id=run_id, owner=request.user)
    except CloneError as exc:
        status = _CLONE_ERROR_STATUS.get(exc.code, 400)
        type_ = {404: TYPE_NOT_FOUND, 409: TYPE_CONFLICT}.get(status, TYPE_VALIDATION)
        raise ProblemError(status, str(exc), type_=type_, detail=exc.code) from exc

    target_pk = target.pk

    def _copy_then_refresh():
        copy()
        # The new opp folder is a new child of the target root — a listing the
        # Drive Changes feed does not reliably report (see
        # drive-changes-api-parent-folder-blind-spot.md).
        snapshot_cache.clear_workspace(target_pk)

    _run_in_background(_copy_then_refresh)
    record = RunClone.objects.select_related("created_by").get(pk=record.pk)
    return JsonResponse(_out(record), status=202)


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


# ---------------------------------------------------------------------------
# release — record reviewers, optionally forward the source's public summary
# ---------------------------------------------------------------------------


class RunReleaseIn(StrictModel):
    # Added to the recorded reviewers (lower-cased, de-duplicated); never removes.
    reviewers: list[str] = []
    # True: the source run of this run's clone forwards its public summary
    # here (307, no-store). False: stop forwarding. Absent: unchanged.
    forward_source: bool | None = None


class ReleaseSourceOut(StrictModel):
    workspace: str
    opp_slug: str
    run_id: str


class RunReleaseOut(StrictModel):
    workspace: str
    opp_slug: str
    run_id: str
    reviewers: list[str]
    forwards_from: ReleaseSourceOut | None
    released_by: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


def _release_out(r) -> dict:
    src = r.forwards_from
    return RunReleaseOut.model_validate(
        {
            "workspace": r.workspace_id,
            "opp_slug": r.opp_slug,
            "run_id": r.run_id,
            "reviewers": list(r.reviewers or []),
            "forwards_from": (
                {"workspace": src.source_workspace_id, "opp_slug": src.opp_slug,
                 "run_id": src.run_id}
                if src else None
            ),
            "released_by": r.released_by.email if r.released_by else None,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
    ).model_dump(mode="json")


def forwarded_summary_target(workspace_slug: str, opp_slug: str, run_id: str):
    """If this run's public summary is forwarded to a released clone, return
    ``(workspace, opp_slug, run_id)`` of the clone, else None."""
    from apps.workspaces.models import RunRelease

    r = (
        RunRelease.objects.filter(
            forwards_from__source_workspace_id=workspace_slug,
            forwards_from__opp_slug=opp_slug,
            forwards_from__run_id=run_id,
        )
        .order_by("-updated_at")
        .first()
    )
    return (r.workspace_id, r.opp_slug, r.run_id) if r else None


def _clear_public_summary_cache(workspace: str, opp_slug: str, run_id: str) -> None:
    from .api import _invalidate_summary_cache

    _invalidate_summary_cache(workspace, opp_slug, run_id)


@router.post(
    "/{slug}/runs/{run_id}/release",
    response={200: RunReleaseOut},
    summary="Record a release (reviewers, source-link forwarding)",
)
def release_run_endpoint(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
    body: RunReleaseIn,
) -> HttpResponse:
    from django.db import transaction

    from apps.workspaces.models import RunClone, RunRelease

    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_owner(request, workspace)

    with transaction.atomic():
        release, _ = RunRelease.objects.select_for_update().get_or_create(
            workspace=workspace, opp_slug=slug, run_id=run_id,
            defaults={"released_by": request.user},
        )
        reviewers = list(release.reviewers or [])
        for email in body.reviewers:
            e = email.strip().lower()
            if e and e not in reviewers:
                reviewers.append(e)
        release.reviewers = reviewers
        old_source = release.forwards_from
        if body.forward_source is True:
            clone = (
                RunClone.objects.filter(target_workspace=workspace, opp_slug=slug,
                                        run_id=run_id, status="done")
                .order_by("-created_at")
                .first()
            )
            if clone is None:
                raise ProblemError(
                    400, "This run is not a finished clone, so there is no source link "
                    "to forward", type_=TYPE_VALIDATION,
                )
            release.forwards_from = clone
        elif body.forward_source is False:
            release.forwards_from = None
        release.save()

    for src in {old_source, release.forwards_from} - {None}:
        _clear_public_summary_cache(src.source_workspace_id, src.opp_slug, src.run_id)
    release = RunRelease.objects.select_related("forwards_from", "released_by").get(
        pk=release.pk
    )
    return JsonResponse(_release_out(release))


@router.get(
    "/{slug}/runs/{run_id}/release",
    response={200: RunReleaseOut},
    summary="Get a run's release record",
)
def get_release(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
) -> HttpResponse:
    from apps.workspaces.models import RunRelease

    workspace = resolve_workspace_for_member(request, workspace_slug)
    release = (
        RunRelease.objects.select_related("forwards_from", "released_by")
        .filter(workspace=workspace, opp_slug=slug, run_id=run_id)
        .first()
    )
    if release is None:
        raise ProblemError(404, "Not released", type_=TYPE_NOT_FOUND)
    return JsonResponse(_release_out(release))
