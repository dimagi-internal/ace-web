"""API-level tests for /api/w/<slug>/videos/* endpoints.

Mirrors the workspace-gating + Pydantic-payload pattern used in
apps/opps/tests/test_api_v2.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


PROGRAM_YAML = """\
slug: demo
workspace: ws1
name: Demo Program
tagline: Test line.
manifest:
  alpha: gdrive:abc.mp4
scene:
  clips:
    - "@alpha"
product:
  beats:
    - asset: "@alpha"
      caption: "first"
"""


@pytest.fixture
def videos_root(tmp_path: Path, settings):
    root = tmp_path / "video-production" / "connect-videos"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "demo.yaml").write_text(PROGRAM_YAML, encoding="utf-8")
    built = root / "out" / "clip-explorer" / "demo"
    built.mkdir(parents=True)
    (built / "index.html").write_text(
        "<html><head></head><body><script>fetch('/edit');</script></body></html>",
        encoding="utf-8",
    )
    (built / "library.html").write_text(
        '<div class="lib-card"><h3>@alpha</h3></div></div>', encoding="utf-8",
    )
    (built / "media").mkdir()
    (built / "media" / "alpha.mp4").write_bytes(b"\x00fakebytes")
    settings.ACE_VIDEOS_ROOT = str(root)
    return root


@pytest.fixture
def member_client(db, client):
    creator = User.objects.create_user(email="creator@example.com")
    workspace = Workspace.objects.create(
        slug="ws1",
        display_name="WS1",
        drive_root_folder_id="folder-1",
        created_by=creator,
    )
    user = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client, workspace


@pytest.fixture
def non_member_client(db, client):
    creator = User.objects.create_user(email="creator2@example.com")
    Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1", created_by=creator,
    )
    user = User.objects.create_user(email="outsider@example.com")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_list_programs_returns_pydantic_payload(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["slug"] == "demo"
    assert body[0]["name"] == "Demo Program"
    assert body[0]["manifest_count"] == 1
    assert body[0]["has_explorer_build"] is True


@pytest.mark.django_db
def test_list_programs_404s_non_member(non_member_client, videos_root):
    resp = non_member_client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_programs_401_anonymous(db, client, videos_root):
    resp = client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_get_program_includes_explorer_url(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["explorer_url"] == "/api/w/ws1/videos/programs/demo/explorer.html"
    assert body["yaml_path"].endswith("programs/demo.yaml")


@pytest.mark.django_db
def test_get_program_404_unknown(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/nope")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_program_404_invalid_slug(member_client, videos_root):
    client, _ = member_client
    # ../ in the slug must be rejected before any FS access.
    resp = client.get("/api/w/ws1/videos/programs/..%2Fetc")
    assert resp.status_code in {400, 404}


@pytest.mark.django_db
def test_library_endpoint_returns_entries(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/library.json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["entries"][0]["alias"] == "alpha"


@pytest.mark.django_db
def test_explorer_html_rewrites_paths(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/explorer.html")
    assert resp.status_code == 200, resp.content
    assert resp["Content-Type"].startswith("text/html")
    assert resp["X-Frame-Options"] == "SAMEORIGIN"
    body = resp.content.decode()
    assert "fetch('edit'" in body
    assert "X-CSRFToken" in body


@pytest.mark.django_db
def test_explorer_html_404_missing_build(member_client, videos_root):
    # Remove the built index.html — endpoint must 404 with a helpful detail.
    (videos_root / "out" / "clip-explorer" / "demo" / "index.html").unlink()
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/explorer.html")
    assert resp.status_code == 404
    body = resp.json()
    assert "build-clip-explorer" in (body.get("detail") or "")


@pytest.mark.django_db
def test_media_endpoint_serves_bytes(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/media/alpha.mp4")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "video/mp4"


@pytest.mark.django_db
def test_media_endpoint_rejects_traversal(member_client, videos_root):
    client, _ = member_client
    # `..%2F` is rejected by Django's URL resolver path-segment matching.
    resp = client.get("/api/w/ws1/videos/programs/demo/media/..%2Fdemo.yaml")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_post_edit_triggers_rerender_and_mutates_yaml(member_client, videos_root):
    client, _ = member_client
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    fake_redis.get.return_value = None
    with mock.patch("apps.videos.service._get_redis", return_value=fake_redis), \
         mock.patch("apps.videos.service.subprocess.Popen") as popen:
        resp = client.post(
            "/api/w/ws1/videos/programs/demo/edit",
            data={"op": "set-narration", "beatId": "intro", "text": "Hi"},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["ok"] is True
    assert body["rerender_triggered"] is True
    assert popen.call_count == 1
    raw = (videos_root / "programs" / "demo.yaml").read_text(encoding="utf-8")
    assert "intro: Hi" in raw


@pytest.mark.django_db
def test_post_edit_400_on_bad_op(member_client, videos_root):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/edit",
        data={"op": "set-clip-start", "kind": "product-beat", "index": 99, "start_seconds": 1.0},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_feedback_get_post_roundtrip(member_client, videos_root):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/feedback",
        data={"scope": "global", "note": "this is a test"},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    resp = client.get("/api/w/ws1/videos/programs/demo/feedback")
    assert resp.status_code == 200
    body = resp.json()
    assert "this is a test" in body["markdown"]


@pytest.mark.django_db
def test_render_status_reads_redis(member_client, videos_root):
    client, _ = member_client
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: "1" if k.endswith(":busy") else "2026-05-14T17:00:00+00:00"
    with mock.patch("apps.videos.service._get_redis", return_value=fake_redis):
        resp = client.get("/api/w/ws1/videos/programs/demo/render-status")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["busy"] is True
    assert body["program_slug"] == "demo"
    assert body["started_at"] == "2026-05-14T17:00:00+00:00"
