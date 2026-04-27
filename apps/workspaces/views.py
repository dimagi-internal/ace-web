"""REST endpoints for the workspaces API.

Phase A surface:
- GET /api/workspaces/         — list my workspaces
- GET /api/workspaces/<slug>/  — detail (members + my role)
- GET /api/workspaces/drive-config/ — service-account email for "share with this"

POST/PATCH/DELETE for workspaces, members, invites are Phase B.
"""
import json

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member, user_workspaces
from apps.workspaces.serializers import (
    WorkspaceDetailSerializer,
    WorkspaceSummarySerializer,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_list(request):
    qs = user_workspaces(request.user)
    serializer = WorkspaceSummarySerializer(qs, many=True, context={"request": request})
    return Response(success_response(serializer.data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_detail(request, slug):
    try:
        ws = Workspace.objects.get(slug=slug)
    except Workspace.DoesNotExist:
        return Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    if not is_member(request.user, ws):
        # 404 (not 403) so we don't leak workspace existence.
        return Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    serializer = WorkspaceDetailSerializer(ws, context={"request": request})
    return Response(success_response(serializer.data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def drive_config(request):
    """Returns the service-account email used by all workspaces.

    The user copy-pastes this into Google Drive's Share dialog when
    setting up a workspace. The SA email is a public identifier extracted
    from the SA credential JSON; it's not a secret.
    """
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
