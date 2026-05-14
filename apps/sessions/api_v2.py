"""Django Ninja v2 router for the sessions surface."""
from __future__ import annotations

import logging
from typing import Annotated

from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api_v2.auth import session_auth
from apps.api_v2.deps import resolve_workspace_for_member
from apps.api_v2.errors import TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError
from apps.api_v2.pagination import Page, paginate

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


@router.get("", response=Page[SessionListOut], summary="List sessions in workspace")
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


@router.get("/{slug}", summary="Session detail")
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
# 2.2.9 — GET /{slug}/turn-state — cheap polling endpoint
# ---------------------------------------------------------------------------


def get_turn_state(workspace, slug: str) -> dict | None:
    """Return turn-state dict or None if the session doesn't exist.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.common.backend_selector import _cli_instance
    from apps.sessions.consumers import turn_task_for_slug
    from apps.sessions.models import Message, Session

    session = Session.objects.filter(slug=slug, workspace=workspace).first()
    if session is None:
        return None

    task = turn_task_for_slug(slug)
    running = task is not None and not task.done()

    cli_state = None
    if _cli_instance is not None:
        cli_state = _cli_instance.session_state(slug)

    last = (
        Message.objects.filter(session=session)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return {
        "running": running,
        "last_message_at": last,
        "cli": cli_state,
    }


@router.get("/{slug}/turn-state", summary="Turn state (polling)")
def session_turn_state(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from .schemas import TurnStateOut

    workspace = resolve_workspace_for_member(request, workspace_slug)
    state = get_turn_state(workspace, slug)
    if state is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    payload = TurnStateOut.model_validate(state).model_dump(mode="json")
    return JsonResponse(payload)


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


# ---------------------------------------------------------------------------
# 2.2.12 — GET /{slug}/share — share-token list
# ---------------------------------------------------------------------------


def list_share_tokens(workspace, slug: str) -> list[dict] | None:
    """Return active share tokens for a session or None if not found.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.sessions.models import Session, ShareToken

    session = Session.objects.filter(slug=slug, workspace=workspace).first()
    if session is None:
        return None
    tokens = (
        ShareToken.objects.filter(session=session, revoked_at__isnull=True)
        .order_by("-created_at")
    )
    return [
        {"token": t.token, "created_at": t.created_at, "revoked_at": t.revoked_at, "url": None}
        for t in tokens
    ]


@router.get("/{slug}/share", summary="List share tokens")
def list_share(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from .schemas import ShareTokenOut

    workspace = resolve_workspace_for_member(request, workspace_slug)
    tokens = list_share_tokens(workspace, slug)
    if tokens is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    payload = [ShareTokenOut.model_validate(t).model_dump(mode="json") for t in tokens]
    return JsonResponse(payload, safe=False)
