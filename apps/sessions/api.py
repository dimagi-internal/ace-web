"""Django Ninja v2 router for the sessions surface."""
from __future__ import annotations

import logging
from typing import Annotated

from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member
from apps.api.errors import TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError
from apps.api.pagination import Page, paginate

from .schemas import SessionCreateIn, SessionListOut, SessionPatchIn

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["sessions"])


# ---------------------------------------------------------------------------
# Helpers — session ORM loading and shape mapping
# ---------------------------------------------------------------------------


def _session_to_list_dict(session) -> dict:
    """Map a Session ORM instance to a SessionListOut-compatible dict.

    Respects the ``first_user_plaintext`` and ``opp_display_name_annotated``
    annotations added by the list queryset.
    """
    from apps.sessions.serializers import _truncate_preview

    # preview
    annotated_preview = getattr(session, "first_user_plaintext", None)
    if annotated_preview is not None:
        preview = _truncate_preview(annotated_preview)
    else:
        msg = (
            session.messages.filter(role="user")
            .order_by("turn_index")
            .values_list("plaintext", flat=True)
            .first()
        )
        preview = _truncate_preview(msg or "")

    # opp display name
    annotated_opp = getattr(session, "opp_display_name_annotated", None)
    if annotated_opp is not None:
        opp_display_name = annotated_opp or ""
    elif session.opp_slug:
        from apps.opps.models import OppWorkspace
        opp_display_name = (
            OppWorkspace.objects.filter(
                workspace_id=session.workspace_id,
                slug=session.opp_slug,
            )
            .values_list("display_name", flat=True)
            .first()
            or ""
        )
    else:
        opp_display_name = ""

    # opp_step_skill display
    opp_step_skill_display = ""
    if session.opp_step_skill:
        try:
            from django.conf import settings as _s

            from apps.system.reader import skill_display_names
            lookup = skill_display_names(getattr(_s, "ACE_PLUGIN_PATH", "") or "")
            opp_step_skill_display = lookup.get(session.opp_step_skill, session.opp_step_skill)
        except Exception:  # noqa: BLE001
            opp_step_skill_display = session.opp_step_skill

    return {
        "slug": session.slug,
        "title": session.title,
        "status": session.status,
        "backend_kind": session.backend_kind,
        "source": session.source,
        "cli_session_id": session.cli_session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "message_count": session.messages.count(),
        "preview": preview,
        "opp_slug": session.opp_slug or "",
        "opp_run_id": session.opp_run_id or "",
        "opp_step_skill": session.opp_step_skill or "",
        "opp_display_name": opp_display_name,
        "opp_step_skill_display": opp_step_skill_display,
    }


def _session_to_detail_dict(session) -> dict:
    """Map a Session to a SessionOut-compatible dict (includes messages)."""
    base = _session_to_list_dict(session)
    msgs = [
        {
            "id": m.id,
            "turn_index": m.turn_index,
            "role": m.role,
            "content": m.content,
            "plaintext": m.plaintext,
            "status": m.status,
            "error_detail": m.error_detail,
            "started_at": m.started_at,
            "completed_at": m.completed_at,
            "created_at": m.created_at,
        }
        for m in session.messages.all().order_by("turn_index")
    ]
    base["messages"] = msgs
    return base


def _load_session_in_workspace(slug: str, workspace) -> object | None:
    """Load a session filtered by workspace.

    Returns None when the session doesn't exist or doesn't belong to this
    workspace. Workspace membership is already verified upstream by
    resolve_workspace_for_member.
    """
    from apps.sessions.models import Session

    return (
        Session.objects.select_related("workspace")
        .filter(slug=slug, workspace=workspace)
        .first()
    )


# ---------------------------------------------------------------------------
# 2.2.2 — GET / — list sessions (paginated, workspace-scoped)
# ---------------------------------------------------------------------------


def list_sessions_in_workspace(
    workspace, *, opp_slug: str | None, archived: bool
) -> list[dict]:
    """Return session dicts for this workspace, optionally filtered.

    The monkeypatch target in contract tests is this module-level function.
    """
    from django.db.models import OuterRef, Subquery

    from apps.opps.models import OppWorkspace
    from apps.sessions.models import Message, Session

    qs = Session.objects.filter(workspace=workspace)
    if opp_slug:
        qs = qs.filter(opp_slug=opp_slug)
    if archived:
        qs = qs.filter(status="archived")
    else:
        qs = qs.exclude(status="archived")

    first_user_msg = (
        Message.objects.filter(session=OuterRef("pk"), role="user")
        .order_by("turn_index")
        .values("plaintext")[:1]
    )
    matching_opp = (
        OppWorkspace.objects.filter(
            workspace_id=OuterRef("workspace_id"),
            slug=OuterRef("opp_slug"),
        )
        .values("display_name")[:1]
    )
    qs = qs.annotate(
        first_user_plaintext=Subquery(first_user_msg),
        opp_display_name_annotated=Subquery(matching_opp),
    ).order_by("-updated_at")

    return [_session_to_list_dict(s) for s in qs]


@router.get(
    "",
    response=Page[SessionListOut],
    summary="List sessions in workspace",
    openapi_extra={"x-mcp-expose": True},
)
def list_sessions(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 50,
    opp_slug: str | None = None,
    archived: bool = False,
) -> Page[SessionListOut]:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    sessions = list_sessions_in_workspace(workspace, opp_slug=opp_slug, archived=archived)
    return paginate(
        [SessionListOut.model_validate(s) for s in sessions],
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Interrupted runs — resume candidates (deterministic deploy-kill detection)
# Registered BEFORE /{slug} so the literal path isn't matched as a slug.
# ---------------------------------------------------------------------------


def interrupted_runs_in_workspace(workspace) -> list[dict]:
    """Runs killed mid-flight (e.g. ECS task replaced by a deploy): a
    non-terminal assistant turn with a stale/absent driver heartbeat. The
    monkeypatch target in contract tests is this module-level function."""
    from apps.sessions.models import Session

    out = []
    for s in Session.interrupted().filter(workspace=workspace).order_by("-updated_at"):
        out.append({
            "slug": s.slug,
            "opp_slug": s.opp_slug or None,
            "opp_run_id": s.opp_run_id or None,
            "title": s.title,
            "driver_heartbeat_at": (
                s.driver_heartbeat_at.isoformat() if s.driver_heartbeat_at else None
            ),
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })
    return out


@router.get("/interrupted", summary="Runs interrupted mid-flight (resume candidates)")
def interrupted_runs(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    workspace = resolve_workspace_for_member(request, workspace_slug)
    return JsonResponse({"items": interrupted_runs_in_workspace(workspace)})


def resume_session_run(session) -> dict | None:
    """Re-launch an interrupted ACE opp run on its EXISTING session + run_id by
    appending a fresh ``/ace:run <slug>/<run_id>`` resume turn (the orchestrator
    picks up from run_state.yaml where it died). Returns
    {assistant_message_id, command, slug} or None if the session isn't a
    resumable ACE opp run (ad-hoc chats have no run_state to resume from).

    The caller spawns the driver for assistant_message_id. Monkeypatch target
    in contract tests."""
    from django.db import models, transaction
    from django.utils import timezone

    from apps.sessions.models import Message

    if not session.opp_run_id or not session.opp_slug:
        return None  # ACE opp runs only
    command = f"/ace:run {session.opp_slug}/{session.opp_run_id} --no-evals"
    with transaction.atomic():
        # Retire the dead turn so the resume scope stops flagging it — BOTH kill
        # modes: a hard-killed turn left streaming/pending, AND a gracefully
        # cancelled turn already marked error:'cancelled (partial:...)'. Rewriting
        # the detail off the 'cancelled' prefix is what stops resumable_after_deploy
        # re-matching it on the next sweep (no double-resume).
        Message.objects.filter(
            models.Q(status__in=("streaming", "pending"))
            | models.Q(status="error", error_detail__startswith="cancelled"),
            session=session,
            role="assistant",
        ).update(
            status="error",
            error_detail="superseded by auto-resume",
            completed_at=timezone.now(),
        )
        next_idx = (
            Message.objects.filter(session=session).aggregate(m=models.Max("turn_index"))["m"] or 0
        ) + 1
        Message.objects.create(
            session=session, turn_index=next_idx, role="user", sender_user=session.owner,
            content={"text": command}, plaintext=command, status="complete",
            completed_at=timezone.now(),
        )
        assistant_msg = Message.objects.create(
            session=session, turn_index=next_idx + 1, role="assistant",
            content={"text": ""}, plaintext="", status="pending",
        )
        # Stamp the beacon fresh NOW (before the driver's first heartbeat ~30s
        # out) so a concurrent detector / second post-deploy hook can't see the
        # just-created pending turn as interrupted and double-resume it.
        from apps.sessions.models import Session as _S
        _S.objects.filter(pk=session.pk).update(driver_heartbeat_at=timezone.now())
    return {"assistant_message_id": assistant_msg.id, "command": command, "slug": session.slug}


@router.post(
    "/resume-interrupted",
    summary="Resume all interrupted ACE opp runs (post-deploy self-heal)",
)
def resume_interrupted(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
) -> HttpResponse:
    """Bulk-resume every interrupted ACE opp run in the workspace. Intended for
    the post-deploy hook: after a rollout drains the tasks driving live runs,
    this relaunches them from run_state.yaml. Single serial call → no
    double-spawn race."""
    from django.http import JsonResponse

    from apps.sessions.models import Session
    from apps.sessions.turn_driver import start_turn_subprocess

    workspace = resolve_workspace_for_member(request, workspace_slug)
    resumed = []
    # ACE opp runs only (have an opp_run_id → resumable from run_state.yaml).
    # resumable_after_deploy (NOT interrupted) so the sweep catches the common
    # graceful-SIGTERM kill mode (turn marked error:'cancelled (partial:...)'),
    # not just hard kills — and is age-bounded so ancient corpses aren't revived.
    candidates = (
        Session.resumable_after_deploy().filter(workspace=workspace).exclude(opp_run_id="")
    )
    for s in candidates:
        res = resume_session_run(s)
        if res is not None:
            start_turn_subprocess(res["assistant_message_id"])
            resumed.append({"slug": s.slug, "opp_run_id": s.opp_run_id})
    return JsonResponse({"resumed": resumed, "count": len(resumed)})


@router.post("/{slug}/resume", summary="Resume one interrupted run")
def resume_run(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.sessions.turn_driver import start_turn_subprocess

    workspace = resolve_workspace_for_member(request, workspace_slug)
    session = _load_session_in_workspace(slug, workspace)
    if session is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    res = resume_session_run(session)
    if res is None:
        raise ProblemError(
            422, "Not a resumable ACE opp run (no opp_run_id)", type_=TYPE_VALIDATION,
        )
    start_turn_subprocess(res["assistant_message_id"])
    return JsonResponse(res, status=202)


# ---------------------------------------------------------------------------
# 2.2.3 — POST / — create session
# ---------------------------------------------------------------------------


def create_session_in_workspace(workspace, user, body: SessionCreateIn) -> dict:
    """Create a session in the given workspace and return a SessionListOut dict.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.sessions.models import Session

    session = Session.create_with_owner(
        owner=user,
        title=body.title,
        workspace=workspace,
    )
    return _session_to_list_dict(session)


@router.post("", summary="Create session")
def create_session(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    body: SessionCreateIn,
) -> HttpResponse:
    from django.http import JsonResponse

    workspace = resolve_workspace_for_member(request, workspace_slug)
    session = create_session_in_workspace(workspace, request.user, body)
    payload = SessionListOut.model_validate(session).model_dump(mode="json")
    return JsonResponse(payload, status=201)


# ---------------------------------------------------------------------------
# 2.2.4 — GET /{slug} — session detail
# ---------------------------------------------------------------------------


def get_session_detail(workspace, slug: str) -> dict | None:
    """Return a SessionOut-compatible dict or None if not found.

    The monkeypatch target in contract tests is this module-level function.
    """
    session = _load_session_in_workspace(slug, workspace)
    if session is None:
        return None
    return _session_to_detail_dict(session)


@router.get(
    "/{slug}",
    summary="Session detail",
    openapi_extra={"x-mcp-expose": True},
)
def get_session(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from .schemas import SessionOut

    workspace = resolve_workspace_for_member(request, workspace_slug)
    detail = get_session_detail(workspace, slug)
    if detail is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    payload = SessionOut.model_validate(detail).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# 2.2.5 — PATCH /{slug} — update session (title, status)
# ---------------------------------------------------------------------------


def patch_session_in_workspace(workspace, slug: str, updates: dict) -> dict | None:
    """Apply allowed field updates to a session. Returns updated dict or None.

    Only ``title`` and ``status`` may be mutated.
    The monkeypatch target in contract tests is this module-level function.
    """
    session = _load_session_in_workspace(slug, workspace)
    if session is None:
        return None
    for k, v in updates.items():
        setattr(session, k, v)
    if updates:
        session.save(update_fields=list(updates.keys()) + ["updated_at"])
    return _session_to_list_dict(session)


@router.patch("/{slug}", summary="Update session")
def update_session(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: SessionPatchIn,
) -> HttpResponse:
    from django.http import JsonResponse

    workspace = resolve_workspace_for_member(request, workspace_slug)
    updates = body.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] not in {"active", "archived"}:
        raise ProblemError(400, "Invalid status value", type_=TYPE_VALIDATION)
    result = patch_session_in_workspace(workspace, slug, updates)
    if result is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    payload = SessionListOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# 2.2.6 — DELETE /{slug} — delete session
# ---------------------------------------------------------------------------


def delete_session_in_workspace(workspace, slug: str) -> bool:
    """Delete session; returns True if found+deleted, False if not found.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.sessions.models import Session

    qs = Session.objects.filter(slug=slug, workspace=workspace)
    count, _ = qs.delete()
    return count > 0


@router.delete("/{slug}", summary="Delete session")
def delete_session(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    deleted = delete_session_in_workspace(workspace, slug)
    if not deleted:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# 2.2.7 — GET /{slug}/messages — message history (paginated)
# ---------------------------------------------------------------------------


def list_messages_for_session(workspace, slug: str) -> list[dict] | None:
    """Return message dicts or None if the session doesn't exist.

    The monkeypatch target in contract tests is this module-level function.
    """
    session = _load_session_in_workspace(slug, workspace)
    if session is None:
        return None
    return [
        {
            "id": m.id,
            "turn_index": m.turn_index,
            "role": m.role,
            "content": m.content,
            "plaintext": m.plaintext,
            "status": m.status,
            "error_detail": m.error_detail,
            "started_at": m.started_at,
            "completed_at": m.completed_at,
            "created_at": m.created_at,
        }
        for m in session.messages.all().order_by("turn_index")
    ]


@router.get("/{slug}/messages", summary="Message history")
def list_messages(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 200,
) -> HttpResponse:
    from django.http import JsonResponse

    from .schemas import MessageOut

    workspace = resolve_workspace_for_member(request, workspace_slug)
    messages = list_messages_for_session(workspace, slug)
    if messages is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    page = paginate(
        [MessageOut.model_validate(m) for m in messages],
        offset=offset,
        limit=limit,
    )
    return JsonResponse(page.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# 2.2.8 — GET /{slug}/participants — participant list
# ---------------------------------------------------------------------------


def list_participants_for_session(workspace, slug: str) -> list[dict] | None:
    """Return participant dicts or None if the session doesn't exist.

    The monkeypatch target in contract tests is this module-level function.
    """
    session = _load_session_in_workspace(slug, workspace)
    if session is None:
        return None
    return [
        {
            "user_id": p.user_id,
            "email": p.user.email,
            "display_name": p.user.display_name,
            "role": p.role,
            "joined_at": p.joined_at,
            "last_seen_at": p.last_seen_at,
        }
        for p in session.participants.select_related("user").all()
    ]


@router.get("/{slug}/participants", summary="Participant list")
def list_participants(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from .schemas import ParticipantOut

    workspace = resolve_workspace_for_member(request, workspace_slug)
    participants = list_participants_for_session(workspace, slug)
    if participants is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    payload = [ParticipantOut.model_validate(p).model_dump(mode="json") for p in participants]
    return JsonResponse(payload, safe=False)


# ---------------------------------------------------------------------------
# 2.2.10 — GET /{slug}/cost — cost breakdown rollup
# ---------------------------------------------------------------------------


def get_cost_breakdown(workspace, slug: str) -> dict | None:
    """Return cost breakdown dict or None if not found.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.sessions.models import Session

    session = Session.objects.filter(slug=slug, workspace=workspace).first()
    if session is None:
        return None
    breakdown = session.cost_breakdown or {}
    if not breakdown:
        return {"schema_version": 0, "totals": None, "phases": []}
    return breakdown


@router.get("/{slug}/cost", summary="Cost breakdown")
def session_cost(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from .schemas import CostBreakdownOut

    workspace = resolve_workspace_for_member(request, workspace_slug)
    breakdown = get_cost_breakdown(workspace, slug)
    if breakdown is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    payload = CostBreakdownOut.model_validate(breakdown).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# 2.2.11 — GET /{slug}/structure — recursive structure tree
# ---------------------------------------------------------------------------


def get_structure_tree(
    workspace, slug: str, if_none_match: str | None = None
) -> tuple[dict | None, str | None, bool]:
    """Return (tree_dict, etag, not_modified) for a session.

    Returns (None, None, False) if the session doesn't exist.
    Returns (empty_dict, None, False) if no raw JSONL is available.
    Returns ({}, etag, True) on 304 hit.
    Returns (tree, etag, False) on cache miss.

    The monkeypatch target in contract tests is this module-level function.
    """
    import gzip as _gzip
    import logging as _logging

    from apps.ingest.parser import parse_session_bytes
    from apps.ingest.structure_aggregator import SCHEMA_VERSION, aggregate
    from apps.sessions.models import Session

    _log = _logging.getLogger(__name__)

    session = Session.objects.filter(slug=slug, workspace=workspace).first()
    if session is None:
        return None, None, False

    upload = session.ingest_records.order_by("-created_at").first()
    if upload is None or not upload.raw_jsonl_gz:
        return (
            {
                "schema_version": 0,
                "session": None,
                "phases": [],
                "unavailable_reason": "no-raw-jsonl",
            },
            None,
            False,
        )

    etag = f'"v{SCHEMA_VERSION}:{upload.content_sha256}"' if upload.content_sha256 else None
    if etag and if_none_match == etag:
        return {}, etag, True

    try:
        _parsed, events = parse_session_bytes(_gzip.decompress(bytes(upload.raw_jsonl_gz)))
        tree = aggregate(events)
    except Exception:
        _log.exception("structure aggregation failed for session %s", slug)
        return (
            {
                "schema_version": 0,
                "session": None,
                "phases": [],
                "unavailable_reason": "parse-failed",
            },
            None,
            False,
        )

    return tree, etag, False


@router.get("/{slug}/structure", summary="Session structure tree")
def session_structure(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    workspace = resolve_workspace_for_member(request, workspace_slug)
    if_none_match = request.headers.get("If-None-Match")
    tree, etag, not_modified = get_structure_tree(workspace, slug, if_none_match=if_none_match)
    if tree is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    if not_modified:
        return HttpResponse(status=304)
    response = JsonResponse(tree)
    if etag:
        response["ETag"] = etag
    return response


