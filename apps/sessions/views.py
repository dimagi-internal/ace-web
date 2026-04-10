"""REST endpoints for Session CRUD, message read-only listing, and
participant management.

Send is over WebSocket (see apps.sessions.consumers) in Phase 3; the
Phase 2 `send_message` view is deleted. Imported-session auto-activation
lives in the consumer's _handle_chat_send → _activate_imported_session.
"""
from __future__ import annotations

from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.auth.models import User
from apps.common.envelope import error_response, success_response

from .models import Session, SessionParticipant
from .serializers import (
    MessageSerializer,
    ParticipantSerializer,
    SessionDetailSerializer,
    SessionSerializer,
)


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
    source_filter = request.query_params.get("source")
    if source_filter:
        qs = qs.filter(source=source_filter)
    q = request.query_params.get("q", "").strip()
    if q:
        qs = qs.filter(title__icontains=q)
    total = qs.count()
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.query_params.get("page_size", "20"))))
    except ValueError:
        page_size = 20
    offset = (page - 1) * page_size
    qs = qs.order_by("-updated_at")[offset : offset + page_size]
    return Response(
        success_response({
            "items": SessionSerializer(qs, many=True).data,
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def session_detail(request: Request, slug: str) -> Response:
    session = _load_session_for_participant(slug, request.user)
    if session is None:
        return _not_found()

    if request.method == "GET":
        return Response(success_response(SessionDetailSerializer(session).data))

    if request.method == "DELETE":
        if session.owner_id != request.user.id:
            return Response(
                error_response(message="only the owner can delete the session", code="forbidden"),
                status=status.HTTP_403_FORBIDDEN,
            )
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH — only the owner may edit the session row.
    if session.owner_id != request.user.id:
        return Response(
            error_response(message="only the owner can edit the session", code="forbidden"),
            status=status.HTTP_403_FORBIDDEN,
        )
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def messages_list(request: Request, slug: str) -> Response:
    """Read-only ordered list of messages in a session.

    This is the observation endpoint — the WebSocket consumer is the
    only writer in Phase 3. Tests, curl, and the initial-hydration
    fallback path in the frontend all use this.
    """
    session = _load_session_for_participant(slug, request.user)
    if session is None:
        return _not_found()
    rows = session.messages.all().order_by("turn_index")
    return Response(success_response(MessageSerializer(rows, many=True).data))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def participant_collection(request: Request, slug: str) -> Response:
    """Add a participant by @dimagi.com email. Owner only."""
    session = _load_session_for_participant(slug, request.user)
    if session is None:
        return _not_found()

    if session.owner_id != request.user.id:
        return Response(
            error_response(
                message="only the session owner can add participants",
                code="forbidden",
            ),
            status=status.HTTP_403_FORBIDDEN,
        )

    email = (request.data or {}).get("email", "").strip().lower()
    # Stricter than endswith('@dimagi.com'): rpartition on '@' ensures
    # there is exactly one '@' and the domain is exactly dimagi.com, so
    # addresses like "alice@dimagi.com@evil.com" cannot slip through on
    # the validation path (the downstream User.objects.get would still
    # reject them, but as a not_found — the correct behavior is a
    # validation_error at this edge).
    local, sep, domain = email.rpartition("@")
    if sep != "@" or domain != "dimagi.com" or "@" in local or not local:
        return Response(
            error_response(
                message="only @dimagi.com emails may be added",
                code="validation_error",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return Response(
            error_response(
                message="no user with that email has logged in yet",
                code="not_found",
            ),
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        participant = SessionParticipant.objects.create(
            session=session, user=user, role="editor"
        )
    except IntegrityError:
        return Response(
            error_response(
                message="user is already a participant",
                code="conflict",
            ),
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        success_response(ParticipantSerializer(participant).data),
        status=status.HTTP_201_CREATED,
    )


# ────────────────────────────── helpers ──────────────────────────────

def _load_session_for_participant(slug: str, user) -> Session | None:
    """Return the session if `user` is a participant, else None.

    Replaces the Phase 2 `owner=request.user` check so editor/viewer
    participants can read the session too.
    """
    try:
        session = Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None
    is_participant = SessionParticipant.objects.filter(
        session=session, user=user
    ).exists()
    if not is_participant:
        return None
    return session


def _not_found() -> Response:
    return Response(
        error_response(message="session not found", code="not_found"),
        status=status.HTTP_404_NOT_FOUND,
    )
