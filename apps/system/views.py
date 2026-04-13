"""REST API views for the ACE System Overview."""
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.system.reader import load_agent_detail, load_skill_detail, load_system_overview
from apps.system.version import check_version


def _plugin_path() -> str:
    return getattr(settings, "ACE_PLUGIN_PATH", "")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def overview(request):
    """Return the full system snapshot: skills, agents, artifacts, version."""
    path = _plugin_path()
    data = load_system_overview(path)
    version = check_version(path)
    data["plugin_version"] = version["plugin_version"]
    data["remote_version"] = version["remote_version"]
    data["update_available"] = version["update_available"]
    return Response(success_response(data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def skill_detail(request, name: str):
    """Return a single skill with full markdown body."""
    detail = load_skill_detail(_plugin_path(), name)
    if detail is None:
        return Response(
            error_response(f"skill {name!r} not found", code="skill-not-found"),
            status=404,
        )
    return Response(success_response(detail))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_detail(request, name: str):
    """Return a single agent with full markdown body."""
    detail = load_agent_detail(_plugin_path(), name)
    if detail is None:
        return Response(
            error_response(f"agent {name!r} not found", code="agent-not-found"),
            status=404,
        )
    return Response(success_response(detail))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def version(request):
    """Lightweight version-only check."""
    data = check_version(_plugin_path())
    return Response(success_response(data))
