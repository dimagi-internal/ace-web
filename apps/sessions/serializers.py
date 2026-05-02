"""DRF serializers for Session, Message, Draft, and Participant."""
from __future__ import annotations

from rest_framework import serializers

from .models import Draft, Message, Session, SessionParticipant, ShareToken


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "turn_index",
            "role",
            "content",
            "plaintext",
            "status",
            "error_detail",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields


PREVIEW_LIMIT = 120


def _truncate_preview(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= PREVIEW_LIMIT:
        return text
    return text[: PREVIEW_LIMIT - 1].rstrip() + "…"


class SessionSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()
    preview = serializers.SerializerMethodField()
    opp_display_name = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "slug",
            "title",
            "status",
            "backend_kind",
            "source",
            "cli_session_id",
            "created_at",
            "updated_at",
            "message_count",
            "preview",
            # Opp linkage — populated server-side by the "Discuss in chat"
            # seed and the /ingest/upload path. Read-only for the chat UI;
            # the chat surface uses these to render the opp breadcrumb,
            # group the recent-sessions sidebar, and drive the ?opp=
            # filter on the /sessions page.
            "opp_slug",
            "opp_run_id",
            "opp_step_skill",
            # Human display name from OppWorkspace (sprint 2). Empty
            # string when not opp-linked or when the OppWorkspace row
            # has been deleted; chat UI falls back to opp_slug.
            "opp_display_name",
        ]
        read_only_fields = [
            "slug", "cli_session_id", "created_at", "updated_at",
            "message_count", "preview",
            "opp_slug", "opp_run_id", "opp_step_skill",
            "opp_display_name",
        ]

    def get_message_count(self, obj: Session) -> int:
        return obj.messages.count()

    def get_opp_display_name(self, obj: Session) -> str:
        # The list view annotates this on the queryset to avoid N+1; if
        # present, prefer it. Otherwise (detail view, ad-hoc serialize)
        # do a single targeted lookup. Empty string when the session
        # isn't opp-linked or the OppWorkspace row has been deleted.
        annotated = getattr(obj, "opp_display_name_annotated", None)
        if annotated is not None:
            return annotated or ""
        if not obj.opp_slug:
            return ""
        # Lazy import — apps.opps depends on apps.sessions, so a top-level
        # import would set up a cycle.
        from apps.opps.models import OppWorkspace

        return (
            OppWorkspace.objects.filter(
                workspace_id=obj.workspace_id, slug=obj.opp_slug,
            )
            .values_list("display_name", flat=True)
            .first()
            or ""
        )

    def get_preview(self, obj: Session) -> str:
        annotated = getattr(obj, "first_user_plaintext", None)
        if annotated is not None:
            return _truncate_preview(annotated)
        msg = (
            obj.messages.filter(role="user")
            .order_by("turn_index")
            .values_list("plaintext", flat=True)
            .first()
        )
        return _truncate_preview(msg or "")


class SessionDetailSerializer(SessionSerializer):
    """Same as SessionSerializer but includes the full message list."""
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(SessionSerializer.Meta):
        fields = SessionSerializer.Meta.fields + ["messages"]


class DraftSerializer(serializers.ModelSerializer):
    last_edit_at = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Draft
        fields = [
            "id",
            "slot",
            "status",
            "body",
            "version",
            "last_editor",
            "last_edit_at",
        ]
        read_only_fields = fields


class ParticipantSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    display_name = serializers.CharField(
        source="user.display_name", read_only=True
    )

    class Meta:
        model = SessionParticipant
        fields = [
            "user_id",
            "email",
            "display_name",
            "role",
            "joined_at",
            "last_seen_at",
        ]
        read_only_fields = fields


class ShareTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareToken
        fields = ["token", "created_at", "revoked_at"]
        read_only_fields = fields


class ShareMessageSerializer(serializers.ModelSerializer):
    """Message serializer for public share views — no sender identity."""

    class Meta:
        model = Message
        fields = [
            "turn_index",
            "role",
            "content",
            "plaintext",
            "status",
            "created_at",
        ]
        read_only_fields = fields
