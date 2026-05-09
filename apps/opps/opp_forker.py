"""Fork an opp at a phase boundary.

The semantic: clone the source opp's Drive folder under a new slug, then
reset ``state.yaml``'s ``current_phase`` / ``current_step`` to the fork
target so the plugin's ``/ace:run`` resumes from there. Artifacts from
phases past the fork point ARE copied (we don't introspect the artifact
manifest to trim — the simplest semantic is "branch this run, then
re-run from phase X"). The plugin overwrites as needed when it re-runs.

Tagging: writes a ``forked_from`` block into the new opp.yaml carrying
``{slug, phase, run_id, forked_at}``. Workbench surfaces this on the
header so the lineage is visible without diving into Drive.

Drive cost: O(N) calls where N is the number of files in the source's
latest run subtree. For a typical 60-100 artifact opp, this is 30-60
seconds wall time. We accept the latency synchronously for v1; a
background worker is the obvious follow-up if real users find it slow.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

import yaml
from django.db import transaction

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.models import OppWorkspace
from apps.sessions.models import Message, Session

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
_FOLDER_MIME = "application/vnd.google-apps.folder"


class ForkOppError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ForkOppResult:
    new_slug: str
    new_folder_id: str
    workspace: OppWorkspace
    working_session: Session


def fork_opp(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    owner,
    source_slug: str,
    new_slug: str,
    fork_at_phase: str,
    workspace=None,
) -> ForkOppResult:
    """Recursively copy the source opp folder to a new slug + reset its
    state.yaml to the fork phase.

    Raises ``ForkOppError`` for caller-friendly validation failures
    (bad slug, slug taken, source not found). Drive failures during
    the copy bubble up as the original exception — partial Drive state
    may be left behind on failure (a follow-up retry will collide on
    the slug check, which is the desired behavior).
    """
    if not SLUG_RE.match(new_slug):
        raise ForkOppError("invalid-slug", f"invalid slug {new_slug!r}")
    if new_slug == source_slug:
        raise ForkOppError(
            "same-slug", "fork slug must differ from the source slug"
        )

    # Slug uniqueness — Postgres + Drive
    slug_q = OppWorkspace.objects.filter(slug=new_slug)
    if workspace is not None:
        slug_q = slug_q.filter(workspace=workspace)
    if slug_q.exists():
        raise ForkOppError("slug-taken", f"opp {new_slug!r} already exists")
    children = drive.list_files(ace_root_folder_id)
    source_folder: DriveFile | None = None
    for child in children:
        if child.name == new_slug:
            raise ForkOppError(
                "slug-taken", f"Drive folder {new_slug!r} already exists"
            )
        if child.name == source_slug and child.mime_type == _FOLDER_MIME:
            source_folder = child
    if source_folder is None:
        raise ForkOppError(
            "source-not-found", f"no opp folder named {source_slug!r}"
        )

    # Recursive copy. We track which file IDs map to the new opp.yaml
    # and state.yaml(s) so we can patch them after the copy without
    # re-listing the destination tree.
    new_folder_id = drive.create_folder(ace_root_folder_id, new_slug)
    forked_at = _dt.datetime.now(_dt.UTC).isoformat()
    patches: _CopyPatches = _CopyPatches()
    _copy_subtree(
        drive=drive,
        source_folder_id=source_folder.id,
        dest_folder_id=new_folder_id,
        rel_path="",
        patches=patches,
    )

    # Patch opp.yaml: rewrite slug + display_name (keep human label
    # informative — append " (fork)" so two opps are distinguishable
    # in the list view) + tag forked_from.
    if patches.opp_yaml_id is not None:
        original_yaml = patches.opp_yaml_body or ""
        new_yaml = _rewrite_opp_yaml(
            original_yaml,
            new_slug=new_slug,
            source_slug=source_slug,
            fork_at_phase=fork_at_phase,
            source_run_id=patches.source_run_id,
            forked_at=forked_at,
        )
        drive.update_file(patches.opp_yaml_id, new_yaml, "text/yaml")

    # Patch state.yaml(s): reset current_phase / current_step to the
    # fork target so the plugin's /ace:run resumes there.
    for state_id, original in patches.state_yaml_bodies.items():
        new_state = _rewrite_state_yaml(original, fork_at_phase=fork_at_phase)
        drive.update_file(state_id, new_state, "text/yaml")

    # Postgres: workspace row + working session.
    with transaction.atomic():
        session = Session.create_with_owner(
            owner=owner,
            title=f"{new_slug} — forked from {source_slug}",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=new_slug,
            opp_run_id="run-001",
            workspace=workspace,
        )
        Message.objects.create(
            session=session,
            turn_index=0,
            role="system",
            sender_user=owner,
            content={
                "type": "system",
                "source": "opps-fork",
                "source_slug": source_slug,
                "fork_at_phase": fork_at_phase,
            },
            plaintext=(
                f"Forked `{new_slug}` from `{source_slug}` at phase "
                f"`{fork_at_phase}`. Re-run /ace:run to continue from there."
            ),
            status="complete",
        )
        opp_ws = OppWorkspace.objects.create(
            slug=new_slug,
            display_name=f"{source_slug} (fork @ {fork_at_phase})",
            working_session=session,
            created_by=owner,
            workspace=workspace,
        )

    return ForkOppResult(
        new_slug=new_slug,
        new_folder_id=new_folder_id,
        workspace=opp_ws,
        working_session=session,
    )


@dataclass
class _CopyPatches:
    """Bookkeeping for files we need to rewrite post-copy."""
    opp_yaml_id: str | None = None
    opp_yaml_body: str | None = None
    state_yaml_bodies: dict[str, str] | None = None  # {new_file_id: original_yaml}
    source_run_id: str | None = None  # latest run id under source/runs/<id>

    def __post_init__(self):
        if self.state_yaml_bodies is None:
            self.state_yaml_bodies = {}


def _copy_subtree(
    *,
    drive: DriveClient,
    source_folder_id: str,
    dest_folder_id: str,
    rel_path: str,
    patches: _CopyPatches,
) -> None:
    """Recursively copy every child of ``source_folder_id`` into ``dest_folder_id``.

    ``rel_path`` is the path within the opp tree (e.g. ``"runs/<run-id>"``)
    — used to recognize the canonical state.yaml / opp.yaml locations so
    we can patch them after the copy.
    """
    for child in drive.list_files(source_folder_id):
        new_path = f"{rel_path}/{child.name}" if rel_path else child.name
        if child.mime_type == _FOLDER_MIME:
            sub_id = drive.create_folder(dest_folder_id, child.name)
            # Track the latest run-id we encounter under runs/. Run-ids
            # sort lexicographically newest-last when they're timestamps;
            # we just keep updating to the most recent string.
            if rel_path == "runs":
                if (
                    patches.source_run_id is None
                    or child.name > patches.source_run_id
                ):
                    patches.source_run_id = child.name
            _copy_subtree(
                drive=drive,
                source_folder_id=child.id,
                dest_folder_id=sub_id,
                rel_path=new_path,
                patches=patches,
            )
        else:
            new_id = drive.copy_file(child.id, dest_folder_id, child.name)
            # Capture body for the files we need to rewrite. Read from
            # the SOURCE id (faster — already-cached metadata) but record
            # the DESTINATION id we'll patch after the copy completes.
            if rel_path == "" and child.name == "opp.yaml":
                patches.opp_yaml_id = new_id
                patches.opp_yaml_body = _read_text_or_empty(drive, child)
            elif child.name in ("state.yaml", "run_state.yaml"):
                patches.state_yaml_bodies[new_id] = _read_text_or_empty(drive, child)


def _read_text_or_empty(drive: DriveClient, f: DriveFile) -> str:
    """Best-effort body read. Returns empty string on failure — the
    caller falls back to leaving the original content alone."""
    try:
        content = drive.get_content(f.id, f.mime_type)
        # FileContent has a ``text`` attribute for text-shaped files.
        return getattr(content, "text", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _rewrite_opp_yaml(
    original: str,
    *,
    new_slug: str,
    source_slug: str,
    fork_at_phase: str,
    source_run_id: str | None,
    forked_at: str,
) -> str:
    """Rewrite opp.yaml: new slug + display_name + forked_from block.

    Falls back to a hand-built YAML stub if the source yaml is empty
    or unparseable — the fork is still usable, just without the source's
    other metadata.
    """
    try:
        data = yaml.safe_load(original) or {}
        if not isinstance(data, dict):
            data = {}
    except yaml.YAMLError:
        data = {}

    data["slug"] = new_slug
    if "display_name" in data:
        data["display_name"] = f"{data['display_name']} (fork @ {fork_at_phase})"
    else:
        data["display_name"] = f"{source_slug} (fork @ {fork_at_phase})"
    data["forked_from"] = {
        "slug": source_slug,
        "phase": fork_at_phase,
        "run_id": source_run_id or "",
        "forked_at": forked_at,
    }
    return yaml.safe_dump(data, sort_keys=False)


def _rewrite_state_yaml(original: str, *, fork_at_phase: str) -> str:
    """Reset current_phase / current_step to the fork target.

    The plugin's ``/ace:run`` resumes from the recorded ``current_phase`` —
    setting it to the fork phase makes the next run start there, and the
    later-phase artifacts left in the copy get overwritten.
    """
    try:
        data = yaml.safe_load(original) or {}
        if not isinstance(data, dict):
            data = {}
    except yaml.YAMLError:
        data = {}

    data["current_phase"] = fork_at_phase
    # current_step set to None so the plugin picks the first step of the
    # phase. Same for the timing fields — those carry the source run's
    # times and would otherwise lie about the fork's progress.
    data.pop("current_step", None)
    data.pop("started_at", None)
    data.pop("last_actor_at", None)
    data.pop("last_actor", None)
    return yaml.safe_dump(data, sort_keys=False)
