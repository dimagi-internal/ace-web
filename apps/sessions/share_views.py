"""REST endpoints for share token management and public share viewing."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from .models import Session, SessionParticipant, ShareToken
from .serializers import ShareMessageSerializer, ShareTokenSerializer


def _load_session_for_editor(slug: str, user) -> tuple[Session | None, str | None]:
    """Return (session, None) if user is owner or editor, else (None, reason)."""
    try:
        session = Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None, "not_found"
    try:
        participant = SessionParticipant.objects.get(session=session, user=user)
    except SessionParticipant.DoesNotExist:
        return None, "not_found"
    if participant.role == "viewer":
        return None, "forbidden"
    return session, None


@api_view(["POST", "GET"])
@permission_classes([IsAuthenticated])
def share_token_collection(request: Request, slug: str) -> Response:
    session, reason = _load_session_for_editor(slug, request.user)
    if session is None:
        if reason == "forbidden":
            return Response(
                error_response("only owners and editors can manage share tokens", code="forbidden"),
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            error_response("session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "POST":
        token = ShareToken.objects.create(session=session, created_by=request.user)
        base_url = request.build_absolute_uri("/").rstrip("/")
        from django.conf import settings
        prefix = settings.FORCE_SCRIPT_NAME or ""
        share_url = f"{base_url}{prefix}/share/{token.token}"
        return Response(
            success_response({
                "token": token.token,
                "url": share_url,
                "created_at": token.created_at.isoformat(),
            }),
            status=status.HTTP_201_CREATED,
        )

    # GET — list active (non-revoked) tokens
    tokens = ShareToken.objects.filter(
        session=session, revoked_at__isnull=True,
    ).order_by("-created_at")
    return Response(success_response(ShareTokenSerializer(tokens, many=True).data))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def share_token_revoke(request: Request, slug: str, token: str) -> Response:
    session, reason = _load_session_for_editor(slug, request.user)
    if session is None:
        if reason == "forbidden":
            return Response(
                error_response("only owners and editors can manage share tokens", code="forbidden"),
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            error_response("session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        share_token = ShareToken.objects.get(
            session=session, token=token, revoked_at__isnull=True,
        )
    except ShareToken.DoesNotExist:
        return Response(
            error_response("share token not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    share_token.revoked_at = timezone.now()
    share_token.save(update_fields=["revoked_at"])
    return Response(success_response(ShareTokenSerializer(share_token).data))


@api_view(["GET"])
@permission_classes([AllowAny])
def public_share_view(request: Request, token: str) -> Response:
    """Public read-only view of a shared session. No auth required."""
    try:
        share_token = ShareToken.objects.select_related("session").get(token=token)
    except ShareToken.DoesNotExist:
        return Response(
            error_response("share link not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if share_token.revoked_at is not None:
        return Response(
            error_response("this share link has been revoked", code="revoked"),
            status=status.HTTP_404_NOT_FOUND,
        )

    session = share_token.session
    messages = session.messages.all().order_by("turn_index")
    return Response(success_response({
        "title": session.title,
        "messages": ShareMessageSerializer(messages, many=True).data,
    }))
