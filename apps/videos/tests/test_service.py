"""Unit tests for apps.videos.service.

These tests exercise the filesystem / YAML / HTML helpers without
spinning up the Django test client. The api_v2 wiring is covered
separately in test_api_v2.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from apps.videos import service


PROGRAM_YAML = """\
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
    """Real on-disk videos root with a single demo program + built explorer."""
    root = tmp_path / "video-production" / "connect-videos"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "demo.yaml").write_text(PROGRAM_YAML, encoding="utf-8")

    built = root / "out" / "clip-explorer" / "demo"
    built.mkdir(parents=True)
    (built / "index.html").write_text(
        "<html><head><title>x</title></head><body>"
        "<a href='/library.html'>library</a>"
        "<a href='/'>home</a>"
        "<script>fetch('/edit', {method:'POST'});</script>"
        "<script>fetch('/library.json');</script>"
        "<script>fetch('/feedback');</script>"
        "</body></html>",
        encoding="utf-8",
    )
    (built / "library.html").write_text(
        '<div class="lib-card"><h3>@alpha</h3>'
        '<video src="media/alpha.mp4" controls></video>'
        '<span>3.5s · 1920x1080</span>'
        '<div class="lib-tag used-in">scene[0]</div>'
        '<div class="lib-tag used-in">beat[0]</div>'
        '</div></div>',
        encoding="utf-8",
    )
    (built / "media").mkdir()
    (built / "media" / "alpha.mp4").write_bytes(b"\x00\x00")

    settings.ACE_VIDEOS_ROOT = str(root)
    return root


def test_slug_validator_rejects_shell_chars():
    assert service.is_valid_slug("chc")
    assert service.is_valid_slug("chc-2")
    assert not service.is_valid_slug("chc;rm -rf /")
    assert not service.is_valid_slug("../chc")
    assert not service.is_valid_slug("")
    assert not service.is_valid_slug("CHC")  # case-sensitive whitelist


def test_load_program_returns_record(videos_root: Path):
    rec = service.load_program("demo")
    assert rec is not None
    assert rec.slug == "demo"
    assert rec.workspace_slug == "dimagi-team"
    assert rec.name == "Demo Program"
    assert rec.manifest_count == 2
    assert rec.has_explorer_build is True


def test_load_program_missing(videos_root: Path):
    assert service.load_program("does-not-exist") is None


def test_list_programs_filters_by_workspace(videos_root: Path):
    # Same program belongs to dimagi-team; other-team gets nothing.
    assert [p.slug for p in service.list_programs_for_workspace("dimagi-team")] == ["demo"]
    assert service.list_programs_for_workspace("other-team") == []


def test_apply_edit_set_clip_start_preserves_comments(videos_root: Path):
    result = service.apply_edit(
        "demo",
        {"op": "set-clip-start", "kind": "product-beat", "index": 0, "start_seconds": 1.25},
    )
    assert result.ok, result.message
    raw = (videos_root / "programs" / "demo.yaml").read_text(encoding="utf-8")
    # The comments on lines 1 and 5 must survive the round-trip.
    assert "# top-level comment about this program" in raw
    assert "# alpha clip" in raw
    # The mutation landed.
    assert "start_seconds: 1.25" in raw


def test_apply_edit_set_clip_asset_promotes_bare_string(videos_root: Path):
    # scene.clips[0] is a bare string `@alpha`; swapping should preserve
    # the compact-string form per the explore.ts contract.
    result = service.apply_edit(
        "demo",
        {"op": "set-clip-asset", "kind": "scene-clip", "index": 0, "alias": "beta"},
    )
    assert result.ok, result.message
    raw = (videos_root / "programs" / "demo.yaml").read_text(encoding="utf-8")
    assert "- '@beta'" in raw or '- "@beta"' in raw or "- @beta" in raw


def test_apply_edit_set_narration_creates_nested_keys(videos_root: Path):
    result = service.apply_edit(
        "demo",
        {"op": "set-narration", "beatId": "intro", "text": "Hello world"},
    )
    assert result.ok, result.message
    raw = (videos_root / "programs" / "demo.yaml").read_text(encoding="utf-8")
    assert "narration:" in raw
    assert "by_beat:" in raw
    assert "intro: Hello world" in raw


def test_apply_edit_unknown_op(videos_root: Path):
    result = service.apply_edit("demo", {"op": "nope"})
    assert not result.ok


def test_apply_edit_unknown_program():
    result = service.apply_edit("does-not-exist", {"op": "set-narration", "beatId": "x", "text": "y"})
    assert not result.ok


def test_load_library_entries_parses_card(videos_root: Path):
    entries = service.load_library_entries("demo")
    assert len(entries) == 1
    e = entries[0]
    assert e["alias"] == "alpha"
    assert e["duration_seconds"] == 3.5
    assert e["resolution"] == "1920x1080"
    assert e["used_in"] == ["scene[0]", "beat[0]"]


def test_load_library_entries_missing_file(videos_root: Path):
    # Remove the built library.html — endpoint should degrade gracefully.
    (videos_root / "out" / "clip-explorer" / "demo" / "library.html").unlink()
    assert service.load_library_entries("demo") == []


def test_rewrite_explorer_html_rewrites_absolute_paths(videos_root: Path):
    src = (videos_root / "out" / "clip-explorer" / "demo" / "index.html").read_text()
    out = service.rewrite_explorer_html(
        src, prefix="/api/w/dimagi-team/videos/programs/demo/", csrf_cookie_name="csrftoken_ace"
    )
    assert "fetch('edit'" in out
    assert "fetch('library.json'" in out
    assert "fetch('feedback'" in out
    # Rewriter preserves the original quoting style (single quotes here).
    assert "href='library.html'" in out
    assert "href='explorer.html'" in out
    # CSRF wrapper injected — the literal appears twice (Headers + plain
    # dict branches in the same wrapper).
    assert "X-CSRFToken" in out
    assert "csrftoken_ace" in out


def test_trigger_rerender_marks_busy_then_skips_duplicate(videos_root: Path):
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True  # first call acquires
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen") as popen:
        ok = service.trigger_rerender("demo", needs_hydrate=False)
    assert ok is True
    assert popen.call_count == 1
    # Inspect the chain we spawned: no hydrate, includes render + build-clip-explorer.
    spawn_args = popen.call_args[0][0]
    assert spawn_args[:2] == ["sh", "-c"]
    assert "npm run hydrate" not in spawn_args[2]
    assert "npm run render -- --program=demo --draft" in spawn_args[2]
    assert "npm run build-clip-explorer -- --program=demo" in spawn_args[2]

    # Second call: SETNX returns False -> skip duplicate, no Popen.
    fake_redis.set.return_value = None
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen") as popen2:
        ok = service.trigger_rerender("demo", needs_hydrate=True)
    assert ok is False
    assert popen2.call_count == 0


def test_trigger_rerender_rejects_bad_slug():
    with pytest.raises(ValueError):
        service.trigger_rerender("../evil", needs_hydrate=False)
