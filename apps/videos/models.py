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


class VideoSnippet(models.Model):
    """One labeled logical range into a master video clip.

    A *snippet* is a ``[in_seconds, out_seconds]`` range into a master
    clip plus the one-line sentence that describes it. Many snippets
    reference one master clip — e.g. five beats of a 60s walkthrough —
    so unlike ``VideoLibraryEntry`` (one row per whole file) this table
    is one row per *labeled range*.

    Snippets are ingested from a canopy "snippet manifest" (the
    ``videos_ingest_snippets`` command). They can be linked to the
    master clip (``clip`` FK) once it lands in the workspace library;
    until then ``source_clip_ref`` / ``source_clip_url`` carry the
    manifest's pointer to the master so the link can be made later by
    matching filename.
    """

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="video_snippets",
    )
    # Stable manifest id (e.g. "verified-monitoring-scene-3"). Unique
    # per workspace — the upsert key for idempotent re-ingest.
    snippet_key = models.CharField(max_length=256)
    title = models.CharField(max_length=512, blank=True)
    # The caption sentence — the descriptive line shown on screen.
    narration_sentence = models.TextField(blank=True)
    # The tight spoken line for this beat's voiceover, distinct from
    # narration_sentence (the caption). Falls back to narration_sentence
    # at ingest time when the manifest snippet omits a ``vo`` string.
    vo = models.TextField(blank=True)
    in_seconds = models.FloatField()
    out_seconds = models.FloatField()
    duration_seconds = models.FloatField()
    tags = models.JSONField(default=list)
    provenance = models.CharField(max_length=128, blank=True, null=True)
    # Top-level manifest fields, denormalized onto every snippet row so
    # the list API can filter by them without a join.
    source_run = models.CharField(max_length=256, blank=True)
    narrative_slug = models.CharField(max_length=256, blank=True)
    scene_index = models.IntegerField(null=True, blank=True)
    # The master clip once it's in the workspace library. Null until the
    # Drive upload + link step matches source_clip_ref to a library row.
    clip = models.ForeignKey(
        VideoLibraryEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="snippets",
    )
    # Manifest pointers to the master clip, kept so a snippet can be
    # ingested + (later) linked to the master without the Drive upload.
    source_clip_ref = models.CharField(max_length=512, blank=True)
    source_clip_url = models.URLField(max_length=512, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_OK)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("workspace", "snippet_key")]
        ordering = ["source_run", "scene_index", "snippet_key"]

    def __str__(self) -> str:
        return f"{self.workspace.slug}/{self.snippet_key}"


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
