"""Tests for the workspace-scoped media library reader.

As of the DB-backed pivot the reader queries Postgres only; Drive is
walked by ``apps.videos.library.sync`` at sync time. Tests seed Drive,
run the sync, then assert the reader returns the right shape.
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import reader, sync as lib_sync
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
    """Seed library/video/uganda-field/ with one well-formed clip and one orphan."""
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


def test_list_video_library_pairs_media_and_sidecar(
    workspace, fake_drive, seeded_video_library,
):
    lib_sync.sync_import_video(workspace)
    out = reader.list_video_library(workspace)
    assert len(out.subfolders) == 1
    sub = out.subfolders[0]
    assert sub.subfolder == "uganda-field"
    names = sorted(i.filename for i in sub.items)
    assert names == ["drone-wide.mp4", "orphan.mp4"]
    by_name = {i.filename: i for i in sub.items}
    assert by_name["drone-wide.mp4"].status == "ok"
    assert by_name["drone-wide.mp4"].name == "Drone — village wide"
    assert by_name["drone-wide.mp4"].tags == ["drone", "wide", "uganda"]
    assert by_name["orphan.mp4"].status == "missing-sidecar"


def test_list_video_library_empty_when_no_rows(workspace, fake_drive):
    out = reader.list_video_library(workspace)
    assert out.subfolders == []


def test_list_audio_library_pairs_by_hash(workspace, fake_drive):
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "deadbeef.mp3", b"mp3-bytes", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_AUDIO,
        "deadbeef.json",
        json.dumps({
            "voice_id": "v1", "model": "m1", "text": "Hello",
            "duration_sec": 1.1, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )
    lib_sync.sync_import_audio(workspace)

    out = reader.list_audio_library(workspace)
    assert len(out.items) == 1
    item = out.items[0]
    assert item.hash == "deadbeef"
    assert item.status == "ok"
    assert item.voice_id == "v1"
    assert item.text == "Hello"
    assert item.duration_sec == 1.1


def test_reader_does_not_walk_drive(
    workspace, fake_drive, seeded_video_library, monkeypatch,
):
    """The reader must hit only the DB — never list Drive folders."""
    lib_sync.sync_import_video(workspace)

    def boom(*args, **kwargs):
        raise AssertionError("reader walked Drive — should be DB-only")

    monkeypatch.setattr(drive_mod, "list_library_subfolders", boom)
    monkeypatch.setattr(drive_mod, "list_library_files", boom)

    out = reader.list_video_library(workspace)
    assert len(out.subfolders) == 1
