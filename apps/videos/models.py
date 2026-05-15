"""Workspace-scoped media library metadata.

Drive remains the durable store for the actual media files + sidecar
JSONs. These tables are an operationally-fast denormalized index over
that Drive content; everything in here can be reconstructed by re-
running ``videos_sync_library --direction=import``.

The motivation is cold-load latency: walking Drive's library/video/ and
library/audio/ folders + fetching every sidecar takes ~3s at 19 audio
items today and scales linearly into the 60-90s range at a few hundred
items. Reads now hit Postgres; the Drive walk happens at sync time only.
"""
from __future__ import annotations

from django.db import models

from apps.workspaces.models import Workspace

STATUS_OK = "ok"
STATUS_MISSING_SIDECAR = "missing-sidecar"
STATUS_MISSING_MEDIA = "missing-media"
STATUS_MALFORMED_SIDECAR = "malformed-sidecar"

STATUS_CHOICES = [
    (STATUS_OK, "ok"),
    (STATUS_MISSING_SIDECAR, "missing-sidecar"),
    (STATUS_MISSING_MEDIA, "missing-media"),
    (STATUS_MALFORMED_SIDECAR, "malformed-sidecar"),
]


class VideoLibraryEntry(models.Model):
    """One curated video clip in a workspace's library."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="video_library_entries",
    )
    subfolder = models.CharField(max_length=128)
    filename = models.CharField(max_length=256)
    drive_id = models.CharField(max_length=128, db_index=True)
    name = models.CharField(max_length=256, blank=True)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_OK)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("workspace", "subfolder", "filename")]
        ordering = ["subfolder", "filename"]

    def __str__(self) -> str:
        return f"{self.workspace.slug}/{self.subfolder}/{self.filename}"

    @property
    def ref(self) -> str:
        return f"library:video/{self.subfolder}/{self.filename}"

    @property
    def drive_url(self) -> str:
        return f"https://drive.google.com/file/d/{self.drive_id}/view"


class AudioLibraryEntry(models.Model):
    """One TTS-synthesized audio clip in a workspace's library."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="audio_library_entries",
    )
    hash = models.CharField(max_length=32)
    drive_id = models.CharField(max_length=128, db_index=True)
    voice_id = models.CharField(max_length=128, blank=True)
    model = models.CharField(max_length=128, blank=True)
    text = models.TextField(blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    generated_at = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_OK)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("workspace", "hash")]
        ordering = ["-generated_at", "hash"]

    def __str__(self) -> str:
        return f"{self.workspace.slug}/audio/{self.hash}"

    @property
    def drive_url(self) -> str:
        return f"https://drive.google.com/file/d/{self.drive_id}/view"
