"""Django Ninja v2 router for the workspaces surface."""
from __future__ import annotations

import re
from typing import Annotated

from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api_v2.auth import session_auth
from apps.api_v2.errors import (
    TYPE_CONFLICT,
    TYPE_FORBIDDEN,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    ProblemError,
)

from .schemas import (
    WorkspaceCreateIn,
    WorkspaceInviteIn,
    WorkspaceInviteOut,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspacePatchIn,
)

router = Router(auth=session_auth, tags=["workspaces"])

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:64] or "workspace"


def _parse_folder_id(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    return raw


def _workspace_to_dict(ws, requesting_user) -> dict:
    from apps.workspaces.permissions import role_for

    return {
        "slug": ws.slug,
        "name": ws.display_name,
        "drive_root_folder_id": ws.drive_root_folder_id,
        "role": role_for(requesting_user, ws) or "viewer",
        "member_count": ws.memberships.count(),
        "created_at": ws.created_at,
        "updated_at": ws.updated_at,
    }


def _membership_to_dict(membership) -> dict:
    return {
        "id": membership.id,
        "user": {
            "id": membership.user_id,
            "email": membership.user.email,
            "display_name": membership.user.display_name,
        },
        "role": membership.role,
        "joined_at": membership.joined_at,
    }


def _require_owner_role(workspace, user) -> None:
    from apps.workspaces.permissions import role_for

    if role_for(user, workspace) != "owner":
        raise ProblemError(403, "Owner required", type_=TYPE_FORBIDDEN)


# ---------------------------------------------------------------------------
# GET /workspaces — list my workspaces
# ---------------------------------------------------------------------------


def list_my_workspaces(user) -> list[dict]:
    from apps.workspaces.permissions import user_workspaces

    workspaces = user_workspaces(user)
    return [_workspace_to_dict(ws, user) for ws in workspaces]


@router.get("", response={200: list[WorkspaceOut]}, summary="List my workspaces")
def list_workspaces(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    workspaces = list_my_workspaces(request.user)
    payload = [WorkspaceOut.model_validate(ws).model_dump(mode="json") for ws in workspaces]
    return JsonResponse(payload, safe=False)


# ---------------------------------------------------------------------------
# POST /workspaces — create workspace
# ---------------------------------------------------------------------------


def create_workspace(user, body: WorkspaceCreateIn) -> dict:
    from django.db import IntegrityError, transaction

    from apps.workspaces.models import Workspace, WorkspaceMembership

    folder_id = _parse_folder_id(body.drive_root_folder_id)
    if not folder_id:
        raise ProblemError(400, "Invalid drive_root_folder_id", type_=TYPE_VALIDATION)

    slug = body.slug or _slugify(body.name)
    if not SLUG_RE.match(slug):
        raise ProblemError(
            400,
            "slug must be lowercase alphanumeric + hyphens",
            type_=TYPE_VALIDATION,
        )

    # Slug dedup
    base_slug = slug
    suffix = 1
    while Workspace.objects.filter(slug=slug).exists():
        suffix += 1
        slug = f"{base_slug}-{suffix}"
        if suffix > 99:
            raise ProblemError(409, "Could not find a free slug", type_=TYPE_CONFLICT)

    # Folder uniqueness
    existing = Workspace.objects.filter(drive_root_folder_id=folder_id).first()
    if existing is not None:
        raise ProblemError(
            409,
            f"Drive folder already claimed by workspace {existing.slug!r}",
            type_=TYPE_CONFLICT,
        )

    try:
        with transaction.atomic():
            ws = Workspace.objects.create(
                slug=slug,
                display_name=body.name,
                drive_root_folder_id=folder_id,
                created_by=user,
            )
            WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    except IntegrityError as exc:
        raise ProblemError(409, str(exc), type_=TYPE_CONFLICT) from exc

    return _workspace_to_dict(ws, user)


@router.post("", summary="Create workspace")
def post_workspace(request: HttpRequest, body: WorkspaceCreateIn) -> HttpResponse:
    from django.http import JsonResponse

    workspace = create_workspace(request.user, body)
    payload = WorkspaceOut.model_validate(workspace).model_dump(mode="json")
    return JsonResponse(payload, status=201)


# ---------------------------------------------------------------------------
# GET /workspaces/{slug} — workspace detail
# ---------------------------------------------------------------------------


def get_workspace_detail(user, slug: str) -> dict | None:
    from apps.api_v2.deps import resolve_workspace_for_member

    class FakeRequest:
        pass

    from django.http import HttpRequest as DjangoRequest

    req = DjangoRequest()
    req.user = user

    ws = resolve_workspace_for_member(req, slug)
    return _workspace_to_dict(ws, user)


@router.get("/{slug}", response={200: WorkspaceOut}, summary="Workspace detail")
def workspace_detail(
    request: HttpRequest,
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    payload = WorkspaceOut.model_validate(_workspace_to_dict(ws, request.user)).model_dump(
        mode="json"
    )
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# PATCH /workspaces/{slug} — update workspace (owner only)
# ---------------------------------------------------------------------------


def patch_workspace(user, slug: str, updates: dict) -> dict:
    from django.http import HttpRequest as DjangoRequest

    from apps.api_v2.deps import resolve_workspace_for_member

    req = DjangoRequest()
    req.user = user
    ws = resolve_workspace_for_member(req, slug)
    _require_owner_role(ws, user)
    changed = []
    if "name" in updates and updates["name"]:
        ws.display_name = updates["name"]
        changed.append("display_name")
    if "drive_root_folder_id" in updates and updates["drive_root_folder_id"]:
        folder_id = _parse_folder_id(updates["drive_root_folder_id"])
        if folder_id:
            ws.drive_root_folder_id = folder_id
            changed.append("drive_root_folder_id")
    if changed:
        ws.save(update_fields=changed + ["updated_at"])
    return _workspace_to_dict(ws, user)


@router.patch("/{slug}", response={200: WorkspaceOut}, summary="Update workspace")
def update_workspace(
    request: HttpRequest,
    slug: Annotated[str, Path()],
    body: WorkspacePatchIn,
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    _require_owner_role(ws, request.user)
    updates = body.model_dump(exclude_unset=True)
    changed = []
    if "name" in updates and updates["name"]:
        ws.display_name = updates["name"]
        changed.append("display_name")
    if "drive_root_folder_id" in updates and updates["drive_root_folder_id"]:
        folder_id = _parse_folder_id(updates["drive_root_folder_id"])
        if folder_id:
            ws.drive_root_folder_id = folder_id
            changed.append("drive_root_folder_id")
    if changed:
        ws.save(update_fields=changed + ["updated_at"])
    payload = WorkspaceOut.model_validate(_workspace_to_dict(ws, request.user)).model_dump(
        mode="json"
    )
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /workspaces/{slug}/members — list members
# ---------------------------------------------------------------------------


def list_members_in_workspace(workspace) -> list[dict]:
    members = workspace.memberships.select_related("user").all()
    return [_membership_to_dict(m) for m in members]


@router.get(
    "/{slug}/members",
    response={200: list[WorkspaceMemberOut]},
    summary="List workspace members",
)
def list_members(
    request: HttpRequest,
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    members = list_members_in_workspace(ws)
    payload = [WorkspaceMemberOut.model_validate(m).model_dump(mode="json") for m in members]
    return JsonResponse(payload, safe=False)


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/members/invite — invite by email
# ---------------------------------------------------------------------------


def invite_member_to_workspace(workspace, inviter, email: str, role: str) -> dict:
    from datetime import timedelta

    from django.utils import timezone

    from apps.workspaces.models import WorkspaceInvite

    _require_owner_role(workspace, inviter)
    if not email or "@" not in email:
        raise ProblemError(400, "Valid email is required", type_=TYPE_VALIDATION)
    if role not in {"owner", "editor", "viewer"}:
        raise ProblemError(
            400, "role must be owner, editor, or viewer", type_=TYPE_VALIDATION
        )
    existing = workspace.memberships.filter(user__email__iexact=email).first()
    if existing is not None:
        raise ProblemError(
            409,
            f"{email} is already a {existing.role} of this workspace",
            type_=TYPE_CONFLICT,
        )
    invite = WorkspaceInvite.objects.create(
        workspace=workspace,
        email=email,
        role=role,
        invited_by=inviter,
        expires_at=timezone.now() + timedelta(days=14),
    )
    return {
        "token": invite.token,
        "email": invite.email,
        "role": invite.role,
        "accepted": False,
        "accepted_at": None,
        "created_at": invite.created_at,
        "updated_at": invite.created_at,
    }


@router.post(
    "/{slug}/members/invite",
    response={201: WorkspaceInviteOut},
    summary="Invite a member",
)
def invite_member(
    request: HttpRequest,
    slug: Annotated[str, Path()],
    body: WorkspaceInviteIn,
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    result = invite_member_to_workspace(ws, request.user, body.email, body.role)
    payload = WorkspaceInviteOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=201)


# ---------------------------------------------------------------------------
# DELETE /workspaces/{slug}/members/{user_id} — remove member
# ---------------------------------------------------------------------------


def remove_member_from_workspace(workspace, requester, user_id: int) -> None:
    from apps.workspaces.models import WorkspaceMembership

    _require_owner_role(workspace, requester)
    try:
        membership = workspace.memberships.select_related("user").get(user_id=user_id)
    except WorkspaceMembership.DoesNotExist as exc:
        raise ProblemError(404, "Member not found", type_=TYPE_NOT_FOUND) from exc

    if membership.role == "owner":
        other_owners = workspace.memberships.filter(role="owner").exclude(user_id=user_id).count()
        if other_owners == 0:
            raise ProblemError(
                400,
                "Cannot remove the last owner; promote another member first",
                type_=TYPE_VALIDATION,
            )
    membership.delete()


@router.delete("/{slug}/members/{user_id}", summary="Remove member")
def remove_member(
    request: HttpRequest,
    slug: Annotated[str, Path()],
    user_id: Annotated[int, Path()],
) -> HttpResponse:
    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    remove_member_from_workspace(ws, request.user, user_id)
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/leave — leave workspace
# ---------------------------------------------------------------------------


def leave_workspace_op(workspace, user) -> None:

    membership = workspace.memberships.filter(user=user).first()
    if membership is None:
        raise ProblemError(404, "Not a member", type_=TYPE_NOT_FOUND)
    if membership.role == "owner":
        other_owners = (
            workspace.memberships.filter(role="owner").exclude(user=user).count()
        )
        if other_owners == 0:
            raise ProblemError(
                400,
                "You are the last owner; promote someone else first",
                type_=TYPE_VALIDATION,
            )
    membership.delete()


@router.post("/{slug}/leave", summary="Leave workspace")
def leave_workspace(
    request: HttpRequest,
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    leave_workspace_op(ws, request.user)
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# GET /workspaces/{slug}/activity — workspace audit log (owner only)
# ---------------------------------------------------------------------------


def get_workspace_activity(workspace, user) -> list[dict]:
    _require_owner_role(workspace, user)
    from apps.service_accounts.models import AccessLog

    rows = (
        AccessLog.objects.filter(context__workspace_slug=workspace.slug)
        .order_by("-created_at")[:100]
    )
    return [
        {
            "action": r.action,
            "subject": r.subject,
            "scopes_used": r.scopes_used,
            "context": r.context,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{slug}/activity", summary="Workspace audit log (owner only)")
def workspace_activity(
    request: HttpRequest,
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    rows = get_workspace_activity(ws, request.user)
    return JsonResponse({"items": rows, "total": len(rows)})


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/drive-config/verify — verify Drive access
# ---------------------------------------------------------------------------


def verify_drive_access_for_workspace(workspace) -> dict:
    from apps.opps.drive_client import get_drive_client
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    try:
        client = get_drive_client()
    except ServiceAccountNotFound as exc:
        raise ProblemError(500, str(exc), type_=TYPE_VALIDATION) from exc

    try:
        children = client.list_files(workspace.drive_root_folder_id)
    except Exception as exc:  # noqa: BLE001
        raise ProblemError(
            400,
            f"Drive can't access that folder: {exc}",
            type_=TYPE_VALIDATION,
        ) from exc

    return {
        "ok": True,
        "sample_files": [
            {"name": c.name, "mime_type": c.mime_type} for c in children[:5]
        ],
        "total_visible": len(children),
    }


@router.post("/{slug}/drive-config/verify", summary="Verify Drive access")
def verify_drive_access(
    request: HttpRequest,
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    from apps.api_v2.deps import resolve_workspace_for_member

    ws = resolve_workspace_for_member(request, slug)
    result = verify_drive_access_for_workspace(ws)
    return JsonResponse(result)
