"""Tests for the Phase 8/9 management commands.

Covers:
  - videos_backfill_audio_sidecars: reconstructs <hash>.json from spec narration
  - videos_relocate_existing_content: moves existing_content/* into library + shared
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive_mod, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, root_id=client.folder_id("ws-root"))


@pytest.fixture
def workspace(fake_drive, db):
    from django.contrib.auth import get_user_model

    from apps.workspaces.models import Workspace
    User = get_user_model()
    creator = User.objects.create_user(email="creator@example.com")
    return Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id=fake_drive.root_id,
        created_by=creator,
    )


def _cache_key(text: str, voice_id: str, model: str) -> str:
    return hashlib.sha256(
        f"{voice_id}::{model}::{text}".encode()
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# videos_backfill_audio_sidecars
# ---------------------------------------------------------------------------


def test_backfill_audio_sidecars_writes_for_reconstructable_hashes(
    workspace, fake_drive,
):
    layout = service_mod.layout_for(workspace)[0]

    # Seed one spec under a program with one beat of narration.
    spec_yaml = (
        "name: Demo\n"
        "voice:\n"
        "  voice_id: voiceA\n"
        "  model: modelB\n"
        "narration:\n"
        "  by_beat:\n"
        "    hook: \"Hello world.\"\n"
    )
    drive_mod.write_spec(layout, fake_drive.client, "demo", "run-001", spec_yaml)

    # The cache key for that synthesis:
    key = _cache_key("Hello world.", "voiceA", "modelB")
    # Orphan mp3 with no sidecar
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.mp3", b"mp3", "audio/mpeg",
    )

    call_command("videos_backfill_audio_sidecars", "--workspace", workspace.slug)

    # Sidecar exists now
    raw = drive_mod.read_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.json",
    )
    assert raw is not None
    parsed = json.loads(raw.decode())
    assert parsed["voice_id"] == "voiceA"
    assert parsed["model"] == "modelB"
    assert parsed["text"] == "Hello world."


def test_backfill_skips_already_sidecared(workspace, fake_drive):
    layout = service_mod.layout_for(workspace)[0]
    key = _cache_key("X", "V", "M")
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.mp3", b"mp3", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_AUDIO,
        f"{key}.json",
        json.dumps({
            "voice_id": "V", "model": "M", "text": "X",
            "duration_sec": None, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )
    # No-op (no orphan to backfill)
    call_command("videos_backfill_audio_sidecars", "--workspace", workspace.slug)


# ---------------------------------------------------------------------------
# videos_relocate_existing_content
# ---------------------------------------------------------------------------


def test_relocate_moves_audio_and_shared(workspace, fake_drive):
    """Files move from existing_content/{audio,shared} to library/audio + shared."""
    layout = service_mod.layout_for(workspace)[0]

    # Seed legacy paths
    drive_mod.upload_existing_content(
        layout, fake_drive.client, drive_mod.EXISTING_CONTENT_AUDIO,
        "deadbeef.mp3", b"audio", "audio/mpeg",
    )
    drive_mod.upload_existing_content(
        layout, fake_drive.client, drive_mod.EXISTING_CONTENT_SHARED,
        "music-bed.mp3", b"music", "audio/mpeg",
    )

    call_command("videos_relocate_existing_content", "--workspace", workspace.slug)

    # New paths should have the files
    new_audio_files = {f.name for f in drive_mod.list_audio_library_files(layout, fake_drive.client)}
    new_shared_files = {f.name for f in drive_mod.list_shared_top_files(layout, fake_drive.client)}
    assert "deadbeef.mp3" in new_audio_files
    assert "music-bed.mp3" in new_shared_files

    # Legacy paths should be empty
    legacy_audio = drive_mod.list_existing_content(layout, fake_drive.client, drive_mod.EXISTING_CONTENT_AUDIO)
    legacy_shared = drive_mod.list_existing_content(layout, fake_drive.client, drive_mod.EXISTING_CONTENT_SHARED)
    assert [f.name for f in legacy_audio] == []
    assert [f.name for f in legacy_shared] == []


def test_relocate_is_idempotent(workspace, fake_drive):
    """Re-running after a successful relocation is a no-op."""
    layout = service_mod.layout_for(workspace)[0]
    drive_mod.upload_existing_content(
        layout, fake_drive.client, drive_mod.EXISTING_CONTENT_AUDIO,
        "x.mp3", b"x", "audio/mpeg",
    )
    call_command("videos_relocate_existing_content", "--workspace", workspace.slug)
    # Second run should not crash and should leave the state as-is
    call_command("videos_relocate_existing_content", "--workspace", workspace.slug)
    new_audio_files = {f.name for f in drive_mod.list_audio_library_files(layout, fake_drive.client)}
    assert "x.mp3" in new_audio_files
