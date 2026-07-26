from django.contrib import admin

from .models import IngestUpload, Message, Session, SessionParticipant


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "owner", "backend_kind", "status", "source", "created_at")
    list_filter = ("backend_kind", "status", "source")
    search_fields = ("slug", "title", "owner__email")
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(SessionParticipant)
class SessionParticipantAdmin(admin.ModelAdmin):
    list_display = ("session", "user", "role", "joined_at", "last_seen_at")
    list_filter = ("role",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("session", "turn_index", "role", "status", "started_at")
    list_filter = ("role", "status")
    readonly_fields = ("session", "turn_index", "role", "content", "plaintext")


@admin.register(IngestUpload)
class IngestUploadAdmin(admin.ModelAdmin):
    list_display = ("session", "uploaded_by", "line_count", "raw_bytes", "created_at")
