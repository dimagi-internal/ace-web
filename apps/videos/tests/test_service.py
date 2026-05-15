"""Unit tests for apps.videos.service after the Drive-source-of-truth cutover.

The tests use a FakeDriveClient (the same in-memory client opps tests
use) and monkeypatch ``apps.videos.drive.client_for_workspace`` to
return it. The local FS is still used for render artifacts (output.mp4,
explorer/) so a few path helpers still touch tmp_path.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, service


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
def fake_drive(monkeypatch):
    """An empty FakeDriveClient with a `videos/` folder pre-created.

    Returns a (client, layout_root_folder_id) tuple. Tests can populate
    the tree by calling client.create_folder / client.upload_file or
    seed it via the SeedHelper below.
    """
    client = FakeDriveClient.from_tree({"workspace-root": {}})
    workspace_root_id = client.folder_id("workspace-root")
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)
    return SimpleNamespace(client=client, workspace_root_id=workspace_root_id)


@pytest.fixture
def workspace(fake_drive):
    """A lightweight workspace stand-in. The service code only needs
    `slug` and `drive_root_folder_id`; not creating a real Django
    Workspace avoids needing a DB fixture for these unit tests."""
    return SimpleNamespace(
        slug="dimagi-team", drive_root_folder_id=fake_drive.workspace_root_id,
    )


@pytest.fixture
def videos_root(tmp_path: Path, settings):
    """Local scratch dir for renders. Drive holds the spec; this dir is
    where ``trigger_rerender`` stages it and where renders write outputs."""
    root = tmp_path / "video-production" / "connect-videos"
    root.mkdir(parents=True)
    settings.ACE_VIDEOS_ROOT = str(root)
    return root


@pytest.fixture
def seeded(fake_drive, workspace, videos_root):
    """A workspace with one program (demo) at run-001, spec in Drive.

    Returns the same SimpleNamespace as fake_drive, with a `.workspace`
    attribute attached.
    """
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(layout, fake_drive.client, "demo", "run-001", SPEC_YAML)
    # Local explorer artifacts for render-status assertions.
    exp = service.explorer_dir("demo", "run-001")
    exp.mkdir(parents=True)
    (exp / "index.html").write_text(
        "<html><head></head><body><script>fetch('/edit');</script></body></html>",
        encoding="utf-8",
    )
    (exp / "library.html").write_text(
        '<div class="lib-card"><h3>@alpha</h3></div></div>', encoding="utf-8",
    )
    fake_drive.workspace = workspace
    return fake_drive


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def test_load_program_run(seeded):
    rec = service.load_program_run(seeded.workspace, "demo", "run-001")
    assert rec is not None
    assert rec.slug == "demo"
    assert rec.run_id == "run-001"
    assert rec.workspace_slug == "dimagi-team"
    assert rec.manifest_count == 2
    assert rec.yaml_path == "videos/demo/runs/run-001/spec.yaml"


def test_load_program_defaults_to_latest(seeded):
    rec = service.load_program(seeded.workspace, "demo")
    assert rec is not None
    assert rec.run_id == "run-001"


def test_list_run_ids(seeded):
    assert service.list_run_ids(seeded.workspace, "demo") == ["run-001"]


def test_list_run_ids_picks_up_second_run(seeded):
    layout = drive.resolve_layout(seeded.workspace, seeded.client)
    drive.write_spec(layout, seeded.client, "demo", "run-002", SPEC_YAML)
    assert service.list_run_ids(seeded.workspace, "demo") == ["run-001", "run-002"]
    assert service.latest_run_id(seeded.workspace, "demo") == "run-002"


def test_next_run_id(seeded):
    assert service.next_run_id(seeded.workspace, "demo") == "run-002"


def test_list_programs_filters_by_workspace(seeded):
    progs = service.list_programs_for_workspace(seeded.workspace)
    assert [p.slug for p in progs] == ["demo"]


# ---------------------------------------------------------------------------
# Creates / writes
# ---------------------------------------------------------------------------


def test_create_program_writes_to_drive(fake_drive, workspace):
    yaml_body = (
        "slug: new-prog\n"
        "workspace: dimagi-team\n"
        "name: New Program\n"
    )
    file_id = service.create_program_from_spec(workspace, "new-prog", yaml_body)
    assert file_id.startswith("fake-")  # FakeDriveClient assigns fake-NNN ids
    # Verify it round-trips via load_program_run.
    rec = service.load_program_run(workspace, "new-prog", "run-001")
    assert rec is not None
    assert rec.name == "New Program"


def test_create_program_autofills_narration_script_from_by_beat(fake_drive, workspace):
    """The render's precondition check requires narration.script non-empty.
    When the agent fills only by_beat (the canonical case for the
    /ace:video-from-program-page skill), the server joins them into
    script before persisting so renders don't abort."""
    yaml_body = (
        "slug: kmc-test\n"
        "workspace: dimagi-team\n"
        "name: KMC Test\n"
        "narration:\n"
        "  generator: manual\n"
        "  by_beat:\n"
        "    hook: \"Pay for verified service delivery.\"\n"
        "    cycle: \"Workers learn, deliver, and verify before pay.\"\n"
        "    cta: \"\"\n"
        "  script: \"\"\n"
    )
    service.create_program_from_spec(workspace, "kmc-test", yaml_body)
    # Re-read from Drive and confirm script is no longer empty.
    layout = drive.resolve_layout(workspace, fake_drive.client)
    fresh = drive.read_spec(layout, fake_drive.client, "kmc-test", "run-001")
    assert fresh is not None
    assert "Pay for verified service delivery." in fresh
    # Joined paragraphs land in narration.script.
    assert "script:" in fresh
    # The empty-string cta is filtered out (no double newlines).
    parsed_by_yaml = fresh.split("script:")[1]
    assert "Pay for verified service delivery." in parsed_by_yaml
    assert "Workers learn, deliver, and verify before pay." in parsed_by_yaml


def test_create_program_respects_author_provided_script(fake_drive, workspace):
    """If the author wrote a script, the auto-fill must NOT overwrite it."""
    yaml_body = (
        "slug: respects-script\n"
        "workspace: dimagi-team\n"
        "name: X\n"
        "narration:\n"
        "  by_beat:\n"
        "    hook: \"This is the by-beat hook.\"\n"
        "  script: \"This is the author's hand-crafted script paragraph.\"\n"
    )
    service.create_program_from_spec(workspace, "respects-script", yaml_body)
    layout = drive.resolve_layout(workspace, fake_drive.client)
    fresh = drive.read_spec(layout, fake_drive.client, "respects-script", "run-001")
    assert fresh is not None
    assert "hand-crafted script paragraph" in fresh
    # The by_beat content does NOT leak into the script.
    script_portion = fresh.split("script:")[1].split("\n")[0]
    assert "by-beat hook" not in script_portion


def test_create_program_rejects_slug_mismatch(workspace):
    bad = "slug: in-yaml\nworkspace: dimagi-team\nname: X\n"
    with pytest.raises(ValueError, match="must match the URL slug"):
        service.create_program_from_spec(workspace, "in-url", bad)


def test_create_program_rejects_workspace_mismatch(workspace):
    bad = "slug: x\nworkspace: other-ws\nname: X\n"
    with pytest.raises(ValueError, match="must match the URL workspace"):
        service.create_program_from_spec(workspace, "x", bad)


def test_create_program_409_when_program_already_exists(seeded):
    with pytest.raises(FileExistsError):
        service.create_program_from_spec(
            seeded.workspace, "demo",
            "slug: demo\nworkspace: dimagi-team\nname: Demo\n",
        )


def test_copy_run_snapshots_spec(seeded):
    new_id = service.copy_run(seeded.workspace, "demo", "run-001")
    assert new_id == "run-002"
    # Verify the new run is loadable.
    rec = service.load_program_run(seeded.workspace, "demo", "run-002")
    assert rec is not None
    assert rec.name == "Demo Program"


# ---------------------------------------------------------------------------
# Apply edit (round-trip preserves comments)
# ---------------------------------------------------------------------------


def test_apply_edit_set_narration_preserves_comments(seeded):
    result = service.apply_edit(
        seeded.workspace, "demo", "run-001",
        {"op": "set-narration", "beatId": "intro", "text": "Hi"},
    )
    assert result.ok, result.message
    # Re-read from Drive and verify the comment + the new value.
    layout = drive.resolve_layout(seeded.workspace, seeded.client)
    fresh = drive.read_spec(layout, seeded.client, "demo", "run-001")
    assert fresh is not None
    assert "# top-level comment about this program" in fresh
    assert "intro: Hi" in fresh


def test_apply_edit_set_clip_start(seeded):
    result = service.apply_edit(
        seeded.workspace, "demo", "run-001",
        {"op": "set-clip-start", "kind": "product-beat", "index": 0, "start_seconds": 1.25},
    )
    assert result.ok, result.message
    layout = drive.resolve_layout(seeded.workspace, seeded.client)
    fresh = drive.read_spec(layout, seeded.client, "demo", "run-001")
    assert fresh is not None
    assert "start_seconds: 1.25" in fresh


def test_apply_edit_unknown_run(seeded):
    result = service.apply_edit(
        seeded.workspace, "demo", "run-999",
        {"op": "set-narration", "beatId": "x", "text": "y"},
    )
    assert not result.ok


# ---------------------------------------------------------------------------
# Render triggers — stage Drive → local + spawn subprocess
# ---------------------------------------------------------------------------


def test_trigger_rerender_stages_then_spawns(seeded):
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen") as popen:
        ok = service.trigger_rerender(seeded.workspace, "demo", "run-001")
    assert ok is True
    # Spec got staged to local.
    staged = service.spec_path("demo", "run-001")
    assert staged.exists()
    assert "slug: demo" in staged.read_text()
    # Subprocess fired with the run flag.
    chain = popen.call_args[0][0][2]
    assert "--program=demo" in chain
    assert "--run=run-001" in chain
    assert "npm run render" in chain


def test_trigger_build_only_skips_render(seeded):
    fake_redis = mock.MagicMock()
    fake_redis.set.return_value = True
    with mock.patch.object(service, "_get_redis", return_value=fake_redis), \
         mock.patch.object(service.subprocess, "Popen") as popen:
        ok = service.trigger_build_only(seeded.workspace, "demo", "run-001")
    assert ok is True
    chain = popen.call_args[0][0][2]
    assert "npm run render" not in chain
    assert "build-clip-explorer -- --program=demo --run=run-001" in chain


def test_trigger_rerender_rejects_bad_slug_or_run(workspace):
    with pytest.raises(ValueError):
        service.trigger_rerender(workspace, "../evil", "run-001")
    with pytest.raises(ValueError):
        service.trigger_rerender(workspace, "demo", "../run-001")


# ---------------------------------------------------------------------------
# render_status: Redis busy flag + output.mp4 mtime → accurate "busy"
# ---------------------------------------------------------------------------


def test_render_status_busy_true_when_no_sentinel_exists(seeded):
    """No explorer/index.html + recent started_at + busy flag set →
    busy True (chain is in flight, not yet 'appears_failed')."""
    started = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: ("1" if k.endswith(":busy") else started)
    # Wipe the sentinel from the fixture.
    sentinel = service.explorer_dir("demo", "run-001") / "index.html"
    if sentinel.exists():
        sentinel.unlink()
    with mock.patch.object(service, "_get_redis", return_value=fake_redis):
        status = service.render_status("demo", "run-001")
    assert status["busy"] is True
    assert status["appears_failed"] is False
    assert status["started_at"] == started


def test_render_status_busy_false_when_sentinel_newer_than_started(seeded):
    """explorer/index.html mtime > started_at → busy False even though
    Redis still has the busy flag (1-hour TTL hasn't cleared)."""
    # The seeded fixture wrote explorer/index.html just now.
    started = (
        dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)
    ).replace(microsecond=0).isoformat()
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: ("1" if k.endswith(":busy") else started)
    with mock.patch.object(service, "_get_redis", return_value=fake_redis):
        status = service.render_status("demo", "run-001")
    assert status["busy"] is False


def test_render_status_busy_true_when_sentinel_older_than_started(seeded):
    """Stale explorer/index.html from a prior render + new busy flag →
    busy True (the new chain hasn't produced the sentinel yet)."""
    import os
    sentinel = service.explorer_dir("demo", "run-001") / "index.html"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("<old>")
    # Backdate the sentinel by 10 minutes; mark the chain as starting now.
    old = (dt.datetime.now() - dt.timedelta(minutes=10)).timestamp()
    os.utime(sentinel, (old, old))
    started = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: ("1" if k.endswith(":busy") else started)
    with mock.patch.object(service, "_get_redis", return_value=fake_redis):
        status = service.render_status("demo", "run-001")
    assert status["busy"] is True


def test_render_status_busy_false_when_redis_flag_absent(seeded):
    fake_redis = mock.MagicMock()
    fake_redis.get.return_value = None
    with mock.patch.object(service, "_get_redis", return_value=fake_redis):
        status = service.render_status("demo", "run-001")
    assert status["busy"] is False
    assert status["started_at"] is None
    assert status["appears_failed"] is False


def test_render_status_appears_failed_after_8_min_with_stale_sentinel(seeded):
    """Redis still busy, sentinel old, started > 8 min ago → appears_failed."""
    import os
    # Backdate the sentinel so it's older than started_at.
    sentinel = service.explorer_dir("demo", "run-001") / "index.html"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("<old>")
    old = (dt.datetime.now() - dt.timedelta(minutes=30)).timestamp()
    os.utime(sentinel, (old, old))
    # Started 15 minutes ago — well past the 8-minute threshold.
    started = (
        dt.datetime.now(dt.UTC) - dt.timedelta(minutes=15)
    ).replace(microsecond=0).isoformat()
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: ("1" if k.endswith(":busy") else started)
    with mock.patch.object(service, "_get_redis", return_value=fake_redis):
        status = service.render_status("demo", "run-001")
    # busy reflects the user-visible signal: not "actually rendering."
    assert status["busy"] is False
    assert status["appears_failed"] is True


def test_render_status_not_failed_within_8_min_window(seeded):
    """Redis busy, no sentinel, started 3 min ago → still in flight,
    not yet 'appears_failed'."""
    sentinel = service.explorer_dir("demo", "run-001") / "index.html"
    if sentinel.exists():
        sentinel.unlink()
    started = (
        dt.datetime.now(dt.UTC) - dt.timedelta(minutes=3)
    ).replace(microsecond=0).isoformat()
    fake_redis = mock.MagicMock()
    fake_redis.get.side_effect = lambda k: ("1" if k.endswith(":busy") else started)
    with mock.patch.object(service, "_get_redis", return_value=fake_redis):
        status = service.render_status("demo", "run-001")
    assert status["busy"] is True
    assert status["appears_failed"] is False


# ---------------------------------------------------------------------------
# HTML rewriter (operates on text — no Drive)
# ---------------------------------------------------------------------------


def test_rewrite_explorer_html_injects_dark_theme():
    out = service.rewrite_explorer_html(
        "<html><head></head><body><script>fetch('/edit');</script></body></html>",
        prefix="/api/w/x/videos/programs/demo/runs/run-001/", csrf_cookie_name="csrftoken_ace",
    )
    assert "ace-web-dark-theme" in out
    assert "X-CSRFToken" in out
    assert "fetch('edit'" in out


def test_apply_single_op_returns_result_without_saving(monkeypatch):
    from apps.videos import service
    from ruamel.yaml import YAML
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    from io import StringIO

    doc = yaml.load(StringIO("""\
scene:
  clips:
    - "@alpha"
narration:
  by_beat: {}
"""))
    result = service._apply_single_op(doc, {
        "op": "set-narration", "beatId": "hook", "text": "Hello"
    })
    assert result.ok
    assert doc["narration"]["by_beat"]["hook"] == "Hello"
