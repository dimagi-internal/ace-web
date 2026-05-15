"""Session query helpers shared by other app modules.

The DRF view surface (session_collection, session_detail, messages_list, etc.)
has been removed — sessions are now served exclusively via the v2 Ninja router
at apps/sessions/api.py.

This module is kept as a thin helper shim because two external callers still
import from it:
  - apps.activity.views imports _scope_sessions_to_user
  - apps.opps.views_session imports _annotate_first_user_plaintext
"""
from __future__ import annotations

from django.db.models import OuterRef, Q, Subquery

from apps.workspaces.permissions import user_workspaces

from .models import Message


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
