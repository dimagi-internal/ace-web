"""Tests for VideoSnippet: model, ingest command/upsert, and list API.

The ingest tests run against the real canopy sample manifest
(``fixtures/snippet_manifest.json``) so the field contract stays
grounded in what canopy actually produces.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from apps.videos.models import STATUS_OK, VideoLibraryEntry, VideoSnippet
from apps.videos.snippets import ingest_manifest
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

FIXTURE = Path(__file__).parent / "fixtures" / "snippet_manifest.json"


def _manifest() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def workspace(db):
    creator = User.objects.create_user(email="creator@example.com")
    return Workspace.objects.create(
        slug="ws-snip", display_name="WS Snip",
        drive_root_folder_id="root-1", created_by=creator,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_model_str_and_unique_per_workspace(workspace):
    snip = VideoSnippet.objects.create(
        workspace=workspace, snippet_key="vm-scene-1",
        in_seconds=0.0, out_seconds=9.2, duration_seconds=9.2,
    )
    assert str(snip) == "ws-snip/vm-scene-1"
    # unique_together (workspace, snippet_key)
    from django.db import transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        VideoSnippet.objects.create(
            workspace=workspace, snippet_key="vm-scene-1",
            in_seconds=0.0, out_seconds=1.0, duration_seconds=1.0,
        )


def test_model_clip_fk_set_null(workspace):
    clip = VideoLibraryEntry.objects.create(
        workspace=workspace, subfolder="vm", filename="iter10_clip.mp4",
        drive_id="d1", name="Master",
    )
    snip = VideoSnippet.objects.create(
        workspace=workspace, snippet_key="k1", clip=clip,
        in_seconds=0.0, out_seconds=1.0, duration_seconds=1.0,
    )
    clip.delete()
    snip.refresh_from_db()
    assert snip.clip_id is None  # SET_NULL, snippet survives


# ---------------------------------------------------------------------------
# Ingest: upsert, idempotency, clip-linking
# ---------------------------------------------------------------------------


def test_ingest_creates_one_row_per_snippet(workspace):
    result = ingest_manifest(workspace, _manifest())
    assert result["created"] == 5
    assert result["updated"] == 0
    assert VideoSnippet.objects.filter(workspace=workspace).count() == 5


def test_ingest_maps_manifest_fields(workspace):
    ingest_manifest(workspace, _manifest())
    s3 = VideoSnippet.objects.get(workspace=workspace, snippet_key="verified-monitoring-scene-3")
    assert s3.title.startswith("The per-surveyor quality scorecard")
    assert s3.narration_sentence.startswith("The survey's quality is not asserted")
    assert s3.scene_index == 3
    assert s3.provenance == "S2"
    assert s3.in_seconds == pytest.approx(22.18)
    assert s3.out_seconds == pytest.approx(34.432)
    assert s3.duration_seconds == pytest.approx(12.252)
    assert "surveyor-scorecard" in s3.tags
    # top-level manifest fields denormalized onto the row
    assert s3.narrative_slug == "verified-monitoring"
    assert s3.source_run == "verified-monitoring-2026-06-16-001"
    assert s3.status == STATUS_OK


def test_ingest_is_idempotent_on_rerun(workspace):
    ingest_manifest(workspace, _manifest())
    result2 = ingest_manifest(workspace, _manifest())
    assert result2["created"] == 0
    assert result2["updated"] == 5
    assert VideoSnippet.objects.filter(workspace=workspace).count() == 5


def test_ingest_rerun_picks_up_edits(workspace):
    ingest_manifest(workspace, _manifest())
    m = _manifest()
    m["snippets"][0]["title"] = "Edited title"
    ingest_manifest(workspace, m)
    s1 = VideoSnippet.objects.get(workspace=workspace, snippet_key="verified-monitoring-scene-1")
    assert s1.title == "Edited title"


def test_ingest_links_clip_when_master_in_library(workspace):
    # source_clip basename is iter10_clip.mp4 — seed a matching library row.
    clip = VideoLibraryEntry.objects.create(
        workspace=workspace, subfolder="vm", filename="iter10_clip.mp4",
        drive_id="d1", name="Master",
    )
    result = ingest_manifest(workspace, _manifest())
    assert result["linked"] == 5
    assert result["unlinked"] == 0
    for snip in VideoSnippet.objects.filter(workspace=workspace):
        assert snip.clip_id == clip.id
        # source_clip_ref still stored even when linked
        assert snip.source_clip_ref.endswith("iter10_clip.mp4")


def test_ingest_leaves_clip_null_when_master_absent(workspace):
    result = ingest_manifest(workspace, _manifest())
    assert result["linked"] == 0
    assert result["unlinked"] == 5
    snip = VideoSnippet.objects.filter(workspace=workspace).first()
    assert snip.clip_id is None
    assert snip.source_clip_ref.endswith("iter10_clip.mp4")


def test_command_ingests_from_path(workspace):
    call_command("videos_ingest_snippets", "--workspace", workspace.slug, str(FIXTURE))
    assert VideoSnippet.objects.filter(workspace=workspace).count() == 5


def test_command_accepts_manifest_flag(workspace):
    call_command(
        "videos_ingest_snippets", "--workspace", workspace.slug, "--manifest", str(FIXTURE),
    )
    assert VideoSnippet.objects.filter(workspace=workspace).count() == 5


def test_command_unknown_workspace_errors(db):
    with pytest.raises(CommandError):
        call_command("videos_ingest_snippets", "--workspace", "nope", str(FIXTURE))


def test_command_missing_manifest_arg_errors(workspace):
    with pytest.raises(CommandError):
        call_command("videos_ingest_snippets", "--workspace", workspace.slug)


# ---------------------------------------------------------------------------
# List API
# ---------------------------------------------------------------------------


@pytest.fixture
def member_client(workspace, client):
    user = User.objects.create_user(email="member@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client, workspace


def test_list_snippets_returns_all(member_client):
    client, workspace = member_client
    ingest_manifest(workspace, _manifest())
    resp = client.get(f"/api/w/{workspace.slug}/videos/snippets")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body["snippets"]) == 5
    keys = {s["snippet_key"] for s in body["snippets"]}
    assert "verified-monitoring-scene-1" in keys


def test_list_snippets_filter_by_source_run(member_client):
    client, workspace = member_client
    ingest_manifest(workspace, _manifest())
    resp = client.get(
        f"/api/w/{workspace.slug}/videos/snippets",
        {"source_run": "verified-monitoring-2026-06-16-001"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["snippets"]) == 5
    resp2 = client.get(f"/api/w/{workspace.slug}/videos/snippets", {"source_run": "other"})
    assert resp2.json()["snippets"] == []


def test_list_snippets_filter_by_narrative_slug(member_client):
    client, workspace = member_client
    ingest_manifest(workspace, _manifest())
    resp = client.get(
        f"/api/w/{workspace.slug}/videos/snippets",
        {"narrative_slug": "verified-monitoring"},
    )
    assert len(resp.json()["snippets"]) == 5


def test_list_snippets_filter_by_tag(member_client):
    client, workspace = member_client
    ingest_manifest(workspace, _manifest())
    resp = client.get(
        f"/api/w/{workspace.slug}/videos/snippets", {"tag": "surveyor-scorecard"},
    )
    body = resp.json()
    assert len(body["snippets"]) == 1
    assert body["snippets"][0]["snippet_key"] == "verified-monitoring-scene-3"


def test_list_snippets_exposes_clip_ref_when_linked(member_client):
    client, workspace = member_client
    VideoLibraryEntry.objects.create(
        workspace=workspace, subfolder="vm", filename="iter10_clip.mp4",
        drive_id="d1", name="Master",
    )
    ingest_manifest(workspace, _manifest())
    resp = client.get(f"/api/w/{workspace.slug}/videos/snippets")
    snip = resp.json()["snippets"][0]
    assert snip["clip_ref"] == "library:video/vm/iter10_clip.mp4"


def test_list_snippets_404_for_non_member(db, client):
    creator = User.objects.create_user(email="c@example.com")
    Workspace.objects.create(
        slug="ws-priv", display_name="Priv", drive_root_folder_id="r", created_by=creator,
    )
    outsider = User.objects.create_user(email="out@example.com")
    client.force_login(outsider)
    resp = client.get("/api/w/ws-priv/videos/snippets")
    assert resp.status_code == 404


def test_snippets_endpoint_is_mcp_exposed():
    from apps.api.api import api

    schema = api.get_openapi_schema()
    paths = schema["paths"]
    snip_path = next(p for p in paths if p.endswith("/videos/snippets"))
    assert paths[snip_path]["get"].get("x-mcp-expose") is True
