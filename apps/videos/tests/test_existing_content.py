"""Tests for the existing_content/ Drive surface + render-time hydration.

Covers:
  - drive.upload_existing_content / read_existing_content / list_existing_content
  - service.upload_existing_content / read_existing_content / list_existing_content
  - service.stage_existing_content_locally (Drive → local)
  - Idempotent re-uploads
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, service


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, root_id=client.folder_id("ws-root"))


@pytest.fixture
def workspace(fake_drive):
    return SimpleNamespace(slug="dimagi-team", drive_root_folder_id=fake_drive.root_id)


@pytest.fixture
def videos_root(tmp_path, settings):
    root = tmp_path / "video-production" / "connect-videos"
    root.mkdir(parents=True)
    settings.ACE_VIDEOS_ROOT = str(root)
    return root


# ---------------------------------------------------------------------------
# drive.* primitives
# ---------------------------------------------------------------------------


def test_upload_and_read_audio_roundtrip(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    payload = b"\x00\x01\x02fake-mp3-bytes"
    file_id = drive.upload_existing_content(
        layout, fake_drive.client, "audio", "abc123.mp3", payload, "audio/mpeg",
    )
    assert file_id
    fetched = drive.read_existing_content(layout, fake_drive.client, "audio", "abc123.mp3")
    assert fetched == payload


def test_upload_replaces_existing_file(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.upload_existing_content(
        layout, fake_drive.client, "shared", "music-bed.mp3", b"old", "audio/mpeg",
    )
    drive.upload_existing_content(
        layout, fake_drive.client, "shared", "music-bed.mp3", b"new", "audio/mpeg",
    )
    fetched = drive.read_existing_content(layout, fake_drive.client, "shared", "music-bed.mp3")
    assert fetched == b"new"


def test_list_existing_content_returns_size(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.upload_existing_content(
        layout, fake_drive.client, "audio", "a.mp3", b"123", "audio/mpeg",
    )
    drive.upload_existing_content(
        layout, fake_drive.client, "audio", "b.mp3", b"1234567", "audio/mpeg",
    )
    files = drive.list_existing_content(layout, fake_drive.client, "audio")
    by_name = {f.name: f for f in files}
    assert by_name.keys() == {"a.mp3", "b.mp3"}
    assert by_name["a.mp3"].size_bytes == 3
    assert by_name["b.mp3"].size_bytes == 7


def test_list_existing_content_empty_when_folder_missing(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    assert drive.list_existing_content(layout, fake_drive.client, "audio") == []


def test_unknown_subdir_raises(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    with pytest.raises(ValueError, match="Unknown existing_content subdir"):
        drive.existing_content_folder_id(layout, fake_drive.client, "evil")


def test_list_program_slugs_excludes_existing_content(workspace, fake_drive):
    """list_program_slugs already filters this folder — sanity check after
    upload populates it."""
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.upload_existing_content(
        layout, fake_drive.client, "audio", "a.mp3", b"x", "audio/mpeg",
    )
    # Now add a real program for contrast.
    drive.write_spec(
        layout, fake_drive.client, "demo", "run-001",
        "slug: demo\nworkspace: dimagi-team\n",
    )
    assert drive.list_program_slugs(layout, fake_drive.client) == ["demo"]


# ---------------------------------------------------------------------------
# service.* wrappers
# ---------------------------------------------------------------------------


def test_service_upload_and_list(workspace, fake_drive):
    drive.resolve_layout(workspace, fake_drive.client)  # materialize layout
    service.upload_existing_content(workspace, "audio", "x.mp3", b"hi", "audio/mpeg")
    items = service.list_existing_content(workspace, "audio")
    assert len(items) == 1
    assert items[0].filename == "x.mp3"
    assert items[0].size_bytes == 2


def test_service_rejects_path_traversal(workspace, fake_drive):
    with pytest.raises(ValueError, match="Invalid filename"):
        service.upload_existing_content(
            workspace, "audio", "../evil.mp3", b"x", "audio/mpeg",
        )
    with pytest.raises(ValueError, match="Invalid filename"):
        service.upload_existing_content(
            workspace, "audio", ".hidden", b"x", "audio/mpeg",
        )


def test_service_rejects_unknown_subdir(workspace, fake_drive):
    with pytest.raises(ValueError, match="Unknown existing_content subdir"):
        service.upload_existing_content(
            workspace, "evil", "x.mp3", b"x", "audio/mpeg",
        )


def test_service_read_returns_none_for_unknown(workspace, fake_drive):
    drive.resolve_layout(workspace, fake_drive.client)
    assert service.read_existing_content(workspace, "audio", "missing.mp3") is None


# ---------------------------------------------------------------------------
# stage_existing_content_locally — render-time hydration
# ---------------------------------------------------------------------------


def test_stage_pulls_from_drive_into_assets_layout(workspace, fake_drive, videos_root):
    # Seed Drive with one audio + one shared file.
    service.upload_existing_content(workspace, "audio", "narr.mp3", b"audio-bytes", "audio/mpeg")
    service.upload_existing_content(workspace, "shared", "music.mp3", b"music-bytes", "audio/mpeg")

    counts = service.stage_existing_content_locally(workspace)

    assert counts == {"audio": 1, "shared": 1}
    assert (videos_root / "assets" / "audio" / "narr.mp3").read_bytes() == b"audio-bytes"
    assert (videos_root / "assets" / "shared" / "music.mp3").read_bytes() == b"music-bytes"


def test_stage_skips_files_already_local_with_same_size(workspace, fake_drive, videos_root):
    service.upload_existing_content(workspace, "audio", "x.mp3", b"abc", "audio/mpeg")

    # Pre-create a local file with matching size — should skip.
    local_dir = videos_root / "assets" / "audio"
    local_dir.mkdir(parents=True)
    local_file = local_dir / "x.mp3"
    local_file.write_bytes(b"abc")

    counts = service.stage_existing_content_locally(workspace)
    assert counts["audio"] == 0
    # File untouched.
    assert local_file.read_bytes() == b"abc"


def test_stage_re_downloads_when_size_mismatches(workspace, fake_drive, videos_root):
    service.upload_existing_content(workspace, "audio", "x.mp3", b"updated-content", "audio/mpeg")
    local_dir = videos_root / "assets" / "audio"
    local_dir.mkdir(parents=True)
    (local_dir / "x.mp3").write_bytes(b"old")  # size mismatch

    counts = service.stage_existing_content_locally(workspace)
    assert counts["audio"] == 1
    assert (local_dir / "x.mp3").read_bytes() == b"updated-content"


def test_stage_creates_empty_subdirs_when_drive_is_empty(workspace, fake_drive, videos_root):
    counts = service.stage_existing_content_locally(workspace)
    assert counts == {"audio": 0, "shared": 0}
    assert (videos_root / "assets" / "audio").is_dir()
    assert (videos_root / "assets" / "shared").is_dir()


# ---------------------------------------------------------------------------
# Render triggers stage existing_content alongside spec.yaml
# ---------------------------------------------------------------------------


def test_stage_existing_content_reads_from_library_audio_then_shared(workspace, fake_drive, videos_root):
    """When new library/audio/ has files, they land in local assets/audio/.
    When videos/shared/ has files, they land in local assets/shared/."""
    layout = service.layout_for(workspace)[0]

    # Seed new layout: one file in library/audio/ and one in shared/.
    drive.upload_library_file(
        layout, fake_drive.client, drive.LIBRARY_AUDIO,
        "deadbeef.mp3", b"audio-bytes", "audio/mpeg",
    )
    drive.upload_library_file(
        layout, fake_drive.client, drive.LIBRARY_AUDIO,
        "deadbeef.json", b'{"voice_id":"v","model":"m","text":"t","duration_sec":null,"generated_at":"2026-05-15T00:00:00Z"}',
        "application/json",
    )
    # Music bed in the new shared/ location.
    shared_id = drive.shared_top_folder_id(layout, fake_drive.client, create=True)
    fake_drive.client.upload_binary(shared_id, "music-bed.mp3", b"music", "audio/mpeg")

    counts = service.stage_existing_content_locally(workspace)
    # audio + shared both downloaded
    assert counts["audio"] >= 1
    assert counts["shared"] >= 1


def test_trigger_rerender_stages_existing_content(workspace, fake_drive, videos_root):
    """Bumping a render should pull all existing_content/ down so the
    Node toolchain finds audio + music bed on disk."""
    from unittest import mock

    # Seed Drive: spec + one audio + one shared file.
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001",
        "slug: demo\nworkspace: dimagi-team\n",
    )
    service.upload_existing_content(workspace, "audio", "narr.mp3", b"a", "audio/mpeg")
    service.upload_existing_content(workspace, "shared", "music.mp3", b"m", "audio/mpeg")

    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen"):
        ok = service.trigger_rerender(workspace, "demo", "run-001")

    assert ok is True
    assert (videos_root / "assets" / "audio" / "narr.mp3").read_bytes() == b"a"
    assert (videos_root / "assets" / "shared" / "music.mp3").read_bytes() == b"m"
