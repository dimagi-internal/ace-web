"""Drive-side storage for video program specs.

Layout under each workspace's Drive root folder:

    <workspace.drive_root>/
    └── videos/
        ├── existing_content/         ← shared assets (music bed, audio cache)
        │   ├── audio/<hash>.mp3
        │   └── music/<file>.mp3
        ├── <program-slug>/
        │   └── runs/
        │       ├── run-001/spec.yaml
        │       └── run-002/spec.yaml
        └── ...

Mirrors apps/opps' Drive-source-of-truth pattern. Renders still happen
on local disk — when a render fires, the service syncs the run's
spec.yaml from Drive to local scratch and shells out to npm.

This module is intentionally thin: find/create the right Drive folder,
read text content, write text content. Cache invalidation + ETag round-
trips can be layered on later if performance becomes a problem.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from apps.opps.drive_client import DriveClient, DriveFile, get_drive_client
from apps.workspaces.models import Workspace

log = logging.getLogger(__name__)


VIDEOS_FOLDER = "videos"
EXISTING_CONTENT = "existing_content"
RUNS_FOLDER = "runs"
SPEC_FILENAME = "spec.yaml"
YAML_MIME = "application/x-yaml"

_RUN_RE = re.compile(r"^run-(\d{3,})$")


@dataclass(frozen=True)
class DriveLayout:
    """Resolved Drive folder IDs for a workspace's videos namespace.

    Cached per (workspace_id, client) — Drive folder IDs are stable, so
    once we've resolved them we can hold onto them for the request.
    """
    videos_folder_id: str
    workspace_root_id: str

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"DriveLayout(videos={self.videos_folder_id})"


class VideosDriveError(Exception):
    """Surface-level errors so callers can translate to ProblemError."""


# ---------------------------------------------------------------------------
# Folder navigation
# ---------------------------------------------------------------------------


def _find_child(client: DriveClient, parent_id: str, name: str) -> DriveFile | None:
    """Look for a direct child by name in a Drive folder. None if missing."""
    for f in client.list_folder(parent_id):
        if f.name == name:
            return f
    return None


def _find_or_create_folder(client: DriveClient, parent_id: str, name: str) -> str:
    existing = _find_child(client, parent_id, name)
    if existing is not None and existing.mime_type == "application/vnd.google-apps.folder":
        return existing.id
    return client.create_folder(parent_id, name)


def resolve_layout(workspace: Workspace, client: DriveClient) -> DriveLayout:
    """Find or create the workspace's `videos/` folder, return its id.

    Idempotent — safe to call on every request. The folder gets created
    the first time a workspace touches videos and then persists.
    """
    root = workspace.drive_root_folder_id
    if not root:
        raise VideosDriveError(
            f"Workspace {workspace.slug} has no drive_root_folder_id"
        )
    videos_id = _find_or_create_folder(client, root, VIDEOS_FOLDER)
    return DriveLayout(videos_folder_id=videos_id, workspace_root_id=root)


def program_folder_id(
    layout: DriveLayout, client: DriveClient, program_slug: str, *, create: bool = False
) -> str | None:
    """Return the Drive folder id for a program, or None if missing.

    Pass create=True to create the program + runs subfolders on first use
    (used by the create-program path).
    """
    existing = _find_child(client, layout.videos_folder_id, program_slug)
    if existing is not None and existing.mime_type == "application/vnd.google-apps.folder":
        return existing.id
    if not create:
        return None
    program_id = client.create_folder(layout.videos_folder_id, program_slug)
    client.create_folder(program_id, RUNS_FOLDER)
    return program_id


def runs_folder_id(
    layout: DriveLayout, client: DriveClient, program_slug: str
) -> str | None:
    pf = program_folder_id(layout, client, program_slug)
    if pf is None:
        return None
    runs = _find_child(client, pf, RUNS_FOLDER)
    if runs is None or runs.mime_type != "application/vnd.google-apps.folder":
        return None
    return runs.id


def run_folder_id(
    layout: DriveLayout, client: DriveClient, program_slug: str, run_id: str,
    *, create: bool = False,
) -> str | None:
    runs = runs_folder_id(layout, client, program_slug)
    if runs is None:
        if not create:
            return None
        # Materialize parent folders.
        program_folder_id(layout, client, program_slug, create=True)
        runs = runs_folder_id(layout, client, program_slug)
        if runs is None:  # pragma: no cover - shouldn't happen post-create
            return None
    existing = _find_child(client, runs, run_id)
    if existing is not None and existing.mime_type == "application/vnd.google-apps.folder":
        return existing.id
    if not create:
        return None
    return client.create_folder(runs, run_id)


# ---------------------------------------------------------------------------
# Spec.yaml read/write
# ---------------------------------------------------------------------------


def read_spec(
    layout: DriveLayout, client: DriveClient, program_slug: str, run_id: str,
) -> str | None:
    """Return the raw spec.yaml text for a run, or None if absent."""
    rid = run_folder_id(layout, client, program_slug, run_id)
    if rid is None:
        return None
    spec_meta = _find_child(client, rid, SPEC_FILENAME)
    if spec_meta is None:
        return None
    body = client.get_content(spec_meta.id, "text/plain")
    return body.content


def write_spec(
    layout: DriveLayout, client: DriveClient, program_slug: str, run_id: str,
    content: str,
) -> str:
    """Create-or-replace `programs/<slug>/runs/<run_id>/spec.yaml` in
    Drive. Returns the file id. Materializes parent folders if needed.
    """
    rid = run_folder_id(layout, client, program_slug, run_id, create=True)
    assert rid is not None
    existing = _find_child(client, rid, SPEC_FILENAME)
    if existing is not None:
        client.update_file(existing.id, content, YAML_MIME)
        return existing.id
    return client.upload_file(rid, SPEC_FILENAME, content, YAML_MIME)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_program_slugs(layout: DriveLayout, client: DriveClient) -> list[str]:
    """All program folder names under videos/. Sorted, excludes
    existing_content + anything that isn't a folder."""
    out: list[str] = []
    for f in client.list_folder(layout.videos_folder_id):
        if f.mime_type != "application/vnd.google-apps.folder":
            continue
        if f.name == EXISTING_CONTENT:
            continue
        if f.name.startswith("_"):
            continue
        out.append(f.name)
    out.sort()
    return out


def list_run_ids(layout: DriveLayout, client: DriveClient, program_slug: str) -> list[str]:
    runs = runs_folder_id(layout, client, program_slug)
    if runs is None:
        return []
    out: list[str] = []
    for f in client.list_folder(runs):
        if f.mime_type != "application/vnd.google-apps.folder":
            continue
        if _RUN_RE.match(f.name):
            out.append(f.name)
    out.sort()
    return out


def latest_run_id(layout: DriveLayout, client: DriveClient, program_slug: str) -> str | None:
    ids = list_run_ids(layout, client, program_slug)
    return ids[-1] if ids else None


def next_run_id(layout: DriveLayout, client: DriveClient, program_slug: str) -> str:
    ids = list_run_ids(layout, client, program_slug)
    if not ids:
        return "run-001"
    n = int(ids[-1].removeprefix("run-"))
    return f"run-{n + 1:03d}"


# ---------------------------------------------------------------------------
# Render-time sync: Drive → local scratch
# ---------------------------------------------------------------------------


def stage_spec_locally(
    layout: DriveLayout, client: DriveClient,
    program_slug: str, run_id: str,
    local_root: Path,
) -> Path:
    """Pull the run's spec.yaml from Drive and write it to
    ``local_root/programs/<slug>/runs/<run_id>/spec.yaml``.

    Called right before kicking off a render so the Node toolchain
    (which reads from local disk) sees the latest content. Raises
    if the spec isn't found in Drive.
    """
    content = read_spec(layout, client, program_slug, run_id)
    if content is None:
        raise VideosDriveError(
            f"Spec not found in Drive: videos/{program_slug}/runs/{run_id}/spec.yaml"
        )
    target = local_root / "programs" / program_slug / "runs" / run_id / "spec.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Client factory wrapper
# ---------------------------------------------------------------------------


def client_for_workspace(workspace: Workspace) -> DriveClient:
    """Resolve the same SA Drive client opps uses, scoped to this workspace."""
    return get_drive_client(workspace=workspace)
