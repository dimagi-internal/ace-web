"""Site admin: who holds `User.is_staff`.

Staff-only. A non-staff caller gets 404, the workspace convention of not
leaking that the surface exists. Session and Bearer auth resolve to the same
`request.user` (`apps.api.auth`), so both go through the same check.
`is_superuser` is deliberately not editable here.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from ninja import Path, Query, Router

from apps.api.auth import session_auth
from apps.api.errors import TYPE_CONFLICT, TYPE_NOT_FOUND, ProblemError
from apps.auth.models import User

from .models import StaffChange
from .schemas import (
    SiteAdminMembershipOut,
    SiteAdminUserOut,
    SiteAdminUsersOut,
    StaffChangeOut,
    StaffPatchIn,
)
from .services import record_staff_change

router = Router(auth=session_auth, tags=["site-admin"])

RECENT_CHANGES = 25


def _require_staff(request: HttpRequest) -> User:
    user = request.user
    if not getattr(user, "is_staff", False):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return user  # type: ignore[return-value]


def _user_out(user: User) -> SiteAdminUserOut:
    memberships = sorted(user.workspace_memberships.all(), key=lambda m: m.workspace.slug)
    return SiteAdminUserOut(
        id=user.id, email=user.email, display_name=user.display_name,
        is_staff=user.is_staff, is_active=user.is_active,
        created_at=user.created_at, last_login=user.last_login,
        workspaces=[
            SiteAdminMembershipOut(
                workspace_slug=m.workspace.slug, workspace_name=m.workspace.display_name,
                role=m.role,
            ) for m in memberships
        ],
    )


def _users_qs():
    return User.objects.prefetch_related("workspace_memberships__workspace")


@router.get("/users", response=SiteAdminUsersOut, operation_id="site_admin_list_users")
def list_users(request: HttpRequest, q: Query[str] = "") -> SiteAdminUsersOut:
    _require_staff(request)
    qs = _users_qs().order_by("-is_staff", "email")
    q = q.strip()
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(display_name__icontains=q))
    changes = StaffChange.objects.all()[:RECENT_CHANGES]
    return SiteAdminUsersOut(
        users=[_user_out(u) for u in qs],
        recent_changes=[StaffChangeOut.model_validate(c) for c in changes],
    )


@router.patch("/users/{user_id}", response=SiteAdminUserOut, operation_id="site_admin_patch_user")
def patch_user(request: HttpRequest, user_id: Path[int], payload: StaffPatchIn) -> SiteAdminUserOut:
    actor = _require_staff(request)
    with transaction.atomic():
        # Lock the staff rows so two concurrent demotions can't each see the
        # other as "the remaining admin" and leave nobody (no-op on SQLite).
        list(User.objects.select_for_update().filter(Q(is_staff=True) | Q(pk=user_id)))
        target = User.objects.filter(pk=user_id).first()
        if target is None:
            raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
        if payload.is_staff != target.is_staff:
            if not payload.is_staff:
                if target.pk == actor.pk:
                    raise ProblemError(
                        409, "Cannot remove your own site admin", type_=TYPE_CONFLICT,
                        detail="You can't remove your own site admin. "
                               "Ask another site admin to do it.",
                    )
                if not User.objects.filter(is_staff=True).exclude(pk=target.pk).exists():
                    raise ProblemError(
                        409, "Cannot remove the last site admin", type_=TYPE_CONFLICT,
                        detail="This is the last site admin; removing them would leave "
                               "nobody able to manage site admins.",
                    )
            record_staff_change(actor=actor, target=target, new_is_staff=payload.is_staff)
    return _user_out(_users_qs().get(pk=target.pk))
