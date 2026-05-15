"""Django admin registrations for the videos app."""
from __future__ import annotations

from django.contrib import admin

from apps.videos.models import AudioLibraryEntry, VideoLibraryEntry


@admin.register(VideoLibraryEntry)
class VideoLibraryEntryAdmin(admin.ModelAdmin):
    list_display = ("workspace", "subfolder", "filename", "status", "last_synced_at")
    list_filter = ("workspace", "subfolder", "status")
    search_fields = ("filename", "name", "description", "drive_id")
    readonly_fields = ("last_synced_at",)


@admin.register(AudioLibraryEntry)
class AudioLibraryEntryAdmin(admin.ModelAdmin):
    list_display = ("workspace", "hash", "voice_id", "model", "status", "last_synced_at")
    list_filter = ("workspace", "voice_id", "model", "status")
    search_fields = ("hash", "text", "drive_id")
    readonly_fields = ("last_synced_at",)
