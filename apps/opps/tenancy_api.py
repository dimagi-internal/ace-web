"""`/api/w/{workspace_slug}/opps/{slug}/tenancy` — read and set an opp's tenancy.

GET is for any member (it is what ACE fetches when it binds a session to an
opp); PATCH is owner-only and audited, because tenancy decides where ACE may
write. See `apps/opps/tenancy.py` for the model.
"""
from __future__ import annotations

from typing import Annotated

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Path, Router
from pydantic import ValidationError

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member
from apps.api.errors import TYPE_FORBIDDEN, TYPE_VALIDATION, ProblemError
from apps.common.schemas import StrictModel

from . import tenancy as tenancy_mod
from .tenancy import Tenancy

router = Router(auth=session_auth, tags=["opps"])


class OppTenancyOut(StrictModel):
    slug: str
    tenancy: Tenancy
    # The workspace Drive root the opp lives under (derived, not stored).
    drive_root_folder_id: str
    # "opp" = the opp's own record; "workspace-default" = the opp has no
    # OppWorkspace row yet, so this is what it would start with.
    source: str


def _out(workspace, slug: str, tenancy: dict, source: str) -> HttpResponse:
    payload = OppTenancyOut.model_validate(
        {
            "slug": slug,
            "tenancy": tenancy,
            "drive_root_folder_id": workspace.drive_root_folder_id,
            "source": source,
        }
    ).model_dump(mode="json", exclude_none=True)
    return JsonResponse(payload)


@router.get(
    "/{slug}/tenancy",
    response={200: OppTenancyOut},
    summary="Get opp tenancy",
)
def get_opp_tenancy(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    from .models import OppWorkspace

    workspace = resolve_workspace_for_member(request, workspace_slug)
    row = OppWorkspace.objects.filter(workspace=workspace, slug=slug).only("tenancy").first()
    if row is None:
        return _out(workspace, slug, tenancy_mod.clean(workspace.default_tenancy),
                    "workspace-default")
    return _out(workspace, slug, tenancy_mod.clean(row.tenancy), "opp")


@router.patch("/{slug}/tenancy", response={200: OppTenancyOut}, summary="Set opp tenancy")
def patch_opp_tenancy(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: Tenancy,
) -> HttpResponse:
    from django.db import transaction

    from apps.workspaces.permissions import role_for

    from .models import OppWorkspace

    workspace = resolve_workspace_for_member(request, workspace_slug)
    if role_for(request.user, workspace) != "owner":
        raise ProblemError(403, "Owner required", type_=TYPE_FORBIDDEN)

    with transaction.atomic():
        row, _ = OppWorkspace.objects.select_for_update().get_or_create(
            workspace=workspace,
            slug=slug,
            defaults={
                "display_name": slug,
                "created_by": request.user,
                "tenancy": tenancy_mod.clean(workspace.default_tenancy),
            },
        )
        before = tenancy_mod.clean(row.tenancy)
        try:
            after = tenancy_mod.merge(before, body.model_dump(exclude_unset=True))
        except ValidationError as exc:
            raise ProblemError(400, "Invalid tenancy", type_=TYPE_VALIDATION,
                               detail=str(exc)) from exc
        if after != row.tenancy:
            row.tenancy = after
            row.save(update_fields=["tenancy", "updated_at"])
        tenancy_mod.record_change(
            workspace=workspace, opp_slug=slug, user=request.user, before=before, after=after,
        )
    return _out(workspace, slug, after, "opp")
