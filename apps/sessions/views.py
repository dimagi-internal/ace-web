"""REST endpoints for Session CRUD and listing."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from .models import Message, Session, SessionParticipant
from .serializers import SessionDetailSerializer, SessionSerializer


@api_view(["POST", "GET"])
@permission_classes([IsAuthenticated])
def session_collection(request: Request) -> Response:
    if request.method == "POST":
        return _create_session(request)
    return _list_sessions(request)


def _create_session(request: Request) -> Response:
    title = (request.data or {}).get("title", "")
    session = Session.objects.create(owner=request.user, title=title)
    SessionParticipant.objects.create(
        session=session, user=request.user, role="owner"
    )
    return Response(
        success_response(SessionSerializer(session).data),
        status=status.HTTP_201_CREATED,
    )


def _list_sessions(request: Request) -> Response:
    qs = Session.objects.filter(owner=request.user)
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))
    qs = qs.order_by("-updated_at")[:limit]
    return Response(success_response(SessionSerializer(qs, many=True).data))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def session_detail(request: Request, slug: str) -> Response:
    try:
        session = Session.objects.get(slug=slug, owner=request.user)
    except Session.DoesNotExist:
        return Response(
            error_response(message="session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        return Response(success_response(SessionDetailSerializer(session).data))

    # PATCH
    allowed = {"title", "status"}
    updates = {k: v for k, v in (request.data or {}).items() if k in allowed}
    if "status" in updates and updates["status"] not in {"active", "archived"}:
        return Response(
            error_response(message="invalid status", code="validation_error"),
            status=400,
        )
    for k, v in updates.items():
        setattr(session, k, v)
    if updates:
        session.save(update_fields=list(updates.keys()) + ["updated_at"])
    return Response(success_response(SessionSerializer(session).data))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_message(request: Request, slug: str) -> Response:
    try:
        session = Session.objects.get(slug=slug, owner=request.user)
    except Session.DoesNotExist:
        return Response(
            error_response(message="session not found", code="not_found"),
            status=404,
        )

    text = (request.data or {}).get("text", "").strip()
    if not text:
        return Response(
            error_response(message="text is required", code="validation_error"),
            status=400,
        )

    with transaction.atomic():
        last_turn = (
            Message.objects.filter(session=session)
            .order_by("-turn_index")
            .values_list("turn_index", flat=True)
            .first()
        )
        next_turn = (last_turn or 0) + 1
        user_msg = Message.objects.create(
            session=session,
            turn_index=next_turn,
            role="user",
            sender_user=request.user,
            content={"text": text},
            plaintext=text,
            status="complete",
            completed_at=timezone.now(),
        )
        assistant_msg = Message.objects.create(
            session=session,
            turn_index=next_turn + 1,
            role="assistant",
            content={"text": ""},
            plaintext="",
            status="pending",
        )

    return Response(
        success_response({
            "user_message_id": user_msg.id,
            "assistant_message_id": assistant_msg.id,
        }),
        status=201,
    )
