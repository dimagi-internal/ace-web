"""Tests for the per-run render-artifact surface (output.mp4 +
explorer.tar.gz + feedback.md → Drive).

Covers:
  - drive.upload_output_mp4 / read_output_mp4 / output_mp4_drive_meta
  - drive.upload_explorer_archive / read_explorer_archive
  - drive.write_feedback / read_feedback
  - service.publish_render_artifacts (end-to-end local→Drive)
  - service.stage_explorer_archive_locally (Drive→local extract)
  - service.read_feedback (Drive first, local fallback)
  - service.append_feedback (read-modify-write through Drive)
  - service.output_mp4_drive_link
"""
from __future__ import annotations

import io
import tarfile
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


@pytest.fixture
def seeded_run(workspace, fake_drive, videos_root):
    """Workspace with one program (demo) at run-001 in Drive + local
    output.mp4, explorer/, and feedback.md ready to publish."""
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001",
        "slug: demo\nworkspace: dimagi-team\nname: Demo\n",
    )
    # Local render artifacts.
    out = service.output_path("demo", "run-001")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x00\x01\x02fake-mp4-bytes")
    exp = service.explorer_dir("demo", "run-001")
    exp.mkdir(parents=True)
    (exp / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (exp / "library.html").write_text("<html>library</html>", encoding="utf-8")
    (exp / "media").mkdir()
    (exp / "media" / "clip.mp4").write_bytes(b"clip-bytes")
    fb = service.feedback_path("demo", "run-001")
    fb.parent.mkdir(parents=True, exist_ok=True)
    fb.write_text("# Feedback\n\nFirst note.\n", encoding="utf-8")
    return SimpleNamespace(workspace=workspace, client=fake_drive.client)


# ---------------------------------------------------------------------------
# drive.* primitives
# ---------------------------------------------------------------------------


def test_upload_and_read_output_mp4(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(
        layout, fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    file_id = drive.upload_output_mp4(
        layout, fake_drive.client, "demo", "run-001", b"video-bytes",
    )
    assert file_id
    assert drive.read_output_mp4(layout, fake_drive.client, "demo", "run-001") == b"video-bytes"


def test_upload_output_mp4_replaces_existing(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(layout, fake_drive.client, "demo", "run-001", "slug: demo\n")
    drive.upload_output_mp4(layout, fake_drive.client, "demo", "run-001", b"v1")
    drive.upload_output_mp4(layout, fake_drive.client, "demo", "run-001", b"v2")
    assert drive.read_output_mp4(layout, fake_drive.client, "demo", "run-001") == b"v2"


def test_output_mp4_drive_meta_returns_drive_file(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(layout, fake_drive.client, "demo", "run-001", "slug: demo\n")
    drive.upload_output_mp4(layout, fake_drive.client, "demo", "run-001", b"v")
    meta = drive.output_mp4_drive_meta(layout, fake_drive.client, "demo", "run-001")
    assert meta is not None
    assert meta.name == "output.mp4"
    assert meta.size_bytes == 1


def test_read_output_mp4_none_when_missing(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    assert drive.read_output_mp4(layout, fake_drive.client, "demo", "run-001") is None


def test_upload_and_read_explorer_archive(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(layout, fake_drive.client, "demo", "run-001", "slug: demo\n")
    drive.upload_explorer_archive(
        layout, fake_drive.client, "demo", "run-001", b"tar-bytes",
    )
    assert drive.read_explorer_archive(
        layout, fake_drive.client, "demo", "run-001",
    ) == b"tar-bytes"


def test_write_and_read_feedback(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(layout, fake_drive.client, "demo", "run-001", "slug: demo\n")
    drive.write_feedback(
        layout, fake_drive.client, "demo", "run-001", "# Hello\n",
    )
    assert drive.read_feedback(layout, fake_drive.client, "demo", "run-001") == "# Hello\n"


def test_write_feedback_overwrites(workspace, fake_drive):
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(layout, fake_drive.client, "demo", "run-001", "slug: demo\n")
    drive.write_feedback(layout, fake_drive.client, "demo", "run-001", "v1")
    drive.write_feedback(layout, fake_drive.client, "demo", "run-001", "v2")
    assert drive.read_feedback(layout, fake_drive.client, "demo", "run-001") == "v2"


# ---------------------------------------------------------------------------
# publish_render_artifacts (service)
# ---------------------------------------------------------------------------


def test_publish_uploads_all_three_artifacts(seeded_run):
    result = service.publish_render_artifacts(seeded_run.workspace, "demo", "run-001")
    assert result.output_mp4_id is not None
    assert result.explorer_archive_id is not None
    assert result.feedback_id is not None
    assert result.bytes_uploaded > 0

    # Round-trip: re-read from Drive and verify content.
    layout = drive.resolve_layout(seeded_run.workspace, seeded_run.client)
    mp4 = drive.read_output_mp4(layout, seeded_run.client, "demo", "run-001")
    assert mp4 == b"\x00\x01\x02fake-mp4-bytes"
    archive = drive.read_explorer_archive(layout, seeded_run.client, "demo", "run-001")
    assert archive is not None and len(archive) > 0
    # Verify the archive contains the explorer files.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = set(tar.getnames())
    assert "index.html" in names
    assert "library.html" in names
    assert "media/clip.mp4" in names
    fb = drive.read_feedback(layout, seeded_run.client, "demo", "run-001")
    assert fb is not None and "First note" in fb


def test_publish_skips_missing_artifacts(workspace, fake_drive, videos_root):
    """If only output.mp4 exists locally, only it gets uploaded."""
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    out = service.output_path("demo", "run-001")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"mp4")
    result = service.publish_render_artifacts(workspace, "demo", "run-001")
    assert result.output_mp4_id is not None
    assert result.explorer_archive_id is None
    assert result.feedback_id is None


def test_publish_rejects_invalid_slug_or_run(workspace, fake_drive):
    with pytest.raises(ValueError):
        service.publish_render_artifacts(workspace, "../evil", "run-001")
    with pytest.raises(ValueError):
        service.publish_render_artifacts(workspace, "demo", "../run-001")


def test_publish_skips_empty_explorer_dir(workspace, fake_drive, videos_root):
    """An empty explorer/ shouldn't upload an empty tarball."""
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    exp = service.explorer_dir("demo", "run-001")
    exp.mkdir(parents=True)
    result = service.publish_render_artifacts(workspace, "demo", "run-001")
    assert result.explorer_archive_id is None


def test_publish_replaces_existing_drive_copies(seeded_run):
    """Two successive publishes — the second should update, not append."""
    service.publish_render_artifacts(seeded_run.workspace, "demo", "run-001")
    # Mutate local artifact then publish again.
    service.output_path("demo", "run-001").write_bytes(b"v2")
    service.publish_render_artifacts(seeded_run.workspace, "demo", "run-001")

    layout = drive.resolve_layout(seeded_run.workspace, seeded_run.client)
    assert drive.read_output_mp4(layout, seeded_run.client, "demo", "run-001") == b"v2"
    # Single output.mp4 file should still be the only one.
    rid = drive.run_folder_id(layout, seeded_run.client, "demo", "run-001")
    assert rid is not None
    names = [f.name for f in seeded_run.client.list_folder(rid)]
    assert names.count("output.mp4") == 1


# ---------------------------------------------------------------------------
# stage_explorer_archive_locally
# ---------------------------------------------------------------------------


def test_stage_explorer_archive_restores_files(seeded_run, tmp_path):
    # First publish so Drive has the archive.
    service.publish_render_artifacts(seeded_run.workspace, "demo", "run-001")
    # Wipe local explorer/ to simulate a fresh host.
    import shutil
    shutil.rmtree(service.explorer_dir("demo", "run-001"))
    assert not service.explorer_dir("demo", "run-001").exists()

    ok = service.stage_explorer_archive_locally(seeded_run.workspace, "demo", "run-001")
    assert ok is True
    exp = service.explorer_dir("demo", "run-001")
    assert (exp / "index.html").read_text() == "<html>index</html>"
    assert (exp / "library.html").read_text() == "<html>library</html>"
    assert (exp / "media" / "clip.mp4").read_bytes() == b"clip-bytes"


def test_stage_explorer_archive_returns_false_when_absent(workspace, fake_drive, videos_root):
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    assert service.stage_explorer_archive_locally(workspace, "demo", "run-001") is False


# ---------------------------------------------------------------------------
# Feedback read/write through Drive
# ---------------------------------------------------------------------------


def test_read_feedback_prefers_drive(seeded_run):
    """Once feedback.md is in Drive, the service returns the Drive copy
    even if local has different content."""
    service.publish_render_artifacts(seeded_run.workspace, "demo", "run-001")
    # Edit local to simulate divergence.
    service.feedback_path("demo", "run-001").write_text("LOCAL OVERRIDE", encoding="utf-8")
    out = service.read_feedback(seeded_run.workspace, "demo", "run-001")
    assert "First note" in out
    assert "LOCAL OVERRIDE" not in out


def test_read_feedback_falls_back_to_local(workspace, fake_drive, videos_root):
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    fb = service.feedback_path("demo", "run-001")
    fb.parent.mkdir(parents=True, exist_ok=True)
    fb.write_text("local-only note", encoding="utf-8")
    out = service.read_feedback(workspace, "demo", "run-001")
    assert out == "local-only note"


def test_append_feedback_writes_to_drive(workspace, fake_drive, videos_root):
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    full = service.append_feedback(workspace, "demo", "run-001", "\n## first\nbody\n")
    assert full.endswith("body\n")
    layout = drive.resolve_layout(workspace, fake_drive.client)
    on_drive = drive.read_feedback(layout, fake_drive.client, "demo", "run-001")
    assert on_drive == full


def test_append_feedback_concatenates(workspace, fake_drive, videos_root):
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    service.append_feedback(workspace, "demo", "run-001", "first\n")
    full = service.append_feedback(workspace, "demo", "run-001", "second\n")
    assert full == "first\nsecond\n"


# ---------------------------------------------------------------------------
# output_mp4_drive_link
# ---------------------------------------------------------------------------


def test_output_mp4_drive_link_returns_url_after_publish(seeded_run):
    service.publish_render_artifacts(seeded_run.workspace, "demo", "run-001")
    link = service.output_mp4_drive_link(seeded_run.workspace, "demo", "run-001")
    assert link is not None
    assert link.startswith("https://fake/")  # FakeDriveClient stub URL


def test_output_mp4_drive_link_none_when_unpublished(workspace, fake_drive, videos_root):
    drive.write_spec(
        drive.resolve_layout(workspace, fake_drive.client),
        fake_drive.client, "demo", "run-001", "slug: demo\n",
    )
    assert service.output_mp4_drive_link(workspace, "demo", "run-001") is None
