"""REST endpoints for Session CRUD, message read-only listing, and
participant management.

Send is over WebSocket (see apps.sessions.consumers) in Phase 3; the
Phase 2 `send_message` view is deleted. Imported-session auto-activation
lives in the consumer's _handle_chat_send → _activate_imported_session.
"""
from __future__ import annotations

from django.db import IntegrityError
from django.db.models import OuterRef, Q, Subquery
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.auth.models import User
from apps.common.envelope import error_response, success_response
from apps.workspaces.permissions import user_workspaces

from .models import Message, Session, SessionParticipant
from .serializers import (
    MessageSerializer,
    ParticipantSerializer,
    SessionDetailSerializer,
    SessionSerializer,
)


def _annotate_first_user_plaintext(qs):
    """Annotate ``first_user_plaintext`` with the earliest user message body.

    SessionSerializer.get_preview reads this annotation when present to
    avoid an N+1 ``messages.first()`` lookup per row in list responses.
    """
    first_user_msg = (
        Message.objects.filter(session=OuterRef("pk"), role="user")
        .order_by("turn_index")
        .values("plaintext")[:1]
    )
    return qs.annotate(first_user_plaintext=Subquery(first_user_msg))


def _scope_sessions_to_user(qs, user):
    """Restrict a Session queryset to sessions the user can see:
    sessions in workspaces they're a member of, plus orphan sessions
    (workspace=NULL) that they own.

    Phase A: this is the read-side membership gate. The orphan
    fallback preserves visibility for sessions created before
    workspaces existed and for chat sessions not yet tied to an opp.
    """
    if not user.is_authenticated:
        return qs.none()
    member_ws_ids = list(user_workspaces(user).values_list("slug", flat=True))
    return qs.filter(
        Q(workspace__in=member_ws_ids) | Q(workspace__isnull=True, owner=user)
    )


@api_view(["POST", "GET"])
@permission_classes([IsAuthenticated])
def session_collection(request: Request) -> Response:
    if request.method == "POST":
        return _create_session(request)
    return _list_sessions(request)


def _create_session(request: Request) -> Response:
    title = (request.data or {}).get("title", "")
    session = Session.create_with_owner(owner=request.user, title=title)
    return Response(
        success_response(SessionSerializer(session).data),
        status=status.HTTP_201_CREATED,
    )


def _list_sessions(request: Request) -> Response:
    # Membership-gated: users see sessions in workspaces they're a member of,
    # plus orphan sessions (no workspace) that they own. Filter-by-owner is
    # available via ?owner=<id> if callers want to narrow further.
    qs = _scope_sessions_to_user(Session.objects.all(), request.user)
    owner_filter = request.query_params.get("owner")
    if owner_filter:
        qs = qs.filter(owner_id=owner_filter)
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)
    source_filter = request.query_params.get("source")
    if source_filter:
        qs = qs.filter(source=source_filter)
    opp_filter = request.query_params.get("opp")
    if opp_filter:
        qs = qs.filter(opp_slug=opp_filter)
    q = request.query_params.get("q", "").strip()
    if q:
        # Match either the title or the body of any user message in the
        # session — so typing a topic finds sessions where the topic was
        # actually discussed, not just sessions whose auto-title happens to
        # mention it. ``distinct`` because the join over messages would
        # otherwise duplicate rows.
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(messages__role="user", messages__plaintext__icontains=q)
        ).distinct()
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
    qs = _annotate_first_user_plaintext(qs).order_by("-updated_at")[
        offset : offset + page_size
    ]
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
    # Validate the email shape (exactly one '@'). Domain allowlist is
    # only enforced when ACE_ALLOWED_EMAIL_DOMAINS is non-empty (matches
    # the new auth flow — workspace membership is the access-control gate).
    from django.conf import settings as django_settings

    local, sep, domain = email.rpartition("@")
    if sep != "@" or "@" in local or not local or not domain:
        return Response(
            error_response(
                message="invalid email address",
                code="validation_error",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    allowed_domains = getattr(django_settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    if allowed_domains and domain not in allowed_domains:
        allowed_str = ", ".join(f"@{d}" for d in allowed_domains)
        return Response(
            error_response(
                message=f"only {allowed_str} emails may be added",
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
    """Return the session if the caller is allowed to read it.

    For workspace-tied sessions: the user must be a member of that
    workspace (any role). Non-members get None (the caller maps that to
    a 404 so workspace existence isn't leaked).

    For orphan sessions (workspace=NULL — legacy sessions and the
    unattached blank chats created via POST /api/sessions): the user
    must be the session owner OR an existing SessionParticipant.

    Owner-only mutation checks (DELETE, PATCH, add-participant) still
    live at the call sites; this helper only gates the read path.
    """
    if not user or not user.is_authenticated:
        return None
    try:
        session = Session.objects.select_related("workspace").get(slug=slug)
    except Session.DoesNotExist:
        return None

    if session.workspace_id is not None:
        from apps.workspaces.permissions import is_member
        if not is_member(user, session.workspace):
            return None
        return session

    # Orphan session — owner or pre-existing participant only.
    if session.owner_id == user.id:
        return session
    if SessionParticipant.objects.filter(
        session_id=session.pk, user_id=user.id
    ).exists():
        return session
    return None


def _not_found() -> Response:
    return Response(
        error_response(message="session not found", code="not_found"),
        status=status.HTTP_404_NOT_FOUND,
    )
