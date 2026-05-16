"""Tests for ``publish_audio_library_from_local`` and its integration
into ``publish_render_artifacts``.

The renderer writes ``<hash>.mp3`` + ``<hash>.json`` pairs to
``<videos_root>/assets/audio/`` during synthesis. The publish step
uploads any pairs not already in Drive's ``library/audio/`` and refreshes
the corresponding ``AudioLibraryEntry`` rows.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, service
from apps.videos.models import AudioLibraryEntry
from apps.workspaces.models import Workspace

User = get_user_model()


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, root_id=client.folder_id("ws-root"))


@pytest.fixture
def workspace(db, fake_drive):
    creator = User.objects.create_user(email="creator@example.com")
    return Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi",
        drive_root_folder_id=fake_drive.root_id,
        created_by=creator,
    )


@pytest.fixture
def videos_root(tmp_path, settings):
    root = tmp_path / "video-production" / "connect-videos"
    root.mkdir(parents=True)
    settings.ACE_VIDEOS_ROOT = str(root)
    return root


def _seed_local_audio(videos_root, hash_: str, sidecar: dict | None = None):
    audio_dir = videos_root / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / f"{hash_}.mp3").write_bytes(b"\xff\xfb" + hash_.encode())
    if sidecar is not None:
        (audio_dir / f"{hash_}.json").write_text(json.dumps(sidecar))


def test_publish_uploads_new_audio_pair(workspace, fake_drive, videos_root):
    _seed_local_audio(videos_root, "abc123", {
        "voice_id": "v1", "model": "m1", "text": "Hello.",
        "duration_sec": 1.2, "generated_at": "2026-05-15T00:00:00Z",
    })
    counts = service.publish_audio_library_from_local(workspace)
    assert counts == {"uploaded_mp3": 1, "uploaded_json": 1, "db_created": 1, "db_updated": 0}

    layout, client = service.layout_for(workspace)
    drive_names = {f.name for f in drive.list_audio_library_files(layout, client)}
    assert "abc123.mp3" in drive_names
    assert "abc123.json" in drive_names

    row = AudioLibraryEntry.objects.get(workspace=workspace, hash="abc123")
    assert row.voice_id == "v1"
    assert row.text == "Hello."


def test_publish_skips_when_drive_already_has_pair(workspace, fake_drive, videos_root):
    _seed_local_audio(videos_root, "abc123", {
        "voice_id": "v", "model": "m", "text": "x",
        "duration_sec": None, "generated_at": "2026-05-15T00:00:00Z",
    })
    service.publish_audio_library_from_local(workspace)
    counts2 = service.publish_audio_library_from_local(workspace)
    assert counts2 == {"uploaded_mp3": 0, "uploaded_json": 0, "db_created": 0, "db_updated": 0}


def test_publish_handles_orphan_sidecar_locally(workspace, fake_drive, videos_root):
    """If a local <hash>.json exists without an <hash>.mp3, skip it
    entirely — we never push orphan sidecars."""
    audio_dir = videos_root / "assets" / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "orphan.json").write_text("{}")
    counts = service.publish_audio_library_from_local(workspace)
    assert counts == {"uploaded_mp3": 0, "uploaded_json": 0, "db_created": 0, "db_updated": 0}


def test_publish_uploads_mp3_even_without_sidecar(workspace, fake_drive, videos_root):
    """An <hash>.mp3 with no sidecar still gets uploaded; the row lands
    as missing-sidecar after the import."""
    _seed_local_audio(videos_root, "nosidecar")  # no JSON
    counts = service.publish_audio_library_from_local(workspace)
    assert counts["uploaded_mp3"] == 1
    assert counts["uploaded_json"] == 0
    row = AudioLibraryEntry.objects.get(workspace=workspace, hash="nosidecar")
    assert row.status == "missing-sidecar"


def test_publish_no_local_audio_dir_is_noop(workspace, fake_drive, videos_root):
    counts = service.publish_audio_library_from_local(workspace)
    assert counts == {"uploaded_mp3": 0, "uploaded_json": 0, "db_created": 0, "db_updated": 0}


def test_publish_render_artifacts_calls_audio_publish(workspace, fake_drive, videos_root):
    """End-to-end: a real publish_render_artifacts call also publishes
    audio sidecars sitting in local assets/audio/."""
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001",
        "slug: demo\nworkspace: dimagi-team\nname: Demo\n",
    )
    out = service.output_path("demo", "run-001")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x00\x01\x02fake-mp4")

    _seed_local_audio(videos_root, "audioA", {
        "voice_id": "v", "model": "m", "text": "ABC",
        "duration_sec": 0.5, "generated_at": "2026-05-15T00:00:00Z",
    })

    service.publish_render_artifacts(workspace, "demo", "run-001")

    layout, client = service.layout_for(workspace)
    drive_names = {f.name for f in drive.list_audio_library_files(layout, client)}
    assert "audioA.mp3" in drive_names
    assert AudioLibraryEntry.objects.filter(workspace=workspace, hash="audioA").exists()


def test_publish_render_artifacts_swallows_audio_failures(
    workspace, fake_drive, videos_root, monkeypatch,
):
    """Audio publish is best-effort: a failure must not break the main
    artifact publish."""
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001",
        "slug: demo\nworkspace: dimagi-team\nname: Demo\n",
    )
    out = service.output_path("demo", "run-001")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x00\x01\x02fake-mp4")

    def boom(*a, **kw):
        raise RuntimeError("simulated")

    monkeypatch.setattr(service, "publish_audio_library_from_local", boom)

    # Should not raise — main publish completes.
    result = service.publish_render_artifacts(workspace, "demo", "run-001")
    assert result.output_mp4_id is not None
