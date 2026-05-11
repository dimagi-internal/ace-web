"""Public, unauthenticated per-run summary endpoint.

Spec: ``docs/specs/2026-05-04-opp-summary-page-design.md``.
Mounted at ``/api/opps/public/<workspace>/<slug>/runs/<run_id>/summary``.
Bypasses the standard auth+workspace gate (``AllowAny``) because the
endpoint is meant for stakeholder-facing share links — workspace is in
the URL path instead.
"""
from __future__ import annotations

from django.core.cache import cache as _cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import get_drive_client
from apps.opps.summary import build_summary_payload
from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.workspaces.models import Workspace

_SUMMARY_CACHE_TTL_SECONDS = 60


@api_view(["GET"])
@permission_classes([AllowAny])
def public_opp_summary(
    request, workspace: str, slug: str, run_id: str,
) -> Response:
    """Public, unauthenticated per-run summary payload.

    Resolves the workspace + opp + run from Drive, composes the JSON
    payload, and returns it. 404s on any miss with the same envelope so
    the API doesn't leak which segment was missing. Successful payloads
    are cached for ~60 seconds; 404s are not cached.
    """
    cache_key = f"opp-summary:v1:{workspace}:{slug}:{run_id}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return Response(success_response(cached))

    try:
        ws = Workspace.objects.get(slug=workspace)
    except Workspace.DoesNotExist:
        return Response(
            error_response("not found", code="not-found"),
            status=404,
        )

    if not ws.drive_root_folder_id:
        return Response(
            error_response("not found", code="not-found"),
            status=404,
        )

    try:
        client = CachedDriveClient(
            get_drive_client(workspace=ws),
            bypass=request.GET.get("force") == "1",
        )
    except ServiceAccountNotFound as exc:
        # Drive misconfiguration is a server problem, not a 404 —
        # surface it explicitly so it can be diagnosed.
        return Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )

    payload = build_summary_payload(
        client, workspace=ws, opp_slug=slug, run_id=run_id,
    )
    if payload is None:
        return Response(
            error_response("not found", code="not-found"),
            status=404,
        )

    _cache.set(cache_key, payload, timeout=_SUMMARY_CACHE_TTL_SECONDS)
    return Response(success_response(payload))
