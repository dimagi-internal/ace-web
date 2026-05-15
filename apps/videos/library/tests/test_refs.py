"""Tests for ``apps.videos.library.refs``.

Parses + resolves ``library:<media>/[<subfolder>/]<filename>`` refs against
a FakeDriveClient-backed workspace.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.library import refs


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive_mod, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, root_id=client.folder_id("ws-root"))


@pytest.fixture
def workspace(fake_drive):
    return SimpleNamespace(slug="dimagi-team", drive_root_folder_id=fake_drive.root_id)


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
    layout = service_mod.layout_for(workspace)[0]
    drive_id = drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "x.mp4", b"x", "video/mp4", subfolder="cat",
    )
    resolved = refs.resolve_library_ref(workspace, "library:video/cat/x.mp4")
    assert resolved is not None
    assert resolved.drive_id == drive_id


def test_resolve_library_ref_missing_returns_none(workspace, fake_drive):
    assert refs.resolve_library_ref(workspace, "library:video/none/missing.mp4") is None


def test_is_library_ref():
    assert refs.is_library_ref("library:video/x/y.mp4")
    assert refs.is_library_ref("library:audio/z.mp3")
    assert not refs.is_library_ref("gdrive:abc.mp4")
    assert not refs.is_library_ref("file:x.mp4")
