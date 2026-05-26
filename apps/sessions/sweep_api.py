"""Cross-workspace session sweep API for /ace:sweep ace-web.

The workspace-scoped sessions router at /w/{workspace_slug}/sessions can't
serve a sweep that spans every workspace the caller belongs to. This router
sits at /sessions (no workspace_slug) and returns / deletes sessions across
all workspaces where the calling user is at least Editor.

Deletes are atomic per row and CASCADE through SessionParticipant, Message,
Draft, ShareToken, and IngestUpload via the FK on_delete settings already
declared on those models. There is no soft-delete path — this is the sweep.
"""
from __future__ import annotations

import logging

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Router

from apps.api.auth import session_auth

from .sweep_schemas import FailedDeleteOut, SweepDeleteIn, SweepListOut, SweepSessionRow

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["sessions"])


# Roles that can list and delete sessions in their workspace via the sweep API.
# Viewers are excluded so a Viewer membership doesn't expose other members'
# session metadata or grant delete rights.
_WRITE_ROLES = ("owner", "editor")


def _build_session_row(session, message_count: int, upload_count: int) -> SweepSessionRow:
    return SweepSessionRow(
        id=session.id,
        slug=session.slug,
        title=session.title or "",
        source=session.source,
        status=session.status,
        opp_slug=session.opp_slug or "",
        opp_run_id=session.opp_run_id or "",
        workspace_slug=session.workspace.slug if session.workspace else "",
        message_count=message_count,
        upload_count=upload_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _writable_workspace_slugs(user) -> list[str]:
    """Return slugs of workspaces where `user` is Owner or Editor."""
    from apps.workspaces.models import WorkspaceMembership

    return list(
        WorkspaceMembership.objects.filter(user=user, role__in=_WRITE_ROLES)
        .values_list("workspace__slug", flat=True)
    )


@router.get(
    "",
    response=SweepListOut,
    summary="List sessions across workspaces (sweep)",
    description=(
        "Returns every Session in workspaces where the calling user is "
        "Owner or Editor. Used by `/ace:sweep ace-web`. Not paginated — "
        "the rows are summary-sized and a single request is the expected "
        "shape for the sweep skill."
    ),
)
def list_sweep_sessions(request: HttpRequest) -> SweepListOut:
    from django.db.models import Count, Sum

    from apps.sessions.models import Session

    writable_slugs = _writable_workspace_slugs(request.user)
    if not writable_slugs:
        return SweepListOut(sessions=[], total_raw_bytes=0)

    qs = (
        Session.objects.filter(workspace__slug__in=writable_slugs)
        .select_related("workspace")
        .annotate(
            _message_count=Count("messages", distinct=True),
            _upload_count=Count("ingest_records", distinct=True),
            _upload_bytes=Sum("ingest_records__raw_bytes"),
        )
        .order_by("workspace__slug", "-updated_at")
    )

    rows: list[SweepSessionRow] = []
    total_bytes = 0
    for session in qs:
        rows.append(
            _build_session_row(
                session,
                message_count=session._message_count,
                upload_count=session._upload_count,
            )
        )
        total_bytes += int(session._upload_bytes or 0)

    return SweepListOut(sessions=rows, total_raw_bytes=total_bytes)


@router.post(
    "/delete",
    response=dict,
    summary="Bulk-delete sessions (sweep)",
    description=(
        "Delete every Session id in the body that the calling user has "
        "Owner or Editor access to. Sessions in workspaces the user can't "
        "write to are reported as 'forbidden' in `failed[]` rather than "
        "deleted. DELETE-with-body is awkward in some HTTP clients, so the "
        "atom is POST /sessions/sweep/delete."
    ),
)
def bulk_delete_sweep_sessions(request: HttpRequest, body: SweepDeleteIn) -> HttpResponse:
    from apps.sessions.models import Session

    writable_slugs = set(_writable_workspace_slugs(request.user))
    session_ids = list(dict.fromkeys(body.session_ids))  # dedupe, preserve order

    if not session_ids:
        return JsonResponse({"deleted": 0, "failed": []})

    sessions_by_id = {
        s.id: s
        for s in Session.objects.filter(id__in=session_ids).select_related("workspace")
    }

    deleted = 0
    failed: list[FailedDeleteOut] = []
    for sid in session_ids:
        session = sessions_by_id.get(sid)
        if session is None:
            failed.append(FailedDeleteOut(session_id=sid, reason="not_found"))
            continue
        ws_slug = session.workspace.slug if session.workspace else ""
        if ws_slug not in writable_slugs:
            failed.append(FailedDeleteOut(session_id=sid, reason="forbidden"))
            continue
        try:
            session.delete()
            deleted += 1
        except DatabaseError as exc:
            log.exception("sweep delete failed for session id=%s", sid)
            failed.append(FailedDeleteOut(session_id=sid, reason=f"db_error: {exc}"))

    payload = {
        "deleted": deleted,
        "failed": [f.model_dump(mode="json") for f in failed],
    }
    return JsonResponse(payload)
