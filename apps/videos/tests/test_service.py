"""Unit tests for apps.videos.service after the runs-model migration."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from apps.videos import service


SPEC_YAML = """\
# top-level comment about this program
slug: demo
workspace: dimagi-team
name: Demo Program
tagline: One-liner.
manifest:
  alpha: gdrive:abc123.mp4   # alpha clip
  beta:  gdrive:def456.mp4

scene:
  clips:
    - "@alpha"
    - "@beta"

product:
  beats:
    - asset: "@alpha"
      caption: "first beat"
    - asset: "@beta"
      caption: "second beat"
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
        "<html><head><title>x</title></head><body>"
        "<script>fetch('/edit');</script></body></html>",
        encoding="utf-8",
    )
    (exp / "library.html").write_text(
        '<div class="lib-card"><h3>@alpha</h3>'
        '<video src="media/alpha.mp4"></video>'
        '<span>3.5s · 1920x1080</span>'
        '<div class="lib-tag used-in">scene[0]</div></div></div>',
        encoding="utf-8",
    )
    (exp / "media").mkdir()
    (exp / "media" / "alpha.mp4").write_bytes(b"fakebytes")
    settings.ACE_VIDEOS_ROOT = str(root)
    return root


def test_slug_validator():
    assert service.is_valid_slug("chc")
    assert not service.is_valid_slug("../chc")
    assert not service.is_valid_slug("")


def test_run_id_validator():
    assert service.is_valid_run_id("run-001")
    assert service.is_valid_run_id("run-042")
    assert service.is_valid_run_id("run-1234")  # 4+ digits ok
    assert not service.is_valid_run_id("run001")
    assert not service.is_valid_run_id("../run-001")
    assert not service.is_valid_run_id("")


def test_load_program_run(videos_root: Path):
    rec = service.load_program_run("demo", "run-001")
    assert rec is not None
    assert rec.slug == "demo"
    assert rec.run_id == "run-001"
    assert rec.workspace_slug == "dimagi-team"
    assert rec.manifest_count == 2


def test_load_program_defaults_to_latest(videos_root: Path):
    rec = service.load_program("demo")
    assert rec is not None
    assert rec.run_id == "run-001"


def test_list_run_ids(videos_root: Path):
    assert service.list_run_ids("demo") == ["run-001"]
    # Add a second run.
    (videos_root / "programs" / "demo" / "runs" / "run-002").mkdir()
    (videos_root / "programs" / "demo" / "runs" / "run-002" / "spec.yaml").write_text(SPEC_YAML)
    assert service.list_run_ids("demo") == ["run-001", "run-002"]
    assert service.latest_run_id("demo") == "run-002"


def test_next_run_id(videos_root: Path):
    assert service.next_run_id("demo") == "run-002"


def test_copy_run_snapshots_spec_into_new_dir(videos_root: Path):
    new_id = service.copy_run("demo", "run-001")
    assert new_id == "run-002"
    new_spec = videos_root / "programs" / "demo" / "runs" / "run-002" / "spec.yaml"
    assert new_spec.exists()
    assert "Demo Program" in new_spec.read_text()
    # Old run remains intact and editable.
    old_spec = videos_root / "programs" / "demo" / "runs" / "run-001" / "spec.yaml"
    assert old_spec.exists()


def test_list_programs_filters_by_workspace(videos_root: Path):
    assert [p.slug for p in service.list_programs_for_workspace("dimagi-team")] == ["demo"]
    assert service.list_programs_for_workspace("other-team") == []


def test_apply_edit_preserves_comments(videos_root: Path):
    result = service.apply_edit(
        "demo", "run-001",
        {"op": "set-clip-start", "kind": "product-beat", "index": 0, "start_seconds": 1.25},
    )
    assert result.ok, result.message
    raw = (videos_root / "programs" / "demo" / "runs" / "run-001" / "spec.yaml").read_text()
    assert "# top-level comment about this program" in raw
    assert "# alpha clip" in raw
    assert "start_seconds: 1.25" in raw


def test_apply_edit_set_narration(videos_root: Path):
    result = service.apply_edit(
        "demo", "run-001",
        {"op": "set-narration", "beatId": "intro", "text": "Hi"},
    )
    assert result.ok, result.message
    raw = (videos_root / "programs" / "demo" / "runs" / "run-001" / "spec.yaml").read_text()
    assert "intro: Hi" in raw


def test_apply_edit_unknown_run(videos_root: Path):
    result = service.apply_edit("demo", "run-999", {"op": "set-narration", "beatId": "x", "text": "y"})
    assert not result.ok


def test_load_library_entries(videos_root: Path):
    entries = service.load_library_entries("demo", "run-001")
    assert len(entries) == 1
    assert entries[0]["alias"] == "alpha"


def test_trigger_rerender_includes_run_flag(videos_root: Path):
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen") as popen:
        ok = service.trigger_rerender("demo", "run-001")
    assert ok is True
    chain = popen.call_args[0][0][2]
    assert "--program=demo" in chain
    assert "--run=run-001" in chain
    assert "npm run render" in chain
    assert "npm run build-clip-explorer" in chain


def test_trigger_build_only_skips_render(videos_root: Path):
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen") as popen:
        ok = service.trigger_build_only("demo", "run-001")
    assert ok is True
    chain = popen.call_args[0][0][2]
    assert "npm run render" not in chain
    assert "npm run build-clip-explorer -- --program=demo --run=run-001" in chain


def test_trigger_rerender_rejects_bad_slug_or_run():
    with pytest.raises(ValueError):
        service.trigger_rerender("../evil", "run-001")
    with pytest.raises(ValueError):
        service.trigger_rerender("demo", "../run-001")


def test_rewrite_explorer_html_injects_dark_theme(videos_root: Path):
    src = (videos_root / "programs" / "demo" / "runs" / "run-001" / "explorer" / "index.html").read_text()
    out = service.rewrite_explorer_html(
        src, prefix="/api/w/x/videos/programs/demo/runs/run-001/", csrf_cookie_name="csrftoken_ace",
    )
    assert "ace-web-dark-theme" in out
    assert "X-CSRFToken" in out
    assert "fetch('edit'" in out
