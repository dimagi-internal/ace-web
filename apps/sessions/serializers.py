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


class SessionSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

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
        ]
        read_only_fields = [
            "slug", "cli_session_id", "created_at", "updated_at", "message_count",
        ]

    def get_message_count(self, obj: Session) -> int:
        return obj.messages.count()


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
