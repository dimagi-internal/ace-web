"""Workspace-scoped media library reader.

Walks Drive folders, pairs media files with their JSON sidecars by stem,
and returns typed responses. Orphans (media with no sidecar, sidecar with
no media, malformed sidecar) are surfaced as ``status != "ok"`` rather
than dropped silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from apps.opps.drive_client import DriveClient, DriveFile
from apps.videos import drive as drive_mod
from apps.videos.drive import DriveLayout
from apps.videos.library.sidecar import (
    AudioSidecar,
    SidecarParseError,
    parse_audio_sidecar,
    parse_video_sidecar,
)
from apps.workspaces.models import Workspace

ItemStatus = Literal["ok", "missing-sidecar", "missing-media", "malformed-sidecar"]

_VIDEO_EXTS = {".mp4", ".mov", ".webm"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg"}


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


def _drive_url(drive_id: str) -> str:
    return f"https://drive.google.com/file/d/{drive_id}/view"


def _layout(workspace: Workspace) -> tuple[DriveLayout, DriveClient]:
    # Local import — avoids cycle between apps.videos.service and library/refs.py.
    from apps.videos.service import layout_for
    return layout_for(workspace)


def _list_video_library_uncached(workspace: Workspace) -> VideoLibraryResponse:
    layout, client = _layout(workspace)
    subs = drive_mod.list_library_subfolders(layout, client, drive_mod.LIBRARY_VIDEO)
    out_subs: list[VideoLibrarySubfolder] = []
    for sub in subs:
        items = _items_in_video_subfolder(layout, client, sub.name)
        if not items:
            continue
        out_subs.append(VideoLibrarySubfolder(subfolder=sub.name, items=items))
    return VideoLibraryResponse(subfolders=out_subs)


def _items_in_video_subfolder(
    layout: DriveLayout, client: DriveClient, subfolder: str,
) -> list[VideoLibraryItem]:
    files = drive_mod.list_library_files(layout, client, drive_mod.LIBRARY_VIDEO, subfolder)
    media: dict[str, DriveFile] = {}
    sidecars: dict[str, DriveFile] = {}
    for f in files:
        ext = PurePosixPath(f.name).suffix.lower()
        stem = PurePosixPath(f.name).stem
        if ext in _VIDEO_EXTS:
            media[stem] = f
        elif ext == ".json":
            sidecars[stem] = f
        # Other extensions ignored.

    out: list[VideoLibraryItem] = []
    for stem, mf in sorted(media.items()):
        sc_file = sidecars.pop(stem, None)
        if sc_file is None:
            out.append(VideoLibraryItem(
                subfolder=subfolder, filename=mf.name, drive_id=mf.id,
                drive_url=_drive_url(mf.id),
                ref=f"library:video/{subfolder}/{mf.name}",
                name=None, description=None, tags=[],
                status="missing-sidecar",
            ))
            continue
        raw = client.get_binary(sc_file.id)
        try:
            sc = parse_video_sidecar(raw.decode("utf-8"))
        except (SidecarParseError, UnicodeDecodeError):
            out.append(VideoLibraryItem(
                subfolder=subfolder, filename=mf.name, drive_id=mf.id,
                drive_url=_drive_url(mf.id),
                ref=f"library:video/{subfolder}/{mf.name}",
                name=None, description=None, tags=[],
                status="malformed-sidecar",
            ))
            continue
        out.append(VideoLibraryItem(
            subfolder=subfolder, filename=mf.name, drive_id=mf.id,
            drive_url=_drive_url(mf.id),
            ref=f"library:video/{subfolder}/{mf.name}",
            name=sc.name, description=sc.description, tags=list(sc.tags),
            status="ok",
        ))

    # Orphan sidecars (sidecar present, media missing)
    for stem, sc_file in sorted(sidecars.items()):
        out.append(VideoLibraryItem(
            subfolder=subfolder, filename=f"{stem}.<missing>", drive_id=sc_file.id,
            drive_url=_drive_url(sc_file.id),
            ref=f"library:video/{subfolder}/{stem}",
            name=None, description=None, tags=[],
            status="missing-media",
        ))
    return out


def _list_audio_library_uncached(workspace: Workspace) -> AudioLibraryResponse:
    layout, client = _layout(workspace)
    files = drive_mod.list_audio_library_files(layout, client)
    media: dict[str, DriveFile] = {}
    sidecars: dict[str, DriveFile] = {}
    for f in files:
        ext = PurePosixPath(f.name).suffix.lower()
        stem = PurePosixPath(f.name).stem
        if ext in _AUDIO_EXTS:
            media[stem] = f
        elif ext == ".json":
            sidecars[stem] = f

    items: list[AudioLibraryItem] = []
    for stem, mf in sorted(media.items()):
        sc_file = sidecars.pop(stem, None)
        if sc_file is None:
            items.append(AudioLibraryItem(
                hash=stem, drive_id=mf.id, drive_url=_drive_url(mf.id),
                voice_id=None, model=None, text=None,
                duration_sec=None, generated_at=None,
                status="missing-sidecar",
            ))
            continue
        raw = client.get_binary(sc_file.id)
        try:
            sc: AudioSidecar = parse_audio_sidecar(raw.decode("utf-8"))
        except (SidecarParseError, UnicodeDecodeError):
            items.append(AudioLibraryItem(
                hash=stem, drive_id=mf.id, drive_url=_drive_url(mf.id),
                voice_id=None, model=None, text=None,
                duration_sec=None, generated_at=None,
                status="malformed-sidecar",
            ))
            continue
        items.append(AudioLibraryItem(
            hash=stem, drive_id=mf.id, drive_url=_drive_url(mf.id),
            voice_id=sc.voice_id, model=sc.model, text=sc.text,
            duration_sec=sc.duration_sec, generated_at=sc.generated_at,
            status="ok",
        ))

    # Orphan sidecars
    for stem, sc_file in sorted(sidecars.items()):
        items.append(AudioLibraryItem(
            hash=stem, drive_id=sc_file.id, drive_url=_drive_url(sc_file.id),
            voice_id=None, model=None, text=None,
            duration_sec=None, generated_at=None,
            status="missing-media",
        ))

    return AudioLibraryResponse(items=items)


# Public entry points — wrapped with the TTL cache in Task 4.2.
list_video_library = _list_video_library_uncached
list_audio_library = _list_audio_library_uncached
