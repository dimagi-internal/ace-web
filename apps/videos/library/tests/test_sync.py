"""Tests for ``apps.videos.library.sync``.

Bidirectional Drive↔DB sync for the media library. Import is the hot
path that backfills DB rows from Drive content; export is the rarer
"DB row changed, push it back to Drive" path.
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import sync as lib_sync
from apps.videos.models import AudioLibraryEntry, VideoLibraryEntry
from apps.workspaces.models import Workspace

User = get_user_model()


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive_mod, "client_for_workspace", lambda ws: client)
    return client


@pytest.fixture
def workspace(db, fake_drive):
    creator = User.objects.create_user(email="creator@example.com")
    return Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi",
        drive_root_folder_id=fake_drive.folder_id("ws-root"),
        created_by=creator,
    )


@pytest.fixture
def seeded_video_library(workspace, fake_drive):
    """library/video/uganda-field/ — one well-formed clip and one orphan."""
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO,
        "drone-wide.mp4", b"mp4-bytes", "video/mp4",
        subfolder="uganda-field",
    )
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO,
        "drone-wide.json",
        json.dumps({
            "name": "Drone — village wide",
            "description": "Sunrise push-in",
            "tags": ["drone", "wide", "uganda"],
        }).encode(),
        "application/json",
        subfolder="uganda-field",
    )
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO,
        "orphan.mp4", b"mp4-bytes", "video/mp4",
        subfolder="uganda-field",
    )
    return layout


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def test_sync_import_video_creates_rows(workspace, fake_drive, seeded_video_library):
    counts = lib_sync.sync_import_video(workspace)
    assert counts["created"] == 2
    assert counts["updated"] == 0
    assert counts["removed"] == 0

    rows = list(VideoLibraryEntry.objects.filter(workspace=workspace).order_by("filename"))
    names = [r.filename for r in rows]
    assert names == ["drone-wide.mp4", "orphan.mp4"]

    drone = next(r for r in rows if r.filename == "drone-wide.mp4")
    assert drone.status == "ok"
    assert drone.name == "Drone — village wide"
    assert drone.tags == ["drone", "wide", "uganda"]
    assert drone.description == "Sunrise push-in"

    orphan = next(r for r in rows if r.filename == "orphan.mp4")
    assert orphan.status == "missing-sidecar"


def test_sync_import_audio_creates_rows(workspace, fake_drive):
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "abc.mp3", b"x", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "abc.json",
        json.dumps({
            "voice_id": "v", "model": "m", "text": "t",
            "duration_sec": 1.0, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )

    counts = lib_sync.sync_import_audio(workspace)
    assert counts["created"] == 1

    row = AudioLibraryEntry.objects.get(workspace=workspace, hash="abc")
    assert row.voice_id == "v"
    assert row.model == "m"
    assert row.text == "t"
    assert row.duration_sec == 1.0
    assert row.generated_at == "2026-05-15T00:00:00Z"
    assert row.status == "ok"


def test_sync_import_audio_handles_malformed_sidecar(workspace, fake_drive):
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "bad.mp3", b"x", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "bad.json", b"{not json", "application/json",
    )
    counts = lib_sync.sync_import_audio(workspace)
    assert counts["created"] == 1
    row = AudioLibraryEntry.objects.get(workspace=workspace, hash="bad")
    assert row.status == "malformed-sidecar"


def test_sync_import_is_idempotent(workspace, fake_drive, seeded_video_library):
    """Second import with no Drive changes should report 0 created/updated."""
    lib_sync.sync_import_video(workspace)
    counts = lib_sync.sync_import_video(workspace)
    assert counts["created"] == 0
    assert counts["updated"] == 0
    assert counts["removed"] == 0
    assert counts["skipped"] == 2


def test_sync_import_updates_changed_rows(workspace, fake_drive, seeded_video_library):
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    lib_sync.sync_import_video(workspace)

    # Update the sidecar on Drive.
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO,
        "drone-wide.json",
        json.dumps({
            "name": "Drone — new name", "tags": ["drone"],
        }).encode(),
        "application/json",
        subfolder="uganda-field",
    )

    counts = lib_sync.sync_import_video(workspace)
    assert counts["updated"] == 1
    row = VideoLibraryEntry.objects.get(
        workspace=workspace, subfolder="uganda-field", filename="drone-wide.mp4",
    )
    assert row.name == "Drone — new name"
    assert row.tags == ["drone"]


def test_sync_import_removes_deleted_drive_rows(workspace, fake_drive, seeded_video_library):
    """When a Drive file disappears, the matching DB row is dropped."""
    lib_sync.sync_import_video(workspace)
    initial = VideoLibraryEntry.objects.filter(workspace=workspace).count()
    assert initial == 2

    # Simulate Drive deletion by yanking the orphan media file out of the
    # fake drive's internal tree. (FakeDriveClient has no delete method.)
    folder_id = drive_mod.library_folder_id(
        service_mod.layout_for(workspace, client=fake_drive)[0],
        fake_drive, drive_mod.LIBRARY_VIDEO, "uganda-field",
    )
    folder_node = fake_drive._nodes_by_id[folder_id]
    orphan_node = folder_node.children.pop("orphan.mp4")
    del fake_drive._nodes_by_id[orphan_node.id]

    counts = lib_sync.sync_import_video(workspace)
    assert counts["removed"] == 1
    remaining = list(VideoLibraryEntry.objects.filter(workspace=workspace))
    assert len(remaining) == 1
    assert remaining[0].filename == "drone-wide.mp4"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_sync_export_video_writes_sidecars(workspace, fake_drive, seeded_video_library):
    """Mutating a DB row's name + export pushes the change back to Drive."""
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    lib_sync.sync_import_video(workspace)

    row = VideoLibraryEntry.objects.get(
        workspace=workspace, subfolder="uganda-field", filename="drone-wide.mp4",
    )
    row.name = "Drone — renamed in DB"
    row.tags = ["drone", "newtag"]
    row.save()

    counts = lib_sync.sync_export_video(workspace)
    assert counts["written"] == 1

    sidecar = drive_mod.read_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO, "drone-wide.json",
        subfolder="uganda-field",
    )
    assert sidecar is not None
    parsed = json.loads(sidecar.decode())
    assert parsed["name"] == "Drone — renamed in DB"
    assert parsed["tags"] == ["drone", "newtag"]


def test_sync_export_video_skips_unchanged(workspace, fake_drive, seeded_video_library):
    """First export normalizes Drive sidecars; the second is a byte-identical no-op."""
    lib_sync.sync_import_video(workspace)
    lib_sync.sync_export_video(workspace)
    # Second export with no DB changes: sidecars in Drive now match the
    # canonical form, so nothing is written.
    counts = lib_sync.sync_export_video(workspace)
    assert counts["written"] == 0
    ok_count = VideoLibraryEntry.objects.filter(workspace=workspace, status="ok").count()
    assert counts["skipped"] == ok_count


def test_sync_export_audio_writes_sidecars(workspace, fake_drive):
    """Manually-created AudioLibraryEntry → export writes a fresh sidecar."""
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "abc.mp3", b"x", "audio/mpeg",
    )
    AudioLibraryEntry.objects.create(
        workspace=workspace, hash="abc",
        drive_id="fake-id-abc",
        voice_id="v", model="m", text="hi",
        duration_sec=2.5, generated_at="2026-05-15T00:00:00Z",
        status="ok",
    )
    counts = lib_sync.sync_export_audio(workspace)
    assert counts["written"] == 1

    sidecar = drive_mod.read_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO, "abc.json",
    )
    parsed = json.loads(sidecar.decode())
    assert parsed["voice_id"] == "v"
    assert parsed["duration_sec"] == 2.5
