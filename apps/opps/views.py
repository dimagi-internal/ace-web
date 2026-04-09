"""REST API views for the ACE opportunity Workbench."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import success_response


@api_view(["GET"])
@permission_classes([AllowAny])  # Scaffold-only; later views in this file use RequireDriveToken.
def health(request):
    """Scaffold sanity check. Used by tests in Task 1."""
    return Response(success_response({"status": "ok", "module": "opps"}))
