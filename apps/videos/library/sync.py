"""Bidirectional sync between Google Drive and the DB-backed library.

Drive is the durable store for media + sidecars; the ``videos.VideoLibraryEntry``
and ``videos.AudioLibraryEntry`` tables are a fast index over it.

Two directions:

- **import**: walk Drive, parse sidecars, upsert DB rows. Rows whose Drive
  files no longer exist are removed. Safe to re-run; idempotent.
- **export**: walk DB rows, serialize each back to a JSON sidecar in Drive.
  Skips writes when the Drive sidecar already matches byte-for-byte to
  avoid burning quota on no-ops.

Triggered by the ``videos_sync_library`` management command. The runtime
reader (``apps.videos.library.reader``) only ever queries the DB.
"""
from __future__ import annotations

import json
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
from apps.videos.models import (
    STATUS_MALFORMED_SIDECAR,
    STATUS_MISSING_MEDIA,
    STATUS_MISSING_SIDECAR,
    STATUS_OK,
    AudioLibraryEntry,
    VideoLibraryEntry,
)
from apps.workspaces.models import Workspace

ItemStatus = Literal["ok", "missing-sidecar", "missing-media", "malformed-sidecar"]

_VIDEO_EXTS = {".mp4", ".mov", ".webm"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg"}


# ---------------------------------------------------------------------------
# Walked-Drive shapes (intermediate; never persisted, never returned)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _WalkedVideoItem:
    subfolder: str
    filename: str
    drive_id: str
    name: str
    description: str
    tags: list[str]
    status: ItemStatus


@dataclass(frozen=True)
class _WalkedAudioItem:
    hash: str
    drive_id: str
    voice_id: str
    model: str
    text: str
    duration_sec: float | None
    generated_at: str
    status: ItemStatus


def _layout(workspace: Workspace) -> tuple[DriveLayout, DriveClient]:
    # Local import — avoids cycle between apps.videos.service and library.
    from apps.videos.service import layout_for
    return layout_for(workspace)


# ---------------------------------------------------------------------------
# Drive walkers
# ---------------------------------------------------------------------------


def _walk_video_drive(
    layout: DriveLayout, client: DriveClient,
) -> list[_WalkedVideoItem]:
    """Walk videos/library/video/<subfolder>/ across all subfolders and
    pair media files with their sidecars. Orphans (media w/o sidecar,
    sidecar w/o media, malformed sidecar) come back with non-ok status.
    """
    out: list[_WalkedVideoItem] = []
    for sub in drive_mod.list_library_subfolders(layout, client, drive_mod.LIBRARY_VIDEO):
        out.extend(_walk_video_subfolder(layout, client, sub.name))
    return out


def _walk_video_subfolder(
    layout: DriveLayout, client: DriveClient, subfolder: str,
) -> list[_WalkedVideoItem]:
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

    out: list[_WalkedVideoItem] = []
    for stem, mf in sorted(media.items()):
        sc_file = sidecars.pop(stem, None)
        if sc_file is None:
            out.append(_WalkedVideoItem(
                subfolder=subfolder, filename=mf.name, drive_id=mf.id,
                name="", description="", tags=[],
                status=STATUS_MISSING_SIDECAR,
            ))
            continue
        raw = client.get_binary(sc_file.id)
        try:
            sc = parse_video_sidecar(raw.decode("utf-8"))
        except (SidecarParseError, UnicodeDecodeError):
            out.append(_WalkedVideoItem(
                subfolder=subfolder, filename=mf.name, drive_id=mf.id,
                name="", description="", tags=[],
                status=STATUS_MALFORMED_SIDECAR,
            ))
            continue
        out.append(_WalkedVideoItem(
            subfolder=subfolder, filename=mf.name, drive_id=mf.id,
            name=sc.name, description=sc.description or "", tags=list(sc.tags),
            status=STATUS_OK,
        ))

    # Orphan sidecars (sidecar present, media missing)
    for stem, sc_file in sorted(sidecars.items()):
        out.append(_WalkedVideoItem(
            subfolder=subfolder, filename=f"{stem}.<missing>", drive_id=sc_file.id,
            name="", description="", tags=[],
            status=STATUS_MISSING_MEDIA,
        ))
    return out


def _walk_audio_drive(
    layout: DriveLayout, client: DriveClient,
) -> list[_WalkedAudioItem]:
    """Walk videos/library/audio/ (flat layout) and pair media files
    with their sidecars by hash."""
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

    out: list[_WalkedAudioItem] = []
    for stem, mf in sorted(media.items()):
        sc_file = sidecars.pop(stem, None)
        if sc_file is None:
            out.append(_WalkedAudioItem(
                hash=stem, drive_id=mf.id,
                voice_id="", model="", text="",
                duration_sec=None, generated_at="",
                status=STATUS_MISSING_SIDECAR,
            ))
            continue
        raw = client.get_binary(sc_file.id)
        try:
            sc: AudioSidecar = parse_audio_sidecar(raw.decode("utf-8"))
        except (SidecarParseError, UnicodeDecodeError):
            out.append(_WalkedAudioItem(
                hash=stem, drive_id=mf.id,
                voice_id="", model="", text="",
                duration_sec=None, generated_at="",
                status=STATUS_MALFORMED_SIDECAR,
            ))
            continue
        out.append(_WalkedAudioItem(
            hash=stem, drive_id=mf.id,
            voice_id=sc.voice_id, model=sc.model, text=sc.text,
            duration_sec=sc.duration_sec, generated_at=sc.generated_at,
            status=STATUS_OK,
        ))

    # Orphan sidecars (sidecar present, media missing)
    for stem, sc_file in sorted(sidecars.items()):
        out.append(_WalkedAudioItem(
            hash=stem, drive_id=sc_file.id,
            voice_id="", model="", text="",
            duration_sec=None, generated_at="",
            status=STATUS_MISSING_MEDIA,
        ))
    return out


# ---------------------------------------------------------------------------
# Import: Drive → DB
# ---------------------------------------------------------------------------


def sync_import_video(workspace: Workspace) -> dict[str, int]:
    """Walk Drive's library/video/ and upsert VideoLibraryEntry rows.

    Rows whose ``(subfolder, filename)`` no longer appears in Drive are
    deleted. Returns ``{"created", "updated", "removed", "skipped"}``.
    ``skipped`` counts rows whose existing DB content already matched
    what Drive returned — useful signal in operational logs.
    """
    layout, client = _layout(workspace)
    walked = _walk_video_drive(layout, client)
    seen: set[tuple[str, str]] = set()
    created = updated = skipped = 0
    for w in walked:
        seen.add((w.subfolder, w.filename))
        row, was_created = VideoLibraryEntry.objects.get_or_create(
            workspace=workspace,
            subfolder=w.subfolder,
            filename=w.filename,
            defaults=dict(
                drive_id=w.drive_id,
                name=w.name,
                description=w.description,
                tags=w.tags,
                status=w.status,
            ),
        )
        if was_created:
            created += 1
            continue
        if (
            row.drive_id == w.drive_id
            and row.name == w.name
            and row.description == w.description
            and list(row.tags or []) == list(w.tags)
            and row.status == w.status
        ):
            skipped += 1
            # Touch last_synced_at so operators can see the row was checked.
            row.save(update_fields=["last_synced_at"])
            continue
        row.drive_id = w.drive_id
        row.name = w.name
        row.description = w.description
        row.tags = w.tags
        row.status = w.status
        row.save()
        updated += 1

    # Remove rows that are no longer in Drive.
    qs = VideoLibraryEntry.objects.filter(workspace=workspace)
    if seen:
        # Tuple-membership filter — small N, do it in Python.
        removed = 0
        for row in qs:
            if (row.subfolder, row.filename) not in seen:
                row.delete()
                removed += 1
    else:
        removed, _ = qs.delete()
        removed = removed  # delete() returns (count, {...}); first element is total

    return {"created": created, "updated": updated, "removed": removed, "skipped": skipped}


def sync_import_audio(workspace: Workspace) -> dict[str, int]:
    """Walk Drive's library/audio/ and upsert AudioLibraryEntry rows.

    Rows whose hash no longer appears in Drive are deleted.
    """
    layout, client = _layout(workspace)
    walked = _walk_audio_drive(layout, client)
    seen: set[str] = set()
    created = updated = skipped = 0
    for w in walked:
        seen.add(w.hash)
        row, was_created = AudioLibraryEntry.objects.get_or_create(
            workspace=workspace,
            hash=w.hash,
            defaults=dict(
                drive_id=w.drive_id,
                voice_id=w.voice_id,
                model=w.model,
                text=w.text,
                duration_sec=w.duration_sec,
                generated_at=w.generated_at,
                status=w.status,
            ),
        )
        if was_created:
            created += 1
            continue
        if (
            row.drive_id == w.drive_id
            and row.voice_id == w.voice_id
            and row.model == w.model
            and row.text == w.text
            and row.duration_sec == w.duration_sec
            and row.generated_at == w.generated_at
            and row.status == w.status
        ):
            skipped += 1
            row.save(update_fields=["last_synced_at"])
            continue
        row.drive_id = w.drive_id
        row.voice_id = w.voice_id
        row.model = w.model
        row.text = w.text
        row.duration_sec = w.duration_sec
        row.generated_at = w.generated_at
        row.status = w.status
        row.save()
        updated += 1

    qs = AudioLibraryEntry.objects.filter(workspace=workspace)
    if seen:
        removed = 0
        for row in qs:
            if row.hash not in seen:
                row.delete()
                removed += 1
    else:
        removed, _ = qs.delete()

    return {"created": created, "updated": updated, "removed": removed, "skipped": skipped}


# ---------------------------------------------------------------------------
# Export: DB → Drive
# ---------------------------------------------------------------------------


def _video_sidecar_json(row: VideoLibraryEntry) -> bytes:
    """Serialize a VideoLibraryEntry to a sidecar JSON matching VideoSidecar."""
    payload: dict[str, object] = {
        "name": row.name,
        "tags": list(row.tags or []),
    }
    if row.description:
        payload["description"] = row.description
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _audio_sidecar_json(row: AudioLibraryEntry) -> bytes:
    """Serialize an AudioLibraryEntry to a sidecar JSON matching AudioSidecar."""
    payload: dict[str, object] = {
        "voice_id": row.voice_id,
        "model": row.model,
        "text": row.text,
        "duration_sec": row.duration_sec,
        "generated_at": row.generated_at,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _stem(filename: str) -> str:
    return PurePosixPath(filename).stem


def sync_export_video(workspace: Workspace) -> dict[str, int]:
    """Walk DB rows and write each one back to Drive as a JSON sidecar.

    Skips writes when the Drive sidecar already matches byte-for-byte.
    Only writes for rows whose ``status == "ok"`` — incomplete rows
    don't have enough content to round-trip.
    """
    layout, client = _layout(workspace)
    written = skipped = 0
    rows = VideoLibraryEntry.objects.filter(workspace=workspace, status=STATUS_OK)
    for row in rows:
        sidecar_name = f"{_stem(row.filename)}.json"
        new_bytes = _video_sidecar_json(row)
        existing = drive_mod.read_library_file(
            layout, client, drive_mod.LIBRARY_VIDEO, sidecar_name,
            subfolder=row.subfolder,
        )
        if existing == new_bytes:
            skipped += 1
            continue
        drive_mod.upload_library_file(
            layout, client, drive_mod.LIBRARY_VIDEO,
            sidecar_name, new_bytes, "application/json",
            subfolder=row.subfolder,
        )
        written += 1
    return {"written": written, "skipped": skipped}


def sync_export_audio(workspace: Workspace) -> dict[str, int]:
    """Walk DB rows and write each one back to Drive as a JSON sidecar.

    Skips writes when the Drive sidecar already matches byte-for-byte.
    """
    layout, client = _layout(workspace)
    written = skipped = 0
    rows = AudioLibraryEntry.objects.filter(workspace=workspace, status=STATUS_OK)
    for row in rows:
        sidecar_name = f"{row.hash}.json"
        new_bytes = _audio_sidecar_json(row)
        existing = drive_mod.read_library_file(
            layout, client, drive_mod.LIBRARY_AUDIO, sidecar_name,
        )
        if existing == new_bytes:
            skipped += 1
            continue
        drive_mod.upload_library_file(
            layout, client, drive_mod.LIBRARY_AUDIO,
            sidecar_name, new_bytes, "application/json",
        )
        written += 1
    return {"written": written, "skipped": skipped}
