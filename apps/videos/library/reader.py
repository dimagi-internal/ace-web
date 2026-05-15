"""Workspace-scoped media library reader.

Returns the typed list shapes the API surface (and the renderer's
``library:`` ref resolver) consume. As of the DB-backed pivot the
reader hits Postgres; Drive walking only happens at sync time
(see ``apps.videos.library.sync``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from apps.workspaces.models import Workspace

ItemStatus = Literal["ok", "missing-sidecar", "missing-media", "malformed-sidecar"]


@dataclass(frozen=True)
class VideoLibraryItem:
    subfolder: str
    filename: str
    drive_id: str
    drive_url: str
    ref: str  # "library:video/<subfolder>/<filename>"
    name: str | None
    description: str | None
    tags: list[str]
    status: ItemStatus


@dataclass(frozen=True)
class VideoLibrarySubfolder:
    subfolder: str
    items: list[VideoLibraryItem]


@dataclass(frozen=True)
class VideoLibraryResponse:
    subfolders: list[VideoLibrarySubfolder]


@dataclass(frozen=True)
class AudioLibraryItem:
    hash: str
    drive_id: str
    drive_url: str
    voice_id: str | None
    model: str | None
    text: str | None
    duration_sec: float | None
    generated_at: str | None
    status: ItemStatus


@dataclass(frozen=True)
class AudioLibraryResponse:
    items: list[AudioLibraryItem]


def list_video_library(workspace: Workspace) -> VideoLibraryResponse:
    """All video library entries for the workspace, grouped by subfolder."""
    # Local import — avoid pulling the ORM at module load time.
    from apps.videos.models import VideoLibraryEntry

    rows = VideoLibraryEntry.objects.filter(workspace=workspace)
    by_sub: dict[str, list[VideoLibraryItem]] = {}
    for row in rows:
        by_sub.setdefault(row.subfolder, []).append(VideoLibraryItem(
            subfolder=row.subfolder,
            filename=row.filename,
            drive_id=row.drive_id,
            drive_url=row.drive_url,
            ref=row.ref,
            name=row.name or None,
            description=row.description or None,
            tags=list(row.tags or []),
            status=row.status,
        ))
    subfolders = [
        VideoLibrarySubfolder(subfolder=sub, items=items)
        for sub, items in sorted(by_sub.items())
    ]
    return VideoLibraryResponse(subfolders=subfolders)


def list_audio_library(workspace: Workspace) -> AudioLibraryResponse:
    """All audio library entries for the workspace, flat list."""
    from apps.videos.models import AudioLibraryEntry

    rows = AudioLibraryEntry.objects.filter(workspace=workspace)
    items = [
        AudioLibraryItem(
            hash=row.hash,
            drive_id=row.drive_id,
            drive_url=row.drive_url,
            voice_id=row.voice_id or None,
            model=row.model or None,
            text=row.text or None,
            duration_sec=row.duration_sec,
            generated_at=row.generated_at or None,
            status=row.status,
        )
        for row in rows
    ]
    return AudioLibraryResponse(items=items)
