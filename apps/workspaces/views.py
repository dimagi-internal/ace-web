"""REST endpoints for the workspaces API.

Phase A surface:
- GET /api/workspaces/         — list my workspaces
- GET /api/workspaces/<slug>/  — detail (members + my role)
- GET /api/workspaces/drive-config/ — service-account email for "share with this"

Phase B surface (this module):
- POST   /api/workspaces/                              — create
- POST   /api/workspaces/<slug>/verify-drive-access/   — Drive ping
- GET    /api/workspaces/<slug>/members/               — list members
- POST   /api/workspaces/<slug>/members/               — invite by email
- PATCH  /api/workspaces/<slug>/members/<user_id>/     — change role
- DELETE /api/workspaces/<slug>/members/<user_id>/     — remove member
- GET    /api/invites/<token>/                         — preview an invite
- POST   /api/invites/<token>/accept/                  — accept invite
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.workspaces.models import (
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)
from apps.workspaces.permissions import is_member, role_for, user_workspaces
from apps.workspaces.serializers import (
    WorkspaceDetailSerializer,
    WorkspaceMemberSerializer,
    WorkspaceSummarySerializer,
)

User = get_user_model()

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
INVITE_TTL = timedelta(days=14)


# ────────────────────────────── helpers ──────────────────────────────


def _require_member(request, slug):
    """Return (workspace, error_response). 404 for non-members so
    workspace existence isn't leaked."""
    try:
        ws = Workspace.objects.get(slug=slug)
    except Workspace.DoesNotExist:
        return None, Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    if not is_member(request.user, ws):
        return None, Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    return ws, None


def _require_owner(request, slug):
    """Return (workspace, error_response). Non-owners get 403; non-members
    get 404 (existence-leak-safe)."""
    ws, err = _require_member(request, slug)
    if err is not None:
        return ws, err
    if role_for(request.user, ws) != "owner":
        return ws, Response(
            error_response("owner required", code="forbidden"), status=403
        )
    return ws, None


def _get_drive_client_safely():
    """Return a drive client or None on configuration error."""
    from apps.opps.drive_client import get_drive_client
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    try:
        return get_drive_client(), None
    except ServiceAccountNotFound as exc:
        return None, str(exc)


def _parse_folder_id(raw: str) -> str:
    """Accept either a bare folder id or a Google Drive URL and return
    the folder id. URLs of the form ``https://drive.google.com/drive/folders/<id>``
    or ``...?id=<id>`` are both handled.
    """
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


# ──────────────────────────────  views  ──────────────────────────────


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def workspace_collection(request):
    if request.method == "POST":
        return _create_workspace(request)
    qs = user_workspaces(request.user)
    serializer = WorkspaceSummarySerializer(qs, many=True, context={"request": request})
    return Response(success_response(serializer.data))


def _create_workspace(request):
    body = request.data if isinstance(request.data, dict) else {}
    display_name = (body.get("display_name") or "").strip()
    raw_folder = body.get("drive_root_folder_id") or ""
    folder_id = _parse_folder_id(raw_folder)
    requested_slug = (body.get("slug") or "").strip().lower()

    if not display_name:
        return Response(
            error_response("display_name is required", code="validation-error"),
            status=400,
        )
    if not folder_id:
        return Response(
            error_response("drive_root_folder_id is required", code="validation-error"),
            status=400,
        )

    # Slug derivation: explicit, or derived from display_name. Append -2/-3/...
    # on collision (matches the opp_creator pattern).
    slug = requested_slug or _slugify(display_name)
    if not SLUG_RE.match(slug):
        return Response(
            error_response(
                "slug must be lowercase alphanumeric + hyphens, 2-64 chars",
                code="validation-error",
            ),
            status=400,
        )

    base_slug = slug
    suffix = 1
    while Workspace.objects.filter(slug=slug).exists():
        suffix += 1
        slug = f"{base_slug}-{suffix}"
        if suffix > 99:
            return Response(
                error_response("could not find a free slug", code="slug-exhausted"),
                status=409,
            )

    # Folder uniqueness: a Drive folder belongs to at most one Workspace
    # (the CLI's implicit-by-folder linkage depends on this).
    existing = Workspace.objects.filter(drive_root_folder_id=folder_id).first()
    if existing is not None:
        return Response(
            error_response(
                f"this Drive folder is already connected to workspace "
                f"{existing.slug!r}; ask its owner to invite you",
                code="folder-already-claimed",
            ),
            status=409,
        )

    try:
        with transaction.atomic():
            ws = Workspace.objects.create(
                slug=slug,
                display_name=display_name,
                drive_root_folder_id=folder_id,
                created_by=request.user,
            )
            WorkspaceMembership.objects.create(
                workspace=ws, user=request.user, role="owner",
            )
    except IntegrityError as exc:
        return Response(
            error_response(str(exc), code="integrity-error"), status=409
        )

    serializer = WorkspaceDetailSerializer(ws, context={"request": request})
    return Response(success_response(serializer.data), status=201)


def _slugify(name: str) -> str:
    """Lowercase, replace non-alnum with hyphens, collapse runs."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:64] or "workspace"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_detail(request, slug):
    ws, err = _require_member(request, slug)
    if err is not None:
        return err
    serializer = WorkspaceDetailSerializer(ws, context={"request": request})
    return Response(success_response(serializer.data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def drive_config(request):
    """Returns the service-account email used by all workspaces."""
    from apps.service_accounts.models import ServiceAccount

    try:
        sa = ServiceAccount.objects.get(name="ace-drive", is_active=True)
    except ServiceAccount.DoesNotExist:
        return Response(
            error_response(
                "ace-drive service account not configured",
                code="drive-not-configured",
            ),
            status=500,
        )
    try:
        info = json.loads(sa.credential_json)
        email = info.get("client_email", "")
    except Exception:  # noqa: BLE001
        email = ""
    return Response(success_response({"service_account_email": email}))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_drive_access(request, slug):
    """Verify the SA can read the workspace's Drive folder.

    Returns up to 5 sample child names on success — gives the user
    confidence that the share worked. Distinguishes 'not shared'
    from 'not found' from 'transient' so the UI can hint usefully.
    """
    ws, err = _require_member(request, slug)
    if err is not None:
        return err
    client, err_msg = _get_drive_client_safely()
    if err_msg:
        return Response(
            error_response(err_msg, code="drive-not-configured"), status=500
        )
    try:
        children = client.list_files(ws.drive_root_folder_id)
    except Exception as exc:  # noqa: BLE001
        # Distinguish errors. The Google Drive API returns 404 for
        # both "doesn't exist" and "not shared with caller". We can't
        # tell them apart from the client side, so return a single
        # ambiguous error code.
        return Response(
            error_response(
                f"Drive can't access that folder: {exc}. Check that the "
                "folder ID is correct and that you've shared it with "
                "the service account as Editor.",
                code="drive-access-denied",
            ),
            status=400,
        )
    return Response(success_response({
        "ok": True,
        "sample_files": [
            {"name": c.name, "mime_type": c.mime_type}
            for c in children[:5]
        ],
        "total_visible": len(children),
    }))


# ──── members & invites ────


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def member_collection(request, slug):
    if request.method == "POST":
        return _invite_member(request, slug)
    ws, err = _require_member(request, slug)
    if err is not None:
        return err
    members = ws.memberships.select_related("user").all()
    return Response(success_response(
        WorkspaceMemberSerializer(members, many=True).data
    ))


def _invite_member(request, slug):
    ws, err = _require_owner(request, slug)
    if err is not None:
        return err
    body = request.data if isinstance(request.data, dict) else {}
    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "editor").strip().lower()
    if not email or "@" not in email:
        return Response(
            error_response("valid email is required", code="validation-error"),
            status=400,
        )
    if role not in {"owner", "editor", "viewer"}:
        return Response(
            error_response(
                "role must be owner, editor, or viewer",
                code="validation-error",
            ),
            status=400,
        )

    # If this email already has membership, surface that.
    existing_member = ws.memberships.filter(user__email__iexact=email).first()
    if existing_member is not None:
        return Response(
            error_response(
                f"{email} is already a {existing_member.role} of this workspace",
                code="already-member",
            ),
            status=409,
        )

    invite = WorkspaceInvite.objects.create(
        workspace=ws,
        email=email,
        role=role,
        invited_by=request.user,
        expires_at=timezone.now() + INVITE_TTL,
    )
    return Response(success_response({
        "token": invite.token,
        "email": invite.email,
        "role": invite.role,
        "expires_at": invite.expires_at.isoformat(),
        # Caller can copy-paste this URL into an email; Phase B doesn't
        # send mail automatically (that's a Phase C nice-to-have).
        "accept_url": f"/welcome?invite={invite.token}",
    }), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def member_detail(request, slug, user_id):
    ws, err = _require_owner(request, slug)
    if err is not None:
        return err
    try:
        membership = ws.memberships.select_related("user").get(user_id=user_id)
    except WorkspaceMembership.DoesNotExist:
        return Response(
            error_response("member not found", code="not-found"), status=404
        )

    if request.method == "DELETE":
        if membership.role == "owner":
            other_owners = ws.memberships.filter(role="owner").exclude(
                user_id=user_id,
            ).count()
            if other_owners == 0:
                return Response(
                    error_response(
                        "cannot remove the last owner; promote another member first",
                        code="last-owner",
                    ),
                    status=400,
                )
        membership.delete()
        return Response(status=204)

    # PATCH: update role
    body = request.data if isinstance(request.data, dict) else {}
    new_role = (body.get("role") or "").strip().lower()
    if new_role not in {"owner", "editor", "viewer"}:
        return Response(
            error_response(
                "role must be owner, editor, or viewer",
                code="validation-error",
            ),
            status=400,
        )
    if membership.role == "owner" and new_role != "owner":
        other_owners = ws.memberships.filter(role="owner").exclude(
            user_id=user_id,
        ).count()
        if other_owners == 0:
            return Response(
                error_response(
                    "cannot demote the last owner; promote another member first",
                    code="last-owner",
                ),
                status=400,
            )
    membership.role = new_role
    membership.save(update_fields=["role"])
    return Response(success_response(
        WorkspaceMemberSerializer(membership).data
    ))


# ──── invite preview + accept ────


@api_view(["GET"])
@permission_classes([AllowAny])
def invite_preview(request, token):
    """Public preview of an invite (workspace name + role + inviter)
    so the user can decide whether to accept. No auth required —
    you might land on the URL before signing in."""
    try:
        invite = WorkspaceInvite.objects.select_related(
            "workspace", "invited_by",
        ).get(token=token)
    except WorkspaceInvite.DoesNotExist:
        return Response(
            error_response("invite not found", code="not-found"), status=404
        )
    if not invite.is_pending():
        return Response(
            error_response(
                "this invite is no longer valid",
                code="invite-not-pending",
            ),
            status=410,
        )
    return Response(success_response({
        "workspace_slug": invite.workspace.slug,
        "workspace_display_name": invite.workspace.display_name,
        "role": invite.role,
        "invited_by_email": invite.invited_by.email if invite.invited_by_id else "",
        "email": invite.email,
        "expires_at": invite.expires_at.isoformat(),
    }))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_activity(request, slug):
    """Read-through to apps.service_accounts.AccessLog filtered by this
    workspace's `context.workspace_slug`. Owner-only because the log
    can include other members' actions."""
    ws, err = _require_owner(request, slug)
    if err is not None:
        return err
    from apps.service_accounts.models import AccessLog
    rows = (
        AccessLog.objects
        .filter(context__workspace_slug=ws.slug)
        .order_by("-created_at")[:100]
    )
    return Response(success_response([
        {
            "action": r.action,
            "subject": r.subject,
            "scopes_used": r.scopes_used,
            "context": r.context,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_reviews(request, slug):
    """GET /api/workspaces/<slug>/pending-reviews — every gate-pending
    step across the workspace's opps, with the gate-brief inlined.

    Powers the workspace-level Reviews queue page. Iterates the opp
    list, fetches each opp's snapshot, and emits one row per
    gate-pending step. The Drive cache makes this cheap on warm runs.
    """
    from django.core.cache import cache as _cache

    ws, err = _require_member(request, slug)
    if err is not None:
        return err

    if not ws.drive_root_folder_id:
        return Response(success_response({"pending": []}))

    force = request.GET.get("force") == "1"
    cache_key = f"pending-reviews:v1:{ws.slug}"
    if not force:
        hit = _cache.get(cache_key)
        if hit is not None:
            return Response(success_response(hit))

    # Local imports to avoid circular dependencies.
    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import list_opp_runs, load_opp
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    try:
        client = CachedDriveClient(get_drive_client(workspace=ws))
    except ServiceAccountNotFound as exc:
        return Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )

    pending: list[dict] = []
    try:
        ace_root_children = client.list_files(ws.drive_root_folder_id)
    except Exception as exc:  # noqa: BLE001
        return Response(
            error_response(
                f"couldn't list ACE root: {exc}", code="drive-unavailable",
            ),
            status=503,
        )

    for child in ace_root_children:
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        # Only walk folders that look like opps.
        opp_children = client.list_files(child.id)
        names = {f.name for f in opp_children}
        if not (
            "idea.md" in names or "state.yaml" in names
            or "run_state.yaml" in names or "opp.yaml" in names
            or "runs" in names
        ):
            continue

        try:
            runs = list_opp_runs(
                client, ace_root_folder_id=ws.drive_root_folder_id,
                opp_slug=child.name, opp_children=opp_children,
            )
        except Exception:  # noqa: BLE001
            continue
        if not runs:
            continue
        # Most-recent run only — older runs' gates aren't actionable.
        try:
            snap = load_opp(
                client, ace_root_folder_id=ws.drive_root_folder_id,
                opp_slug=child.name, run_id=runs[0].run_id,
            )
        except FileNotFoundError:
            continue

        for step in snap.current_run.steps:
            if step.step.status != "gate-pending":
                continue
            latest_gate = step.gates[-1] if step.gates else None
            pending.append({
                "opp_slug": child.name,
                "opp_display_name": snap.opp.display_name or child.name,
                "run_id": runs[0].run_id,
                "skill_name": step.step.skill_name,
                "phase": step.step.phase,
                "ordinal": step.step.ordinal,
                "score": step.judge.score if step.judge else None,
                "gate_decided_by": latest_gate.decided_by if latest_gate else None,
                "gate_ts": latest_gate.ts if latest_gate else None,
                "gate_note": latest_gate.note if latest_gate else None,
            })

    payload = {"pending": pending}
    _cache.set(
        cache_key, payload,
        timeout=getattr(settings, "OPPS_DRIVE_CACHE_SECONDS", 30),
    )
    return Response(success_response(payload))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_workspace(request, slug):
    """Self-remove from a workspace. Last owners can't leave; they must
    promote another member to owner first."""
    ws, err = _require_member(request, slug)
    if err is not None:
        return err
    membership = ws.memberships.filter(user=request.user).first()
    if membership is None:
        return Response(
            error_response("not a member", code="not-found"), status=404
        )
    if membership.role == "owner":
        other_owners = ws.memberships.filter(role="owner").exclude(
            user=request.user,
        ).count()
        if other_owners == 0:
            return Response(
                error_response(
                    "you are the last owner; promote someone else first",
                    code="last-owner",
                ),
                status=400,
            )
    membership.delete()
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invite_accept(request, token):
    with transaction.atomic():
        try:
            invite = WorkspaceInvite.objects.select_for_update().select_related(
                "workspace",
            ).get(token=token)
        except WorkspaceInvite.DoesNotExist:
            return Response(
                error_response("invite not found", code="not-found"), status=404
            )
        if not invite.is_pending():
            return Response(
                error_response(
                    "this invite is no longer valid",
                    code="invite-not-pending",
                ),
                status=410,
            )

        # Email match is advisory but enforced — prevents a user from
        # accepting an invite addressed to someone else.
        if invite.email.lower() != (request.user.email or "").lower():
            return Response(
                error_response(
                    "this invite is for a different email address",
                    code="email-mismatch",
                ),
                status=403,
            )

        membership, created = WorkspaceMembership.objects.get_or_create(
            workspace=invite.workspace,
            user=request.user,
            defaults={
                "role": invite.role,
                "invited_by": invite.invited_by,
            },
        )
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])

    return Response(success_response({
        "workspace_slug": invite.workspace.slug,
        "role": membership.role,
        "newly_joined": created,
    }))
