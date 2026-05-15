"""Tests for ``apps.videos.library.refs``.

Parses + resolves ``library:<media>/[<subfolder>/]<filename>`` refs. As
of the DB pivot, resolution hits the DB-backed library tables rather
than walking Drive — tests sync first, then resolve.
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import refs, sync as lib_sync
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


def test_parse_library_ref_video():
    parsed = refs.parse_library_ref("library:video/uganda-field/drone-wide.mp4")
    assert parsed.media == "video"
    assert parsed.subfolder == "uganda-field"
    assert parsed.filename == "drone-wide.mp4"


def test_parse_library_ref_audio_flat():
    parsed = refs.parse_library_ref("library:audio/deadbeef.mp3")
    assert parsed.media == "audio"
    assert parsed.subfolder is None
    assert parsed.filename == "deadbeef.mp3"


def test_parse_library_ref_rejects_malformed():
    with pytest.raises(refs.LibraryRefError):
        refs.parse_library_ref("library:nope/x/y")
    with pytest.raises(refs.LibraryRefError):
        refs.parse_library_ref("gdrive:abc")
    with pytest.raises(refs.LibraryRefError):
        refs.parse_library_ref("library:video/")


def test_resolve_library_ref_returns_drive_id(workspace, fake_drive):
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_id = drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO,
        "x.mp4", b"x", "video/mp4", subfolder="cat",
    )
    drive_mod.upload_library_file(
        layout, fake_drive, drive_mod.LIBRARY_VIDEO,
        "x.json", json.dumps({"name": "X", "tags": []}).encode(),
        "application/json", subfolder="cat",
    )
    lib_sync.sync_import_video(workspace)

    resolved = refs.resolve_library_ref(workspace, "library:video/cat/x.mp4")
    assert resolved is not None
    assert resolved.drive_id == drive_id


def test_resolve_library_ref_resolves_audio_by_hash(workspace, fake_drive):
    """Audio refs carry ``<hash>.mp3``; resolution strips the extension
    to look up by hash."""
    layout = service_mod.layout_for(workspace, client=fake_drive)[0]
    drive_id = drive_mod.upload_library_file(
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
    lib_sync.sync_import_audio(workspace)
    resolved = refs.resolve_library_ref(workspace, "library:audio/abc.mp3")
    assert resolved is not None
    assert resolved.drive_id == drive_id


def test_resolve_library_ref_missing_returns_none(workspace, fake_drive):
    assert refs.resolve_library_ref(workspace, "library:video/none/missing.mp4") is None


def test_is_library_ref():
    assert refs.is_library_ref("library:video/x/y.mp4")
    assert refs.is_library_ref("library:audio/z.mp3")
    assert not refs.is_library_ref("gdrive:abc.mp4")
    assert not refs.is_library_ref("file:x.mp4")
