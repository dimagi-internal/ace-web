"""Tests for service.apply_edit_batch — single load-mutate-save round trip."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, service
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


SPEC = """\
slug: demo
workspace: ws1
name: Demo
manifest:
  alpha: gdrive:abc.mp4
scene:
  clips:
    - "@alpha"
product:
  beats:
    - asset: "@alpha"
      caption: "first"
problem:
  big: "29%"
  caption: "old"
impact:
  - big: "$1"
    caption: "a"
  - big: "$2"
    caption: "b"
narration:
  by_beat: {}
"""


@pytest.fixture
def ws_and_drive(db, monkeypatch, tmp_path, settings):
    settings.ACE_VIDEOS_ROOT = str(tmp_path / "videos-scratch")
    creator = User.objects.create_user(email="creator@example.com")
    user = User.objects.create_user(email="alice@example.com")
    client = FakeDriveClient.from_tree({"ws1-root": {}})
    ws = Workspace.objects.create(
        slug="ws1",
        display_name="Ws1",
        drive_root_folder_id=client.folder_id("ws1-root"),
        created_by=creator,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    monkeypatch.setattr(drive, "client_for_workspace", lambda w: client)
    # Seed videos/programs/demo/runs/run-001/spec.yaml
    # NOTE: the videos drive layout is videos/<slug>/runs/<run-id>/spec.yaml,
    # there is no intermediate "programs/" segment.
    ws_root = client.folder_id("ws1-root")
    videos_id = client.create_folder(ws_root, "videos")
    demo_id = client.create_folder(videos_id, "demo")
    runs_id = client.create_folder(demo_id, "runs")
    run_id = client.create_folder(runs_id, "run-001")
    client.upload_file(run_id, "spec.yaml", SPEC, "application/x-yaml")
    return ws, client


def test_apply_edit_batch_applies_all_ops_in_order(ws_and_drive):
    ws, _fake = ws_and_drive
    result = service.apply_edit_batch(ws, "demo", "run-001", [
        {"op": "set-narration", "beatId": "hook", "text": "Hi"},
        {"op": "set-stat", "path": "problem", "big": "31%"},
        {"op": "set-stat", "path": "impact[1]", "big": "$5"},
    ])
    assert result.ok, result.message
    assert result.applied == 3
    # Verify YAML round-tripped to Drive with all three ops applied.
    layout, client = service.layout_for(ws)
    saved = drive.read_spec(layout, client, "demo", "run-001")
    assert "Hi" in saved
    assert "31%" in saved
    assert "$5" in saved


def test_apply_edit_batch_is_all_or_nothing_on_invalid_op(ws_and_drive):
    ws, _ = ws_and_drive
    result = service.apply_edit_batch(ws, "demo", "run-001", [
        {"op": "set-narration", "beatId": "hook", "text": "Hi"},
        {"op": "set-stat", "path": "impact[99]", "big": "boom"},
    ])
    assert not result.ok
    assert result.applied == 0
    # Original spec untouched (no "Hi" persisted).
    layout, client = service.layout_for(ws)
    saved = drive.read_spec(layout, client, "demo", "run-001")
    assert "Hi" not in saved


def test_apply_edit_batch_preserves_comments(ws_and_drive, monkeypatch):
    ws, _ = ws_and_drive
    # Overwrite spec with comment-bearing yaml via monkeypatching the
    # drive.read_spec call apply_edit_batch issues.
    yaml_with_comments = """\
# A comment above the field
problem:
  big: "29%"        # inline comment
  caption: "x"
"""
    monkeypatch.setattr(
        drive, "read_spec",
        lambda *a, **kw: yaml_with_comments,
    )
    writes: list[str] = []
    monkeypatch.setattr(
        drive, "write_spec",
        lambda layout, client, slug, run, content: writes.append(content) or "fake-file-id",
    )
    result = service.apply_edit_batch(ws, "demo", "run-001", [
        {"op": "set-stat", "path": "problem", "big": "33%"},
    ])
    assert result.ok, result.message
    assert writes, "expected one drive.write_spec call"
    saved = writes[0]
    assert "# A comment above the field" in saved
    assert "# inline comment" in saved
    assert "33%" in saved


def test_apply_edit_batch_empty_is_noop(ws_and_drive, monkeypatch):
    """Empty batch returns ok=True, applied=0 without touching Drive."""
    ws, _ = ws_and_drive
    reads: list[str] = []
    writes: list[str] = []
    monkeypatch.setattr(
        drive, "read_spec",
        lambda *a, **kw: reads.append("read") or "",
    )
    monkeypatch.setattr(
        drive, "write_spec",
        lambda *a, **kw: writes.append("write") or "fake-id",
    )
    result = service.apply_edit_batch(ws, "demo", "run-001", [])
    assert result.ok
    assert result.applied == 0
    assert reads == [], "empty batch should not read from Drive"
    assert writes == [], "empty batch should not write to Drive"
