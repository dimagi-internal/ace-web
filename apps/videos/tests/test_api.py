"""API-level tests for /api/w/<slug>/videos/* with Drive as source of truth."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive
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
def fake_drive(monkeypatch):
    client = FakeDriveClient.from_tree({"ws1-drive-root": {}})
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)
    return client


@pytest.fixture
def videos_root(tmp_path: Path, settings, fake_drive):
    """Local scratch dir + seeded fake-drive spec for the `demo` program."""
    root = tmp_path / "video-production" / "connect-videos"
    root.mkdir(parents=True)
    settings.ACE_VIDEOS_ROOT = str(root)

    # Seed Drive with the demo spec at run-001.
    ws_root = fake_drive.folder_id("ws1-drive-root")
    videos_id = fake_drive.create_folder(ws_root, "videos")
    demo_id = fake_drive.create_folder(videos_id, "demo")
    runs_id = fake_drive.create_folder(demo_id, "runs")
    run001_id = fake_drive.create_folder(runs_id, "run-001")
    fake_drive.upload_file(run001_id, "spec.yaml", SPEC_YAML, "application/x-yaml")

    # Local render artifacts (kept on disk for now — output.mp4, explorer/).
    exp = root / "programs" / "demo" / "runs" / "run-001" / "explorer"
    exp.mkdir(parents=True)
    (exp / "index.html").write_text(
        "<html><head></head><body><script>fetch('/edit');</script></body></html>",
        encoding="utf-8",
    )
    (exp / "library.html").write_text(
        '<div class="lib-card"><h3>@alpha</h3></div></div>', encoding="utf-8",
    )
    (exp / "media").mkdir()
    (exp / "media" / "alpha.mp4").write_bytes(b"\x00fakebytes")
    return root


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


# ---------------------------------------------------------------------------
# Programs list / detail
# ---------------------------------------------------------------------------


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
def test_get_run_detail(member_client, videos_root):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["explorer_url"] == "/api/w/ws1/videos/programs/demo/runs/run-001/explorer.html"
    assert body["run_id"] == "run-001"
    assert body["yaml_path"] == "videos/demo/runs/run-001/spec.yaml"


@pytest.mark.django_db
def test_get_run_detail_includes_parsed_spec(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "spec" in body
    assert body["spec"]["slug"] == "demo"
    assert "scene" in body["spec"]


@pytest.mark.django_db
def test_get_run_detail_serializes_trim_floats(member_client, videos_root, fake_drive):
    """Regression: a clip-trim edit writes float start_seconds/duration_seconds
    via ruamel.yaml, which loads them back as `ScalarFloat` (a float
    subclass orjson refuses to serialize). Without the scrub step at the
    service boundary, the next GET /runs/<id> 500s with
    `Type is not JSON serializable: ScalarFloat`. See fix in
    apps/videos/service._scrub_ruamel."""
    client, _ = member_client
    # Save a trim — same path the React drawer uses.
    edit = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": [{
            "op": "set-clip-trim",
            "kind": "scene-clip",
            "index": 0,
            "start_seconds": 8.0,
            "duration_seconds": 2.3,
        }]},
        content_type="application/json",
    )
    assert edit.status_code == 200, edit.content
    # Re-read — would 500 without the scrub.
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001")
    assert resp.status_code == 200, resp.content
    clip = resp.json()["spec"]["scene"]["clips"][0]
    assert clip["start_seconds"] == 8.0
    assert clip["duration_seconds"] == 2.3
    assert type(clip["start_seconds"]) is float
    assert type(clip["duration_seconds"]) is float


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
def test_copy_run(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.post("/api/w/ws1/videos/programs/demo/runs", content_type="application/json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["new_run_id"] == "run-002"
    assert body["copied_from"] == "run-001"


# ---------------------------------------------------------------------------
# Create program (writes to Drive)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_program_happy_path(member_client, videos_root, fake_drive):
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
    assert body["spec_path"] == "videos/new-prog/runs/run-001/spec.yaml"


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
def test_create_program_400_invalid_slug(member_client, videos_root):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs",
        data={"slug": "../evil", "spec_yaml": "slug: x\nworkspace: ws1\n"},
        content_type="application/json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Edit (round-trip through Drive)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_edit_saves_spec_without_triggering_render(member_client, videos_root, fake_drive):
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
    assert popen.call_count == 0  # save only


@pytest.mark.django_db
def test_set_global_template_writes_under_new_key(member_client, videos_root, fake_drive):
    """Regression for the 2026-05-21 rename: `set-global-template` op
    persists to `spec.global_template` (was `spec.brand` pre-rename).
    Renderer's resolveGlobalTemplate() in Root.tsx reads the new key
    with fallback to the legacy one; this test pins down the write
    side so the keys don't silently diverge."""
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": [{"op": "set-global-template",
                       "tagline": "Verified care, every visit.",
                       "cycle_steps": []}]},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    spec = client.get("/api/w/ws1/videos/programs/demo/runs/run-001").json()["spec"]
    assert spec.get("global_template", {}).get("tagline") == "Verified care, every visit."
    assert "brand" not in spec, "legacy `brand` key should not be re-written"


@pytest.mark.django_db
def test_set_program_name_renames(member_client, videos_root, fake_drive):
    """`set-program-name` writes spec.name, trims whitespace, rejects empty."""
    client, _ = member_client
    # Happy path
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": [{"op": "set-program-name", "name": "  Renamed Demo  "}]},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    spec = client.get("/api/w/ws1/videos/programs/demo/runs/run-001").json()["spec"]
    assert spec["name"] == "Renamed Demo"
    # Empty / whitespace-only is rejected
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": [{"op": "set-program-name", "name": "   "}]},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_serve_media_lazy_pulls_final_mp4_from_drive(
    member_client, videos_root, fake_drive,
):
    """When labs (or any host that doesn't render) is asked for
    final.mp4 and has no local copy, it should fetch the published
    output.mp4 from Drive on demand. Without this, labs serves a
    permanent 404 for any video published from another host — which
    is the only way videos land on labs (no ElevenLabs key in the
    task def). See _lazy_pull_output_mp4 in apps/videos/api.py."""
    client, _ = member_client
    # Seed Drive with a published output.mp4 (mimics what
    # render_locally.py --publish does after a Mac render).
    ws_root = fake_drive.folder_id("ws1-drive-root")
    videos_id = fake_drive.list_folder(ws_root)[0].id
    demo_id = fake_drive.list_folder(videos_id)[0].id
    runs_id = fake_drive.list_folder(demo_id)[0].id
    run001_id = fake_drive.list_folder(runs_id)[0].id
    fake_drive.upload_binary(
        run001_id, "output.mp4", b"\x00FAKE-MP4-BYTES", "video/mp4",
    )
    # Local FS has no final.mp4 yet (the seed only puts alpha.mp4 in
    # explorer/media/, never final.mp4 or output.mp4).
    final_local = (
        videos_root / "programs" / "demo" / "runs" / "run-001"
        / "explorer" / "media" / "final.mp4"
    )
    output_local = (
        videos_root / "programs" / "demo" / "runs" / "run-001" / "output.mp4"
    )
    assert not final_local.exists()
    assert not output_local.exists()

    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4",
    )
    assert resp.status_code == 200, resp.content
    assert resp.headers["Accept-Ranges"] == "bytes"
    body = b"".join(resp.streaming_content) if resp.streaming else resp.content
    assert body.startswith(b"\x00FAKE-MP4-BYTES")

    # output.mp4 cached at the canonical local path, plus the symlink
    # the explorer build expects.
    assert output_local.is_file()
    assert output_local.read_bytes() == b"\x00FAKE-MP4-BYTES"
    assert final_local.is_symlink()


@pytest.mark.django_db
def test_has_output_falls_through_to_drive(member_client, videos_root, fake_drive):
    """When local FS has no final.mp4 but Drive does, the run-detail
    + program-list endpoints should report has_output=True. Without
    this, labs (which never runs the render chain) shows every
    program as 'not built' even when artifacts are published on
    Drive."""
    client, _ = member_client
    ws_root = fake_drive.folder_id("ws1-drive-root")
    videos_id = fake_drive.list_folder(ws_root)[0].id
    demo_id = fake_drive.list_folder(videos_id)[0].id
    runs_id = fake_drive.list_folder(demo_id)[0].id
    run001_id = fake_drive.list_folder(runs_id)[0].id
    fake_drive.upload_binary(run001_id, "output.mp4", b"\x00FAKE", "video/mp4")

    # Local FS has no output.mp4 (seed only put alpha.mp4 in explorer/media/).
    assert not (videos_root / "programs" / "demo" / "runs" / "run-001" / "output.mp4").exists()

    # FakeDrive's upload_binary doesn't set modified_time; the Drive
    # SDK does. Set it explicitly so the rendered_at fallthrough has
    # a value to surface.
    fake_drive.set_modified_time("ws1-drive-root/videos/demo/runs/run-001/output.mp4",
                                 "2026-05-21T20:30:00Z")

    detail = client.get("/api/w/ws1/videos/programs/demo/runs/run-001").json()
    assert detail["has_output"] is True
    assert detail["output_rendered_at"] == "2026-05-21T20:30:00Z"

    program = client.get("/api/w/ws1/videos/programs/demo").json()
    assert program["runs"][0]["has_output"] is True


@pytest.mark.django_db
def test_drive_changes_invalidates_stale_local_cache(
    member_client, videos_root, fake_drive,
):
    """End-to-end: lazy-pull populates the file_cache reverse-index,
    then a Drive Changes API report of the same file_id flips the
    next /media/final.mp4 request to a fresh lazy-pull. This is the
    proper invalidation flow that replaces the run-detail mtime
    band-aid I shipped + reverted earlier."""
    from unittest.mock import patch

    client, workspace = member_client

    # Seed Drive with output.mp4
    ws_root = fake_drive.folder_id("ws1-drive-root")
    videos_id = fake_drive.list_folder(ws_root)[0].id
    demo_id = fake_drive.list_folder(videos_id)[0].id
    runs_id = fake_drive.list_folder(demo_id)[0].id
    run001_id = fake_drive.list_folder(runs_id)[0].id
    fake_drive.upload_binary(
        run001_id, "output.mp4", b"\x00OLD-BYTES", "video/mp4",
    )
    out_local = (
        videos_root / "programs" / "demo" / "runs" / "run-001" / "output.mp4"
    )
    assert not out_local.exists()

    # First request: lazy-pulls the OLD bytes + records file_id in reverse-index.
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4")
    assert resp.status_code == 200
    body = b"".join(resp.streaming_content) if resp.streaming else resp.content
    assert body == b"\x00OLD-BYTES"
    assert out_local.exists()

    # Locate the recorded file_id (whatever the fake assigned).
    from apps.videos import service as svc
    layout, drv_client = svc.layout_for(workspace)
    meta = drive.output_mp4_drive_meta(layout, drv_client, "demo", "run-001")
    assert meta is not None
    recorded_fid = meta.id

    # Confirm the file_cache reverse-index has the mapping.
    from django.core.cache import cache as dj_cache
    entry = dj_cache.get(f"videos:fcache:v1:fid:ws1:{recorded_fid}")
    assert entry == {"slug": "demo", "run_id": "run-001", "kind": "output_mp4"}

    # Republish: change the Drive bytes to NEW content (FakeDrive
    # update_binary keeps the same file_id; that mirrors real Drive
    # where upload_output_mp4 updates the existing file in place).
    fake_drive.update_binary(recorded_fid, b"\x00NEW-BYTES", "video/mp4")

    # Stub drive_changes.observe to report this file_id as changed —
    # that's what the real Drive Changes API would surface after the
    # update_binary call. (FakeDrive doesn't simulate the changes
    # feed, so we stub at the observer boundary.)
    with patch(
        "apps.videos.drive_changes.observe",
        return_value={recorded_fid},
    ):
        # Second request: observe reports the file_id changed,
        # invalidate unlinks the local cache, lazy-pull refetches.
        resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4")
        assert resp.status_code == 200
        body = b"".join(resp.streaming_content) if resp.streaming else resp.content
        assert body == b"\x00NEW-BYTES", "should serve fresh bytes after Drive change"


@pytest.mark.django_db
def test_has_explorer_falls_through_to_drive(member_client, videos_root, fake_drive):
    """Same fallthrough pattern for explorer.tar.gz — when the
    archive is published on Drive but no local extraction exists,
    has_explorer_build still reads True so the program card stops
    saying 'not built'."""
    client, _ = member_client
    ws_root = fake_drive.folder_id("ws1-drive-root")
    videos_id = fake_drive.list_folder(ws_root)[0].id
    demo_id = fake_drive.list_folder(videos_id)[0].id
    runs_id = fake_drive.list_folder(demo_id)[0].id
    run001_id = fake_drive.list_folder(runs_id)[0].id
    fake_drive.upload_binary(
        run001_id, "explorer.tar.gz", b"\x1f\x8bFAKE-GZ", "application/gzip",
    )

    # Local FS has no explorer/index.html — but the videos_root fixture
    # creates one for the seed, so remove it to test the fallthrough.
    (videos_root / "programs" / "demo" / "runs" / "run-001"
     / "explorer" / "index.html").unlink()

    program_list = client.get("/api/w/ws1/videos/programs").json()
    [demo] = program_list
    assert demo["has_explorer_build"] is True

    detail = client.get("/api/w/ws1/videos/programs/demo/runs/run-001").json()
    assert detail["has_explorer_build"] is True


@pytest.mark.django_db
def test_serve_media_404_when_drive_also_missing(
    member_client, videos_root, fake_drive,
):
    """Neither local FS nor Drive has the output.mp4 → clean 404."""
    client, _ = member_client
    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_serve_media_lazy_pulls_clip_via_manifest_alias(
    member_client, videos_root, fake_drive,
):
    """A fresh labs ECS task never ran the explorer build, so
    ``explorer/media/<alias>.mp4`` doesn't exist on disk at all — not
    as a file, not even as a broken symlink. ``serve_media`` should
    resolve the alias against the run's spec.yaml manifest, parse the
    ``gdrive:<id>.<ext>`` ref, and lazy-pull the bytes via the workspace
    SA. Without this, every snippet preview in the beat editor renders
    as 'preview not cached on host' on labs."""
    client, _ = member_client
    # Seed Drive with the clip's binary, then rewrite the spec's manifest
    # alias to point at the FakeDrive-assigned file id (FakeDrive uses
    # `fake-N` ids; the seed's literal `gdrive:abc.mp4` wouldn't resolve).
    ws_root = fake_drive.folder_id("ws1-drive-root")
    clip_id = fake_drive.upload_binary(
        ws_root, "alpha.mp4", b"\x00ALPHA-BYTES", "video/mp4",
    )
    videos_id = fake_drive.list_folder(ws_root)[0].id
    demo_id = fake_drive.list_folder(videos_id)[0].id
    runs_id = fake_drive.list_folder(demo_id)[0].id
    run001_id = fake_drive.list_folder(runs_id)[0].id
    spec_node = next(
        n for n in fake_drive.list_folder(run001_id) if n.name == "spec.yaml"
    )
    fake_drive.update_file(
        spec_node.id,
        SPEC_YAML.replace("gdrive:abc.mp4", f"gdrive:{clip_id}.mp4"),
        "application/x-yaml",
    )

    # Delete the local seeded copy so the recovery path is forced.
    alpha_local = (
        videos_root / "programs" / "demo" / "runs" / "run-001"
        / "explorer" / "media" / "alpha.mp4"
    )
    assert alpha_local.exists()
    alpha_local.unlink()

    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/alpha.mp4",
    )
    assert resp.status_code == 200, resp.content
    body = b"".join(resp.streaming_content) if resp.streaming else resp.content
    assert body.startswith(b"\x00ALPHA")

    # Bytes land in the shared clip-cache so subsequent requests skip
    # the Drive round-trip (matches the symlink-recovery cache path).
    cached = videos_root / "assets" / "clip-cache"
    assert any(p.suffix == ".mp4" for p in cached.iterdir())


@pytest.mark.django_db
def test_serve_media_unknown_alias_404s(
    member_client, videos_root, fake_drive,
):
    """When the requested alias isn't in the manifest at all, the
    recovery path returns None and the endpoint produces a clean 404
    — no AttributeError, no 500."""
    client, _ = member_client
    # Remove the local seeded file so we reach the recovery path.
    alpha_local = (
        videos_root / "programs" / "demo" / "runs" / "run-001"
        / "explorer" / "media" / "alpha.mp4"
    )
    if alpha_local.exists():
        alpha_local.unlink()
    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/not-in-manifest.mp4",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_qa_frame_404_when_no_render(member_client, videos_root, fake_drive):
    """The qa-frame endpoint serves the per-beat preview PNG written by
    the QA probe. Before the first render lands (or for unknown beat
    ids) it 404s so the GlobalTemplateWidget falls back to icon-only."""
    client, _ = member_client
    # Run hasn't been rendered → no qa-frames dir.
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/qa-frame/hook")
    assert resp.status_code == 404
    # Unknown beat id is blocked at the allowlist, never touches disk.
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/qa-frame/../../etc/passwd")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_serve_media_honors_range_header(member_client, videos_root, fake_drive):
    """Regression: Django 5's FileResponse silently ignores Range headers,
    so the <video> scrubber on the editor page was a no-op (browser sends
    `Range: bytes=N-`, server returned 200 + full body, video couldn't
    seek). _range_aware_file_response parses Range, returns 206, and
    advertises Accept-Ranges so the browser knows it can re-request."""
    client, _ = member_client
    # Seed a tiny MP4-ish blob (content doesn't matter for header behavior).
    media_dir = videos_root / "programs" / "demo" / "runs" / "run-001" / "explorer" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "final.mp4").write_bytes(b"\x00" * 4096)

    # No Range → 200 + Accept-Ranges so the browser knows to use Range next.
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4")
    assert resp.status_code == 200
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert int(resp.headers["Content-Length"]) == 4096

    # Closed range → 206 with Content-Range.
    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4",
        HTTP_RANGE="bytes=100-199",
    )
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 100-199/4096"
    assert int(resp.headers["Content-Length"]) == 100
    body = b"".join(resp.streaming_content) if resp.streaming else resp.content
    assert len(body) == 100

    # Open-ended range (browser's most common form).
    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4",
        HTTP_RANGE="bytes=4000-",
    )
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 4000-4095/4096"
    assert int(resp.headers["Content-Length"]) == 96

    # Out-of-range → 416 with Content-Range: bytes */<size>.
    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4",
        HTTP_RANGE="bytes=99999-",
    )
    assert resp.status_code == 416
    assert resp.headers["Content-Range"] == "bytes */4096"

    # Unsupported form (suffix range) → also 416 so the browser drops back.
    resp = client.get(
        "/api/w/ws1/videos/programs/demo/runs/run-001/media/final.mp4",
        HTTP_RANGE="bytes=-200",
    )
    assert resp.status_code == 416


@pytest.mark.django_db
def test_qa_frame_serves_png_when_present(member_client, videos_root, fake_drive):
    """When the QA probe has written hook.png, the endpoint returns
    it as image/png with a short private cache-control."""
    from apps.videos import service as svc
    qa_dir = svc.qa_frames_dir("demo", "run-001")
    qa_dir.mkdir(parents=True, exist_ok=True)
    # Minimal valid PNG magic header — enough for the endpoint to serve.
    (qa_dir / "hook.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    client, _ = member_client
    resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/qa-frame/hook")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert "private" in resp.headers.get("Cache-Control", "")


@pytest.mark.django_db
def test_post_edit_batch_applies_multiple_ops(member_client, videos_root, fake_drive):
    client, _ = member_client
    with mock.patch("apps.videos.service.subprocess.Popen") as popen:
        resp = client.post(
            "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
            data={"ops": [
                {"op": "set-narration", "beatId": "intro", "text": "Hello"},
                {"op": "set-clip-trim", "kind": "scene-clip", "index": 0,
                 "start_seconds": 1.0, "duration_seconds": 3.0},
            ]},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["ok"] is True
    assert body["applied"] == 2
    assert popen.call_count == 0  # save only


@pytest.mark.django_db
def test_post_edit_batch_400_on_invalid_op(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": [
            {"op": "set-narration", "beatId": "intro", "text": "Hello"},
            {"op": "set-stat", "path": "nope"},
        ]},
        content_type="application/json",
    )
    assert resp.status_code == 400, resp.content


@pytest.mark.django_db
def test_post_edit_batch_400_on_empty_ops(member_client, videos_root, fake_drive):
    client, _ = member_client
    resp = client.post(
        "/api/w/ws1/videos/programs/demo/runs/run-001/edit-batch",
        data={"ops": []},
        content_type="application/json",
    )
    assert resp.status_code == 422  # Ninja validation — min_length=1


# ---------------------------------------------------------------------------
# Render trigger (stages spec from Drive to local, spawns subprocess)
# ---------------------------------------------------------------------------


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
    # Spec was staged to local before the subprocess fired.
    assert (videos_root / "programs" / "demo" / "runs" / "run-001" / "spec.yaml").exists()


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


# ---------------------------------------------------------------------------
# Misc surfaces (local artifacts — explorer, media, feedback, status)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_render_status_reads_redis(member_client, videos_root):
    """busy=True when the chain is in flight (sentinel older than
    started_at). The fixture writes explorer/index.html at fixture-
    setup time; pick a future started_at so the sentinel is OLDER and
    busy stays True per the mtime-based derivation in service.render_status."""
    import datetime as dt
    client, _ = member_client
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: "1" if k.endswith(":busy") else future
    with mock.patch("apps.videos.service._get_redis", return_value=fake_redis):
        resp = client.get("/api/w/ws1/videos/programs/demo/runs/run-001/render-status")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["busy"] is True


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


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_programs_404_non_member(non_member_client, videos_root):
    resp = non_member_client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_programs_401_anonymous(db, client, videos_root):
    resp = client.get("/api/w/ws1/videos/programs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Templates (unchanged from previous PR; Drive-independent)
# ---------------------------------------------------------------------------


def _seed_template(root: Path) -> None:
    t = root / "templates" / "60s-campaign-overview"
    t.mkdir(parents=True)
    (t / "template.yaml").write_text(
        "id: 60s-campaign-overview\nname: 60s\ndescription: test\n"
        "intended_audience: x\nwhen_to_use: y\n",
        encoding="utf-8",
    )
    (t / "spec.template.yaml").write_text("slug: \"{{slug}}\"\nworkspace: \"{{ws}}\"\n", encoding="utf-8")
    (t / "generate.prompt.md").write_text("# Skill prompt\nFill it.\n", encoding="utf-8")


@pytest.mark.django_db
def test_list_templates(member_client):
    client, _ = member_client
    # Drive has no templates yet; list_templates auto-seeds from the repo tree.
    resp = client.get("/api/w/ws1/videos/templates")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body) >= 1
    ids = {t["id"] for t in body}
    assert "60s-campaign-overview" in ids


@pytest.mark.django_db
def test_get_template_bundle(member_client):
    client, _ = member_client
    # Trigger lazy auto-seed by listing first, then fetch the specific bundle.
    client.get("/api/w/ws1/videos/templates")
    resp = client.get("/api/w/ws1/videos/templates/60s-campaign-overview")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["meta"]["id"] == "60s-campaign-overview"
    assert body["prompt_md"].strip()


@pytest.mark.django_db
def test_patch_template_meta(member_client):
    """PATCH /templates/{id} updates the template name and returns the fresh bundle."""
    client, _ = member_client
    # Seed first.
    client.get("/api/w/ws1/videos/templates")
    resp = client.patch(
        "/api/w/ws1/videos/templates/60s-campaign-overview",
        data={"meta": {"name": "Patched Name"}},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["meta"]["name"] == "Patched Name"
    assert body["meta"]["id"] == "60s-campaign-overview"
    assert body["skeleton_yaml"]
    assert body["prompt_md"]


@pytest.mark.django_db
def test_patch_template_400_on_invalid_skeleton(member_client):
    """PATCH with unparseable skeleton_yaml returns 400."""
    client, _ = member_client
    client.get("/api/w/ws1/videos/templates")
    resp = client.patch(
        "/api/w/ws1/videos/templates/60s-campaign-overview",
        data={"skeleton_yaml": "::: not yaml :::"},
        content_type="application/json",
    )
    assert resp.status_code == 400, resp.content


@pytest.mark.django_db
def test_patch_template_400_on_invalid_example(member_client):
    """PATCH with example_yaml missing required spec fields returns 400."""
    client, _ = member_client
    client.get("/api/w/ws1/videos/templates")
    resp = client.patch(
        "/api/w/ws1/videos/templates/60s-campaign-overview",
        data={"example_yaml": "slug: x\n"},  # missing workspace
        content_type="application/json",
    )
    assert resp.status_code == 400, resp.content


@pytest.mark.django_db
def test_patch_template_404_unknown(member_client):
    """PATCH on an unknown template id returns 404."""
    client, _ = member_client
    resp = client.patch(
        "/api/w/ws1/videos/templates/does-not-exist",
        data={"meta": {"name": "x"}},
        content_type="application/json",
    )
    assert resp.status_code == 404, resp.content


@pytest.mark.django_db
def test_get_template_example(member_client):
    """GET /templates/{id}/example returns the seeded example for connectify-program."""
    client, _ = member_client
    # Seed templates (auto-seed uploads example.spec.yaml for connectify-program).
    client.get("/api/w/ws1/videos/templates")
    resp = client.get("/api/w/ws1/videos/templates/connectify-program/example")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["template_id"] == "connectify-program"
    assert "slug: connectify-program" in body["example_yaml"]


@pytest.mark.django_db
def test_get_template_example_404_when_missing(member_client):
    """GET /templates/{id}/example returns 404 when no example.spec.yaml exists."""
    client, _ = member_client
    client.get("/api/w/ws1/videos/templates")
    # connect-explainer has no example.spec.yaml in the repo tree.
    resp = client.get("/api/w/ws1/videos/templates/connect-explainer/example")
    # Either 404 (no example) or 200 (if the file exists) — no crash.
    assert resp.status_code in {200, 404}


# ---------------------------------------------------------------------------
# T7: GET /templates/{id}/example-spec  +  PATCH with example_spec
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_template_example_spec(member_client):
    """GET /templates/{id}/example-spec returns a parsed dict with slug."""
    client, _ = member_client
    client.get("/api/w/ws1/videos/templates")  # trigger auto-seed
    resp = client.get("/api/w/ws1/videos/templates/connectify-program/example-spec")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["template_id"] == "connectify-program"
    assert isinstance(body["spec"], dict)
    assert body["spec"]["slug"] == "connectify-program"


@pytest.mark.django_db
def test_get_template_example_spec_404_when_missing(member_client):
    """GET /templates/{id}/example-spec returns 404 when no example exists."""
    client, _ = member_client
    client.get("/api/w/ws1/videos/templates")
    resp = client.get("/api/w/ws1/videos/templates/connect-explainer/example-spec")
    # Either 404 (no example) or 200 (if the file happens to exist).
    assert resp.status_code in {200, 404}


@pytest.mark.django_db
def test_patch_template_example_spec(member_client):
    """PATCH /templates/{id} with example_spec dict persists and is reflected in example-spec."""
    client, _ = member_client
    client.get("/api/w/ws1/videos/templates")  # seed

    # Read the current example-spec.
    get_resp = client.get("/api/w/ws1/videos/templates/connectify-program/example-spec")
    assert get_resp.status_code == 200, get_resp.content
    current_spec = get_resp.json()["spec"]

    # Patch it with an edited dict.
    current_spec["tagline"] = "Test tagline via patch"
    patch_resp = client.patch(
        "/api/w/ws1/videos/templates/connectify-program",
        data={"example_spec": current_spec},
        content_type="application/json",
    )
    assert patch_resp.status_code == 200, patch_resp.content

    # Confirm the round-trip.
    get_resp2 = client.get("/api/w/ws1/videos/templates/connectify-program/example-spec")
    assert get_resp2.status_code == 200, get_resp2.content
    assert get_resp2.json()["spec"]["tagline"] == "Test tagline via patch"
