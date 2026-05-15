"""Tests for the /api/w/<slug>/videos/library/{video,audio} endpoints."""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import cache as cache_mod
from apps.videos import drive as drive_mod
from apps.videos import service as service_mod
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


@pytest.fixture
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws1-drive-root": {}})
    monkeypatch.setattr(drive_mod, "client_for_workspace", lambda ws: client)
    return client


@pytest.fixture
def member_client(db, client, fake_drive):
    creator = User.objects.create_user(email="creator@example.com")
    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1",
        drive_root_folder_id=fake_drive.folder_id("ws1-drive-root"),
        created_by=creator,
    )
    user = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    # Library cache leaks across tests within a process — clear for isolation.
    cache_mod.invalidate_lib_video(workspace.slug)
    cache_mod.invalidate_lib_audio(workspace.slug)
    return client, workspace


@pytest.fixture
def non_member_client(db, client, fake_drive):
    creator = User.objects.create_user(email="creator2@example.com")
    Workspace.objects.create(
        slug="ws1", display_name="WS1",
        drive_root_folder_id=fake_drive.folder_id("ws1-drive-root"),
        created_by=creator,
    )
    user = User.objects.create_user(email="outsider@example.com")
    client.force_login(user)
    return client


def _seed_video_lib(workspace, fake_drive_client):
    layout = service_mod.layout_for(workspace, client=fake_drive_client)[0]
    drive_mod.upload_library_file(
        layout, fake_drive_client, drive_mod.LIBRARY_VIDEO,
        "drone.mp4", b"a", "video/mp4", subfolder="uganda",
    )
    drive_mod.upload_library_file(
        layout, fake_drive_client, drive_mod.LIBRARY_VIDEO,
        "drone.json",
        json.dumps({"name": "Drone", "tags": ["uganda"]}).encode(),
        "application/json", subfolder="uganda",
    )


def _seed_audio_lib(workspace, fake_drive_client):
    layout = service_mod.layout_for(workspace, client=fake_drive_client)[0]
    drive_mod.upload_library_file(
        layout, fake_drive_client, drive_mod.LIBRARY_AUDIO,
        "abc.mp3", b"a", "audio/mpeg",
    )
    drive_mod.upload_library_file(
        layout, fake_drive_client, drive_mod.LIBRARY_AUDIO,
        "abc.json",
        json.dumps({
            "voice_id": "v", "model": "m", "text": "Hi",
            "duration_sec": 1.0, "generated_at": "2026-05-15T00:00:00Z",
        }).encode(),
        "application/json",
    )


@pytest.mark.django_db
def test_get_video_library_returns_grouped_subfolders(member_client, fake_drive):
    client, workspace = member_client
    _seed_video_lib(workspace, fake_drive)
    resp = client.get(f"/api/w/{workspace.slug}/videos/library/video")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body["subfolders"]) == 1
    assert body["subfolders"][0]["subfolder"] == "uganda"
    items = body["subfolders"][0]["items"]
    assert items[0]["status"] == "ok"
    assert items[0]["name"] == "Drone"
    assert items[0]["ref"] == "library:video/uganda/drone.mp4"


@pytest.mark.django_db
def test_get_audio_library_flat_list(member_client, fake_drive):
    client, workspace = member_client
    _seed_audio_lib(workspace, fake_drive)
    resp = client.get(f"/api/w/{workspace.slug}/videos/library/audio")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    items = body["items"]
    assert len(items) == 1
    assert items[0]["hash"] == "abc"
    assert items[0]["voice_id"] == "v"


@pytest.mark.django_db
def test_video_library_endpoint_404_for_non_member(non_member_client):
    resp = non_member_client.get("/api/w/ws1/videos/library/video")
    assert resp.status_code == 404


def test_library_endpoints_are_mcp_exposed():
    """Both new endpoints carry x-mcp-expose so the generator skill can call them."""
    from apps.api.api import api

    schema = api.get_openapi_schema()
    paths = schema["paths"]
    video_path = next(p for p in paths if p.endswith("/videos/library/video"))
    audio_path = next(p for p in paths if p.endswith("/videos/library/audio"))
    assert paths[video_path]["get"].get("x-mcp-expose") is True, (
        f"path {video_path} not MCP-exposed: {paths[video_path]['get']}"
    )
    assert paths[audio_path]["get"].get("x-mcp-expose") is True
