"""Tests for the ``videos_sync_library`` management command."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.videos.models import VideoLibraryEntry
from apps.workspaces.models import Workspace

User = get_user_model()


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws-root": {}})
    monkeypatch.setattr(drive_mod, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, root_id=client.folder_id("ws-root"))


@pytest.fixture
def workspace(db, fake_drive):
    creator = User.objects.create_user(email="creator@example.com")
    return Workspace.objects.create(
        slug="dimagi-team", display_name="Dimagi",
        drive_root_folder_id=fake_drive.root_id,
        created_by=creator,
    )


def _seed_video(workspace, fake_drive):
    layout = service_mod.layout_for(workspace, client=fake_drive.client)[0]
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "x.mp4", b"x", "video/mp4", subfolder="cat",
    )
    drive_mod.upload_library_file(
        layout, fake_drive.client, drive_mod.LIBRARY_VIDEO,
        "x.json", json.dumps({"name": "X", "tags": []}).encode(),
        "application/json", subfolder="cat",
    )


def test_command_import_creates_rows(workspace, fake_drive):
    _seed_video(workspace, fake_drive)
    call_command("videos_sync_library", "--workspace", workspace.slug)
    assert VideoLibraryEntry.objects.filter(workspace=workspace).count() == 1


def test_command_default_direction_is_import(workspace, fake_drive):
    _seed_video(workspace, fake_drive)
    call_command("videos_sync_library", "--workspace", workspace.slug, "--direction", "import")
    assert VideoLibraryEntry.objects.filter(workspace=workspace).count() == 1


def test_command_direction_both_runs_import_then_export(workspace, fake_drive):
    _seed_video(workspace, fake_drive)
    call_command("videos_sync_library", "--workspace", workspace.slug, "--direction", "both")
    assert VideoLibraryEntry.objects.filter(workspace=workspace).count() == 1


def test_command_unknown_workspace_errors(db):
    with pytest.raises(CommandError):
        call_command("videos_sync_library", "--workspace", "no-such-ws")
