"""API-level tests for /api/w/<slug>/videos/* after the runs-model migration."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


SPEC_YAML = """\
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
    run = root / "programs" / "demo" / "runs" / "run-001"
    run.mkdir(parents=True)
    (run / "spec.yaml").write_text(SPEC_YAML, encoding="utf-8")
    exp = run / "explorer"
    exp.mkdir()
    (exp / "index.html").write_text(
        "<html><head></head><body><script>fetch('/edit');</script></body></html>",
        encoding="utf-8",
    )
    (exp / "library.html").write_text(
        '<div class="lib-card"><h3>@alpha</h3></div></div>', encoding="utf-8",
    )
    (exp / "media").mkdir()
    (exp / "media" / "alpha.mp4").write_bytes(b"\x00fakebytes")
    settings.ACE_VIDEOS_ROOT = str(root)
    return root


@pytest.fixture
def member_client(db, client):
    creator = User.objects.create_user(email="creator@example.com")
    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1", created_by=creator,
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
def test_list_programs(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == "demo"
    assert body[0]["latest_run_id"] == "run-001"
    assert body[0]["run_count"] == 1


@pytest.mark.django_db
def test_get_program_lists_runs(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["slug"] == "demo"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["run_id"] == "run-001"
    assert body["runs"][0]["has_explorer_build"] is True


@pytest.mark.django_db
def test_copy_run(member_client, videos_root):
    client, _ = member_client
    resp = client.post("/api/w/ws1/videos/programs/demo/runs", content_type="application/json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["new_run_id"] == "run-002"
    assert body["copied_from"] == "run-001"
    # Verify the new run exists on disk.
    assert (videos_root / "programs" / "demo" / "runs" / "run-002" / "spec.yaml").exists()


@pytest.mark.django_db
def test_get_run_detail(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["explorer_url"] == "/api/w/ws1/videos/programs/demo/runs/run-001/explorer.html"
    assert body["run_id"] == "run-001"


@pytest.mark.django_db
def test_get_run_404_unknown_run(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-999")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_run_404_invalid_run_format(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/notarun")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_explorer_html_serves_with_dark_theme(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/explorer.html")
    assert resp.status_code == 200, resp.content
    body = resp.content.decode()
    assert "ace-web-dark-theme" in body
    assert "fetch('edit'" in body
    assert resp["X-Frame-Options"] == "SAMEORIGIN"


@pytest.mark.django_db
def test_media_serves_bytes(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/media/alpha.mp4")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "video/mp4"


@pytest.mark.django_db
def test_media_traversal_rejected(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/media/..%2Fspec.yaml")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_post_edit_saves_spec_without_triggering_render(member_client, videos_root):
    """POST /edit just saves the YAML — render is an explicit /build call.

    Splits the two so the operator can batch edits before paying the
    multi-second render cost.
    """
    client, _ = member_client
    with mock.patch("apps.videos.service.subprocess.Popen") as popen:
        resp = client.post(
            "/api/w/ws1/videos/programs/demo/runs/run-001/edit",
            data={"op": "set-narration", "beatId": "intro", "text": "Hi"},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["ok"] is True
    assert body["rerender_triggered"] is False
    assert popen.call_count == 0  # save only, no subprocess
    raw = (videos_root / "programs" / "demo" / "runs" / "run-001" / "spec.yaml").read_text()
    assert "intro: Hi" in raw


@pytest.mark.django_db
def test_post_build_render_mode(member_client, videos_root):
    client, _ = member_client
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch("apps.videos.service._get_redis", return_value=fake_redis), \
         mock.patch("apps.videos.service.subprocess.Popen") as popen:
        resp = client.post(
            "/api/w/ws1/videos/programs/demo/runs/run-001/build",
            data={"mode": "render"},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["triggered"] is True
    chain = popen.call_args[0][0][2]
    assert "npm run render -- --program=demo --run=run-001 --draft" in chain


@pytest.mark.django_db
def test_post_build_build_only_mode(member_client, videos_root):
    client, _ = member_client
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch("apps.videos.service._get_redis", return_value=fake_redis), \
         mock.patch("apps.videos.service.subprocess.Popen") as popen:
        resp = client.post(
            "/api/w/ws1/videos/programs/demo/runs/run-001/build",
            data={"mode": "build-only"},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    chain = popen.call_args[0][0][2]
    assert "npm run render" not in chain
    assert "build-clip-explorer -- --program=demo --run=run-001" in chain


@pytest.mark.django_db
def test_render_status_reads_redis(member_client, videos_root):
    client, _ = member_client
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: "1" if k.endswith(":busy") else "2026-05-15T01:00:00+00:00"
    with mock.patch("apps.videos.service._get_redis", return_value=fake_redis):
        resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/render-status")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["busy"] is True
    assert body["run_id"] == "run-001"


@pytest.mark.django_db
def test_feedback_get_post_roundtrip(member_client, videos_root):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/feedback",
        data={"scope": "global", "note": "this is a test"},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/feedback")
    assert resp.status_code == 200
    body = resp.json()
    assert "this is a test" in body["markdown"]


@pytest.mark.django_db
def test_list_programs_404_non_member(non_member_client, videos_root):
    resp = non_member_client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Templates + create-program (agent-driven flow)
# ---------------------------------------------------------------------------


def _seed_template(root: Path) -> None:
    t = root / "templates" / "60s-campaign-overview"
    t.mkdir(parents=True)
    (t / "template.yaml").write_text(
        "id: 60s-campaign-overview\nname: 60s\ndescription: test\n"
        "expected_duration_seconds: 60\nintended_audience: x\nwhen_to_use: y\n",
        encoding="utf-8",
    )
    (t / "spec.template.yaml").write_text("slug: \"{{slug}}\"\nworkspace: \"{{ws}}\"\n", encoding="utf-8")
    (t / "generate.prompt.md").write_text("# Skill prompt\nFill it.\n", encoding="utf-8")


@pytest.mark.django_db
def test_list_templates(member_client, videos_root):
    client, _ = member_client
    _seed_template(videos_root)
    resp = client.get("/api/w/ws1/videos/templates")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "60s-campaign-overview"
    assert body[0]["expected_duration_seconds"] == 60


@pytest.mark.django_db
def test_get_template_bundle(member_client, videos_root):
    client, _ = member_client
    _seed_template(videos_root)
    resp = client.get("/api/w/ws1/videos/templates/60s-campaign-overview")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["meta"]["id"] == "60s-campaign-overview"
    assert "Skill prompt" in body["prompt_md"]
    assert "{{slug}}" in body["skeleton_yaml"]


@pytest.mark.django_db
def test_get_template_404(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/templates/nonexistent")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_program_happy_path(member_client, videos_root):
    client, _ = member_client
    spec = (
        "slug: new-prog\n"
        "workspace: ws1\n"
        "name: New Program\n"
        "country_focus: Test Country\n"
    )
    resp = client.post(
        "/api/w/ws1/videos/programs",
        data={"slug": "new-prog", "spec_yaml": spec},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["program_slug"] == "new-prog"
    assert body["run_id"] == "run-001"
    assert (videos_root / "programs" / "new-prog" / "runs" / "run-001" / "spec.yaml").exists()


@pytest.mark.django_db
def test_create_program_409_when_slug_taken(member_client, videos_root):
    client, _ = member_client
    spec = "slug: demo\nworkspace: ws1\nname: Demo\n"
    resp = client.post(
        "/api/w/ws1/videos/programs",
        data={"slug": "demo", "spec_yaml": spec},
        content_type="application/json",
    )
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_create_program_400_workspace_mismatch(member_client, videos_root):
    client, _ = member_client
    spec = "slug: x\nworkspace: other-ws\nname: X\n"
    resp = client.post(
        "/api/w/ws1/videos/programs",
        data={"slug": "x", "spec_yaml": spec},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_program_400_slug_mismatch(member_client, videos_root):
    client, _ = member_client
    spec = "slug: in-yaml\nworkspace: ws1\nname: X\n"
    resp = client.post(
        "/api/w/ws1/videos/programs",
        data={"slug": "in-url", "spec_yaml": spec},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_program_400_invalid_slug(member_client, videos_root):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs",
        data={"slug": "../evil", "spec_yaml": "slug: x\nworkspace: ws1\n"},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_list_templates_401_anonymous(db, client, videos_root):
    resp = client.get("/api/w/ws1/videos/templates")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_programs_401_anonymous(db, client, videos_root):
    resp = client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 401
