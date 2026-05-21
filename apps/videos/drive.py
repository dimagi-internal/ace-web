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
RUNS_FOLDER = "runs"
SPEC_FILENAME = "spec.yaml"
YAML_MIME = "application/x-yaml"

# Legacy layout — kept readable through Phase B; removed in Phase C.
EXISTING_CONTENT = "existing_content"
EXISTING_CONTENT_AUDIO = "audio"
EXISTING_CONTENT_SHARED = "shared"
EXISTING_CONTENT_SUBDIRS = (EXISTING_CONTENT_AUDIO, EXISTING_CONTENT_SHARED)

# New layout — destination of the relocation.
LIBRARY = "library"
LIBRARY_VIDEO = "video"
LIBRARY_AUDIO = "audio"
LIBRARY_MEDIA_KINDS = (LIBRARY_VIDEO, LIBRARY_AUDIO)
SHARED_TOP = "shared"  # sibling of library/, at videos/shared/

# Per-run artifact filenames + mime types.
OUTPUT_MP4_FILENAME = "output.mp4"
OUTPUT_MP4_MIME = "video/mp4"
EXPLORER_ARCHIVE_FILENAME = "explorer.tar.gz"
EXPLORER_ARCHIVE_MIME = "application/gzip"
FEEDBACK_FILENAME = "feedback.md"
FEEDBACK_MIME = "text/markdown"

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


def spec_modified_time(
    layout: DriveLayout, client: DriveClient, program_slug: str, run_id: str,
) -> str | None:
    """Return spec.yaml's `modifiedTime` from Drive, or None if absent.

    Used by the run detail endpoint to drive the "stale render"
    indicator: the editor compares this Drive-source-of-truth mtime
    against final.mp4's local mtime to tell the user when their saved
    edits haven't been re-rendered yet."""
    rid = run_folder_id(layout, client, program_slug, run_id)
    if rid is None:
        return None
    spec_meta = _find_child(client, rid, SPEC_FILENAME)
    if spec_meta is None:
        return None
    return spec_meta.modified_time


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


_NON_PROGRAM_FOLDERS = frozenset({EXISTING_CONTENT, LIBRARY, SHARED_TOP})


def list_program_slugs(layout: DriveLayout, client: DriveClient) -> list[str]:
    """All program folder names under videos/. Sorted, excludes
    infrastructure folders (existing_content, library, shared) and
    anything that isn't a folder or starts with an underscore."""
    out: list[str] = []
    for f in client.list_folder(layout.videos_folder_id):
        if f.mime_type != "application/vnd.google-apps.folder":
            continue
        if f.name in _NON_PROGRAM_FOLDERS:
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
# existing_content/ — shared binary assets (audio cache + music bed)
# ---------------------------------------------------------------------------


def existing_content_folder_id(
    layout: DriveLayout, client: DriveClient,
    subdir: str | None = None, *, create: bool = False,
) -> str | None:
    """Return the Drive folder id for `videos/existing_content/` or one
    of its subdirs (audio/, shared/). Pass create=True to materialize
    on first use."""
    if subdir is not None and subdir not in EXISTING_CONTENT_SUBDIRS:
        raise ValueError(
            f"Unknown existing_content subdir: {subdir}; "
            f"expected one of {EXISTING_CONTENT_SUBDIRS}"
        )
    existing = _find_child(client, layout.videos_folder_id, EXISTING_CONTENT)
    if existing is None or existing.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        root_id = client.create_folder(layout.videos_folder_id, EXISTING_CONTENT)
    else:
        root_id = existing.id
    if subdir is None:
        return root_id
    sub = _find_child(client, root_id, subdir)
    if sub is None or sub.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        return client.create_folder(root_id, subdir)
    return sub.id


def list_existing_content(
    layout: DriveLayout, client: DriveClient, subdir: str,
) -> list[DriveFile]:
    """List files in `videos/existing_content/<subdir>/`. Excludes
    folders. Empty list if the folder doesn't exist yet."""
    folder_id = existing_content_folder_id(layout, client, subdir)
    if folder_id is None:
        return []
    return [
        f for f in client.list_folder(folder_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]


def find_existing_content_file(
    layout: DriveLayout, client: DriveClient, subdir: str, filename: str,
) -> DriveFile | None:
    """Look for one file by name. None if not found."""
    folder_id = existing_content_folder_id(layout, client, subdir)
    if folder_id is None:
        return None
    return _find_child(client, folder_id, filename)


def upload_existing_content(
    layout: DriveLayout, client: DriveClient,
    subdir: str, filename: str, content: bytes, mime_type: str,
) -> str:
    """Create-or-replace `videos/existing_content/<subdir>/<filename>`.
    Returns the file id. Materializes parent folders if needed.

    Idempotent on byte-identical content (still issues an update call,
    but the content is unchanged). For size-based skip behavior the
    caller should consult ``find_existing_content_file`` first.
    """
    folder_id = existing_content_folder_id(layout, client, subdir, create=True)
    assert folder_id is not None
    existing = _find_child(client, folder_id, filename)
    if existing is not None:
        client.update_binary(existing.id, content, mime_type)
        return existing.id
    return client.upload_binary(folder_id, filename, content, mime_type)


def read_existing_content(
    layout: DriveLayout, client: DriveClient, subdir: str, filename: str,
) -> bytes | None:
    """Fetch the raw bytes of one file. None if absent."""
    meta = find_existing_content_file(layout, client, subdir, filename)
    if meta is None:
        return None
    return client.get_binary(meta.id)


# ---------------------------------------------------------------------------
# library/ — curated media + shared/ — music bed + brand assets
# ---------------------------------------------------------------------------


def library_folder_id(
    layout: DriveLayout, client: DriveClient,
    media: str | None = None, subfolder: str | None = None,
    *, create: bool = False,
) -> str | None:
    """Resolve videos/library/, videos/library/<media>/, or
    videos/library/<media>/<subfolder>/.

    Pass create=True to materialize missing parents.
    """
    if media is not None and media not in LIBRARY_MEDIA_KINDS:
        raise ValueError(
            f"Unknown library media: {media!r}; "
            f"expected one of {LIBRARY_MEDIA_KINDS}"
        )
    if subfolder is not None and media is None:
        raise ValueError("subfolder requires media")

    root = _find_child(client, layout.videos_folder_id, LIBRARY)
    if root is None or root.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        root_id = client.create_folder(layout.videos_folder_id, LIBRARY)
    else:
        root_id = root.id

    if media is None:
        return root_id

    media_node = _find_child(client, root_id, media)
    if media_node is None or media_node.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        media_id = client.create_folder(root_id, media)
    else:
        media_id = media_node.id

    if subfolder is None:
        return media_id

    sub = _find_child(client, media_id, subfolder)
    if sub is None or sub.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        return client.create_folder(media_id, subfolder)
    return sub.id


def list_library_subfolders(
    layout: DriveLayout, client: DriveClient, media: str,
) -> list[DriveFile]:
    """Direct subfolders under videos/library/<media>/.

    Empty list when library/<media>/ does not exist yet.
    """
    media_id = library_folder_id(layout, client, media)
    if media_id is None:
        return []
    return [
        f for f in client.list_folder(media_id)
        if f.mime_type == "application/vnd.google-apps.folder"
    ]


def list_library_files(
    layout: DriveLayout, client: DriveClient,
    media: str, subfolder: str,
) -> list[DriveFile]:
    """Direct files under videos/library/<media>/<subfolder>/.

    Returns both media files and sidecars; folders excluded. Empty list
    when the subfolder doesn't exist.
    """
    folder_id = library_folder_id(layout, client, media, subfolder)
    if folder_id is None:
        return []
    return [
        f for f in client.list_folder(folder_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]


def list_audio_library_files(
    layout: DriveLayout, client: DriveClient,
) -> list[DriveFile]:
    """Direct files under videos/library/audio/ (flat layout — no subfolders).

    Returns both .mp3 and .json files; folders excluded.
    """
    media_id = library_folder_id(layout, client, LIBRARY_AUDIO)
    if media_id is None:
        return []
    return [
        f for f in client.list_folder(media_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]


def read_library_file(
    layout: DriveLayout, client: DriveClient,
    media: str, name: str,
    *, subfolder: str | None = None,
) -> bytes | None:
    """Read one file under library/<media>/[<subfolder>/]<name>.

    For audio (flat) pass subfolder=None. For video (subfoldered) pass
    the subfolder.
    """
    if media == LIBRARY_AUDIO:
        files = list_audio_library_files(layout, client)
    else:
        if subfolder is None:
            raise ValueError("video reads require a subfolder")
        files = list_library_files(layout, client, media, subfolder)
    for f in files:
        if f.name == name:
            return client.get_binary(f.id)
    return None


def upload_library_file(
    layout: DriveLayout, client: DriveClient,
    media: str, name: str, content: bytes, mime_type: str,
    *, subfolder: str | None = None,
) -> str:
    """Create-or-replace a library file. Materializes parents if needed.

    For audio pass subfolder=None (audio is flat); for video pass the subfolder.
    Returns the Drive file id.
    """
    if media == LIBRARY_AUDIO:
        folder_id = library_folder_id(layout, client, LIBRARY_AUDIO, create=True)
    else:
        if subfolder is None:
            raise ValueError("video uploads require a subfolder")
        folder_id = library_folder_id(layout, client, media, subfolder, create=True)
    assert folder_id is not None
    existing = _find_child(client, folder_id, name)
    if existing is not None:
        client.update_binary(existing.id, content, mime_type)
        return existing.id
    return client.upload_binary(folder_id, name, content, mime_type)


def shared_top_folder_id(
    layout: DriveLayout, client: DriveClient, *, create: bool = False,
) -> str | None:
    """Resolve videos/shared/ (sibling of library/)."""
    existing = _find_child(client, layout.videos_folder_id, SHARED_TOP)
    if existing is None or existing.mime_type != "application/vnd.google-apps.folder":
        if not create:
            return None
        return client.create_folder(layout.videos_folder_id, SHARED_TOP)
    return existing.id


def list_shared_top_files(
    layout: DriveLayout, client: DriveClient,
) -> list[DriveFile]:
    folder_id = shared_top_folder_id(layout, client)
    if folder_id is None:
        return []
    return [
        f for f in client.list_folder(folder_id)
        if f.mime_type != "application/vnd.google-apps.folder"
    ]


# ---------------------------------------------------------------------------
# Per-run render artifacts: output.mp4, explorer.tar.gz, feedback.md
# ---------------------------------------------------------------------------


def _put_binary_in_run(
    layout: DriveLayout, client: DriveClient,
    slug: str, run_id: str, filename: str, content: bytes, mime_type: str,
) -> str:
    """Create-or-replace a binary file inside `videos/<slug>/runs/<run_id>/`.
    Returns the Drive file id."""
    rid = run_folder_id(layout, client, slug, run_id, create=True)
    assert rid is not None
    existing = _find_child(client, rid, filename)
    if existing is not None:
        client.update_binary(existing.id, content, mime_type)
        return existing.id
    return client.upload_binary(rid, filename, content, mime_type)


def _get_binary_in_run(
    layout: DriveLayout, client: DriveClient,
    slug: str, run_id: str, filename: str,
) -> bytes | None:
    rid = run_folder_id(layout, client, slug, run_id)
    if rid is None:
        return None
    meta = _find_child(client, rid, filename)
    if meta is None:
        return None
    return client.get_binary(meta.id)


def _find_in_run(
    layout: DriveLayout, client: DriveClient,
    slug: str, run_id: str, filename: str,
) -> DriveFile | None:
    rid = run_folder_id(layout, client, slug, run_id)
    if rid is None:
        return None
    return _find_child(client, rid, filename)


# output.mp4

def upload_output_mp4(
    layout: DriveLayout, client: DriveClient,
    slug: str, run_id: str, content: bytes,
) -> str:
    return _put_binary_in_run(
        layout, client, slug, run_id, OUTPUT_MP4_FILENAME, content, OUTPUT_MP4_MIME,
    )


def read_output_mp4(
    layout: DriveLayout, client: DriveClient, slug: str, run_id: str,
) -> bytes | None:
    return _get_binary_in_run(layout, client, slug, run_id, OUTPUT_MP4_FILENAME)


def output_mp4_drive_meta(
    layout: DriveLayout, client: DriveClient, slug: str, run_id: str,
) -> DriveFile | None:
    """Return Drive metadata (id, web_view_link, size, modified_time) for
    the output.mp4 if it's been published. Used to build share links."""
    return _find_in_run(layout, client, slug, run_id, OUTPUT_MP4_FILENAME)


# explorer.tar.gz

def upload_explorer_archive(
    layout: DriveLayout, client: DriveClient,
    slug: str, run_id: str, content: bytes,
) -> str:
    return _put_binary_in_run(
        layout, client, slug, run_id, EXPLORER_ARCHIVE_FILENAME, content,
        EXPLORER_ARCHIVE_MIME,
    )


def read_explorer_archive(
    layout: DriveLayout, client: DriveClient, slug: str, run_id: str,
) -> bytes | None:
    return _get_binary_in_run(
        layout, client, slug, run_id, EXPLORER_ARCHIVE_FILENAME,
    )


def explorer_archive_drive_meta(
    layout: DriveLayout, client: DriveClient, slug: str, run_id: str,
) -> DriveFile | None:
    """Return Drive metadata (id, modifiedTime, size) for the
    explorer.tar.gz if it's been published. Lets the program-list /
    run-detail endpoints flip the "not built" badge to "built" on
    hosts that didn't render (labs, fresh dev) without forcing a
    full byte download."""
    return _find_in_run(layout, client, slug, run_id, EXPLORER_ARCHIVE_FILENAME)


# feedback.md  (text — uses upload_file/update_file, not the binary surface)

def write_feedback(
    layout: DriveLayout, client: DriveClient,
    slug: str, run_id: str, content: str,
) -> str:
    rid = run_folder_id(layout, client, slug, run_id, create=True)
    assert rid is not None
    existing = _find_child(client, rid, FEEDBACK_FILENAME)
    if existing is not None:
        client.update_file(existing.id, content, FEEDBACK_MIME)
        return existing.id
    return client.upload_file(rid, FEEDBACK_FILENAME, content, FEEDBACK_MIME)


def read_feedback(
    layout: DriveLayout, client: DriveClient, slug: str, run_id: str,
) -> str | None:
    rid = run_folder_id(layout, client, slug, run_id)
    if rid is None:
        return None
    meta = _find_child(client, rid, FEEDBACK_FILENAME)
    if meta is None:
        return None
    return client.get_content(meta.id, "text/plain").content


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
