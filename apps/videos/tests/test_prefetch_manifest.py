"""Tests for ``prefetch_manifest_to_cache``.

Before the npm hydrate chain runs, the server walks the staged spec.yaml
manifest and downloads any ``gdrive:<id>.<ext>`` ref not yet in the
local render cache (``~/.cache/connect-videos/``). Without this, the
hydrate step exits 1 because every Drive ref is "missing from cache" —
the laptop dev flow expects the operator to have used the ace-gdrive
MCP first.
"""
from __future__ import annotations

from pathlib import Path
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
def home_cache(tmp_path, monkeypatch):
    """Redirect Path.home() to a tmp dir so prefetch writes into a
    pytest-managed location instead of the real ~/.cache."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return tmp_path / "home"


def _write_spec(workspace, fake_drive, slug, run_id, manifest: dict[str, str]):
    """Drive-write a minimal spec with the given manifest. The staged
    copy is what prefetch_manifest_to_cache reads."""
    layout = drive.resolve_layout(workspace, fake_drive.client)
    body = "name: Demo\nworkspace: dimagi-team\nmanifest:\n"
    for alias, value in manifest.items():
        body += f"  {alias}: \"{value}\"\n"
    drive.write_spec(layout, fake_drive.client, slug, run_id, body)


def _stage(workspace, slug, run_id):
    """Force the spec onto local disk so prefetch can read it."""
    service._stage_spec(workspace, slug, run_id)


def test_prefetch_downloads_missing_gdrive_refs(
    workspace, fake_drive, videos_root, home_cache,
):
    """gdrive: refs missing from the cache get downloaded."""
    layout = drive.resolve_layout(workspace, fake_drive.client)
    # Upload one file at the workspace root so we can prove get_binary works.
    file_id = fake_drive.client.upload_binary(
        fake_drive.root_id, "src.mp4", b"pretend-mp4-bytes", "video/mp4",
    )

    _write_spec(workspace, fake_drive, "demo", "run-001", {
        "hero": f"gdrive:{file_id}.mp4",
    })
    _stage(workspace, "demo", "run-001")

    counts = service.prefetch_manifest_to_cache(workspace, "demo", "run-001")
    assert counts == {"downloaded": 1, "skipped": 0, "errored": 0}

    cached = home_cache / ".cache" / "connect-videos" / f"{file_id}.mp4"
    assert cached.read_bytes() == b"pretend-mp4-bytes"


def test_prefetch_skips_already_cached(workspace, fake_drive, videos_root, home_cache):
    """Files already in the cache are not re-fetched."""
    file_id = fake_drive.client.upload_binary(
        fake_drive.root_id, "x.mp4", b"orig", "video/mp4",
    )
    _write_spec(workspace, fake_drive, "demo", "run-001", {
        "x": f"gdrive:{file_id}.mp4",
    })
    _stage(workspace, "demo", "run-001")

    cache_dir = home_cache / ".cache" / "connect-videos"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{file_id}.mp4").write_bytes(b"already-here")

    counts = service.prefetch_manifest_to_cache(workspace, "demo", "run-001")
    assert counts == {"downloaded": 0, "skipped": 1, "errored": 0}
    # Cache untouched
    assert (cache_dir / f"{file_id}.mp4").read_bytes() == b"already-here"


def test_prefetch_ignores_non_gdrive_refs(workspace, fake_drive, videos_root, home_cache):
    """library: / file: / plain manifest values are skipped (library:
    refs are rewritten to gdrive: by _stage_spec before prefetch sees
    them; other forms are operator-managed)."""
    _write_spec(workspace, fake_drive, "demo", "run-001", {
        "literal": "file:something.mp4",
        "plain": "/abs/path.mp4",
    })
    _stage(workspace, "demo", "run-001")

    counts = service.prefetch_manifest_to_cache(workspace, "demo", "run-001")
    assert counts == {"downloaded": 0, "skipped": 0, "errored": 0}


def test_prefetch_records_errors_without_failing(
    workspace, fake_drive, videos_root, home_cache,
):
    """Drive errors per-file count as errored; prefetch keeps going on
    other files."""
    good_id = fake_drive.client.upload_binary(
        fake_drive.root_id, "g.mp4", b"good", "video/mp4",
    )
    _write_spec(workspace, fake_drive, "demo", "run-001", {
        "ok": f"gdrive:{good_id}.mp4",
        "broken": "gdrive:nonexistent999.mp4",  # not in fake_drive
    })
    _stage(workspace, "demo", "run-001")

    counts = service.prefetch_manifest_to_cache(workspace, "demo", "run-001")
    assert counts["downloaded"] == 1
    assert counts["errored"] == 1


def test_prefetch_no_manifest_is_noop(workspace, fake_drive, videos_root, home_cache):
    """A spec with no manifest block returns zero counts."""
    layout = drive.resolve_layout(workspace, fake_drive.client)
    drive.write_spec(
        layout, fake_drive.client, "demo", "run-001",
        "name: Demo\nworkspace: dimagi-team\n",
    )
    _stage(workspace, "demo", "run-001")

    counts = service.prefetch_manifest_to_cache(workspace, "demo", "run-001")
    assert counts == {"downloaded": 0, "skipped": 0, "errored": 0}


def test_prefetch_no_staged_spec_is_noop(workspace, fake_drive, videos_root, home_cache):
    """If the spec hasn't been staged locally yet, prefetch is a no-op
    instead of crashing."""
    counts = service.prefetch_manifest_to_cache(workspace, "never", "run-001")
    assert counts == {"downloaded": 0, "skipped": 0, "errored": 0}
