"""Plain-Python serializers for Session, Message, Draft, and Participant.

These replaced the DRF ModelSerializer implementations when djangorestframework
was removed. The public surface is identical: each class accepts a model
instance (or list with ``many=True``) and exposes a ``.data`` dict/list
property that consumers.py and api_v2.py read from.
"""
from __future__ import annotations

from .models import Draft, Message, Session, SessionParticipant, ShareToken  # noqa: F401


PREVIEW_LIMIT = 120


def _truncate_preview(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= PREVIEW_LIMIT:
        return text
    return text[: PREVIEW_LIMIT - 1].rstrip() + "…"


def _serialize_message(msg: Message) -> dict:
    return {
        "id": msg.pk,
        "turn_index": msg.turn_index,
        "role": msg.role,
        "content": msg.content,
        "plaintext": msg.plaintext,
        "status": msg.status,
        "error_detail": msg.error_detail,
        "started_at": msg.started_at.isoformat() if msg.started_at else None,
        "completed_at": msg.completed_at.isoformat() if msg.completed_at else None,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _serialize_session(obj: Session, *, include_messages: bool = False) -> dict:
    annotated_preview = getattr(obj, "first_user_plaintext", None)
    if annotated_preview is not None:
        preview = _truncate_preview(annotated_preview)
    else:
        msg = (
            obj.messages.filter(role="user")
            .order_by("turn_index")
            .values_list("plaintext", flat=True)
            .first()
        )
        preview = _truncate_preview(msg or "")

    annotated_display = getattr(obj, "opp_display_name_annotated", None)
    if annotated_display is not None:
        opp_display_name = annotated_display or ""
    elif not obj.opp_slug:
        opp_display_name = ""
    else:
        from apps.opps.models import OppWorkspace  # noqa: PLC0415

        opp_display_name = (
            OppWorkspace.objects.filter(
                workspace_id=obj.workspace_id, slug=obj.opp_slug,
            )
            .values_list("display_name", flat=True)
            .first()
            or ""
        )

    opp_step_skill_display = ""
    if obj.opp_step_skill:
        try:
            from django.conf import settings  # noqa: PLC0415

            from apps.system.reader import skill_display_names  # noqa: PLC0415

            lookup = skill_display_names(
                getattr(settings, "ACE_PLUGIN_PATH", "") or ""
            )
            opp_step_skill_display = lookup.get(obj.opp_step_skill, obj.opp_step_skill)
        except Exception:
            opp_step_skill_display = obj.opp_step_skill

    result = {
        "slug": obj.slug,
        "title": obj.title,
        "status": obj.status,
        "backend_kind": obj.backend_kind,
        "source": obj.source,
        "cli_session_id": obj.cli_session_id,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        "message_count": obj.messages.count(),
        "preview": preview,
        "opp_slug": obj.opp_slug or "",
        "opp_run_id": obj.opp_run_id or "",
        "opp_step_skill": obj.opp_step_skill or "",
        "opp_display_name": opp_display_name,
        "opp_step_skill_display": opp_step_skill_display,
    }
    if include_messages:
        result["messages"] = [_serialize_message(m) for m in obj.messages.all()]
    return result


def _serialize_draft(draft: Draft) -> dict:
    updated_at = draft.updated_at
    return {
        "id": draft.pk,
        "slot": draft.slot,
        "status": draft.status,
        "body": draft.body,
        "version": draft.version,
        # last_editor is a ForeignKey — serialise as the integer user PK,
        # matching the wire format the DRF ModelSerializer produced.
        "last_editor": draft.last_editor_id,
        "last_edit_at": updated_at.isoformat() if updated_at else None,
    }


def _serialize_participant(p: SessionParticipant) -> dict:
    return {
        "user_id": p.user_id,
        "email": p.user.email,
        "display_name": p.user.display_name,
        "role": p.role,
        "joined_at": p.joined_at.isoformat() if p.joined_at else None,
        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
    }


class _SingleOrMany:
    """Thin wrapper: serializes one instance or a list (many=True), exposes .data."""

    def __init__(self, instance, *, many: bool = False, _fn):
        self._fn = _fn
        self._instance = instance
        self._many = many

    @property
    def data(self):
        if self._many:
            return [self._fn(obj) for obj in self._instance]
        return self._fn(self._instance)


class MessageSerializer(_SingleOrMany):
    def __init__(self, instance, many: bool = False):
        super().__init__(instance, many=many, _fn=_serialize_message)


class SessionSerializer(_SingleOrMany):
    def __init__(self, instance, many: bool = False):
        super().__init__(instance, many=many, _fn=_serialize_session)


class SessionDetailSerializer(_SingleOrMany):
    def __init__(self, instance, many: bool = False):
        super().__init__(
            instance, many=many,
            _fn=lambda obj: _serialize_session(obj, include_messages=True),
        )


class DraftSerializer(_SingleOrMany):
    def __init__(self, instance, many: bool = False):
        super().__init__(instance, many=many, _fn=_serialize_draft)


class ParticipantSerializer(_SingleOrMany):
    def __init__(self, instance, many: bool = False):
        super().__init__(instance, many=many, _fn=_serialize_participant)


class ShareTokenSerializer(_SingleOrMany):
    def __init__(self, instance, many: bool = False):
        super().__init__(
            instance, many=many,
            _fn=lambda t: {
                "token": t.token,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
            },
        )


class ShareMessageSerializer(_SingleOrMany):
    """Message serializer for public share views — no sender identity."""

    def __init__(self, instance, many: bool = False):
        super().__init__(
            instance, many=many,
            _fn=lambda m: {
                "turn_index": m.turn_index,
                "role": m.role,
                "content": m.content,
                "plaintext": m.plaintext,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            },
        )
