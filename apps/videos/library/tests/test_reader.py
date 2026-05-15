"""Tests for the workspace-scoped media library reader.

Walks Drive (videos/library/video/<subfolder>/ and videos/library/audio/),
pairs media files with their JSON sidecars by stem, surfaces orphans
via ``status != "ok"``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import reader


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive_mod, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, root_id=client.folder_id("ws-root"))


@pytest.fixture
def workspace(fake_drive):
    return SimpleNamespace(slug="dimagi-team", drive_root_folder_id=fake_drive.root_id)


@pytest.fixture
def seeded_video_library(workspace, fake_drive):
    """Seed library/video/uganda-field/ with one well-formed clip and one orphan."""
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "drone-wide.mp4", b"mp4-bytes", "video/mp4",
        subfolder="uganda-field",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "drone-wide.json",
        json.dumps({
            "name": "Drone — village wide",
            "description": "Sunrise push-in",
            "tags": ["drone", "wide", "uganda"],
        }).encode(),
        "application/json",
        subfolder="uganda-field",
    )
    # Orphan media (no sidecar)
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "orphan.mp4", b"mp4-bytes", "video/mp4",
        subfolder="uganda-field",
    )
    return layout


def test_list_video_library_pairs_media_and_sidecar(workspace, fake_drive, seeded_video_library):
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


def test_list_video_library_empty_when_no_library_folder(workspace, fake_drive):
    out = reader.list_video_library(workspace)
    assert out.subfolders == []


def test_list_audio_library_pairs_by_hash(workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "deadbeef.mp3", b"mp3-bytes", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        "deadbeef.json",
        json.dumps({
            "voice_id": "v1", "model": "m1", "text": "Hello",
            "duration_sec": 1.1, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )
    out = reader.list_audio_library(workspace)
    assert len(out.items) == 1
    item = out.items[0]
    assert item.hash == "deadbeef"
    assert item.status == "ok"
    assert item.voice_id == "v1"
    assert item.text == "Hello"
    assert item.duration_sec == 1.1


def test_list_video_library_uses_cache(workspace, fake_drive, seeded_video_library, monkeypatch):
    """Second call within TTL doesn't re-hit Drive."""
    from apps.videos import drive as drive_mod

    real_list_subfolders = drive_mod.list_library_subfolders
    call_count = {"n": 0}

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return real_list_subfolders(*args, **kwargs)

    monkeypatch.setattr(drive_mod, "list_library_subfolders", counting)

    reader.list_video_library(workspace)
    reader.list_video_library(workspace)
    assert call_count["n"] == 1, "second call must hit cache"
