"""Copy one run, whole, into another workspace (clone-to-new-workspace).

The ace-web half of `/ace:clone-to-new-workspace`. Unlike a fork
(`opp_forker.py`), which mints a new run inside the same opp and trims it to
a fork point, a clone:

* lands under the TARGET workspace's Drive root, as
  ``<opp-slug>/runs/<same run-id>/``;
* copies the run verbatim — every phase folder, including the Phase 6
  screenshots and videos a reviewer needs (a fork skips those);
* brings the opp-level files (``opp.yaml``, ``pdd.md``, ``inputs/`` …) the
  first time an opp is cloned into a workspace, so the new opp is workable;
  a later clone of another run of the same opp reuses them;
* creates the target ``OppWorkspace`` with the TARGET workspace's default
  tenancy — the new opp's assets belong in the new workspace's areas.

The copied ``run_state.yaml`` still points at the source tenancy's assets
(HQ apps, Connect opportunity, bot…). ACE's clone command rebuilds those in
the new tenancy, system by system, and rewrites the products as it goes.

The source run is never written to; the record of the clone is a
``RunClone`` row. ``run_state.yaml`` is copied FIRST, as in a fork
(ace-web#734), so a stalled clone leaves a resumable run, not a pile of files.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § C.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)

_FOLDER_MIME = "application/vnd.google-apps.folder"
_RUN_STATE = "run_state.yaml"
# Progress is written to the RunClone row every N files, not every file.
_PROGRESS_EVERY = 10


class CloneError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class CloneResult:
    clone_id: int
    opp_slug: str
    run_id: str
    target_run_folder_id: str
    files_copied: int


def _child(files: list[DriveFile], name: str, *, folder: bool) -> DriveFile | None:
    for f in files:
        if f.name == name and (f.mime_type == _FOLDER_MIME) == folder:
            return f
    return None


# The opp-level files a clone carries: identity (opp.yaml), the idea and PDD,
# and the inputs the PDD was built from. Anything else at the opp root is ACE's
# internal working state and stays in the source workspace.
_OPP_LEVEL_FILES = frozenset({"opp.yaml", "idea.md", "pdd.md", "inputs"})


class _Copier:
    def __init__(self, drive: DriveClient, record):
        self.drive = drive
        self.record = record
        self.copied = 0

    def file(self, f: DriveFile, dest_folder_id: str) -> None:
        self.drive.copy_file(f.id, dest_folder_id, f.name)
        self.copied += 1
        if self.copied % _PROGRESS_EVERY == 0:
            self.record.files_copied = self.copied
            self.record.save(update_fields=["files_copied", "updated_at"])

    def tree(
        self,
        source_folder_id: str,
        dest_folder_id: str,
        *,
        skip: frozenset[str] = frozenset(),
        only: frozenset[str] | None = None,
    ) -> None:
        for child in self.drive.list_files(source_folder_id):
            if child.name in skip or (only is not None and child.name not in only):
                continue
            if child.mime_type == _FOLDER_MIME:
                sub = self.drive.create_folder(dest_folder_id, child.name)
                self.tree(child.id, sub)
            else:
                self.file(child, dest_folder_id)


def clone_run(
    *, drive: DriveClient, source, target, opp_slug: str, run_id: str, owner
) -> CloneResult:
    """Copy ``source``'s ``opp_slug/runs/run_id`` into ``target``. Blocking:
    one Drive copy per file. Raises ``CloneError`` for caller-facing
    validation failures; a Drive failure mid-copy marks the record ``error``
    and re-raises, leaving a partial run with its ``run_state.yaml``."""
    from apps.opps import tenancy as tenancy_mod
    from apps.opps.models import OppWorkspace
    from apps.workspaces.models import RunClone

    if source.pk == target.pk:
        raise CloneError("same-workspace", "source and target are the same workspace")

    src_opp = _child(drive.list_files(source.drive_root_folder_id), opp_slug, folder=True)
    if src_opp is None:
        raise CloneError("source-not-found", f"no opp folder named {opp_slug!r}")
    src_opp_children = drive.list_files(src_opp.id)
    src_runs = _child(src_opp_children, "runs", folder=True)
    src_run = _child(drive.list_files(src_runs.id), run_id, folder=True) if src_runs else None
    if src_run is None:
        raise CloneError("source-run-not-found", f"opp {opp_slug!r} has no run {run_id!r}")

    dst_root_children = drive.list_files(target.drive_root_folder_id)
    dst_opp = _child(dst_root_children, opp_slug, folder=True)
    dst_runs = None
    if dst_opp is not None:
        dst_runs = _child(drive.list_files(dst_opp.id), "runs", folder=True)
        if dst_runs is not None and _child(drive.list_files(dst_runs.id), run_id, folder=True):
            raise CloneError(
                "already-cloned",
                f"{target.slug} already has {opp_slug}/runs/{run_id}; trash it there to re-clone",
            )

    record = RunClone.objects.create(
        source_workspace=source, target_workspace=target, opp_slug=opp_slug,
        run_id=run_id, created_by=owner,
    )
    copier = _Copier(drive, record)
    try:
        if dst_opp is None:
            dst_opp_id = drive.create_folder(target.drive_root_folder_id, opp_slug)
            # Opp-level files, once — an ALLOWLIST, not "everything above
            # runs/". The opp root is where ACE keeps its own working notes
            # (open-questions.md, eval-calibration/, the inbox-triage
            # comms-log, parked email drafts), and a clone exists to be shown
            # to outside reviewers. spark-facilitator's root held all four,
            # including an unsent draft addressed to the reviewer. Other runs
            # are not copied either — a clone is one run.
            copier.tree(src_opp.id, dst_opp_id, only=_OPP_LEVEL_FILES)
        else:
            dst_opp_id = dst_opp.id
        dst_runs_id = dst_runs.id if dst_runs else drive.create_folder(dst_opp_id, "runs")
        dst_run_id = drive.create_folder(dst_runs_id, run_id)

        run_children = drive.list_files(src_run.id)
        state = _child(run_children, _RUN_STATE, folder=False)
        if state is not None:
            copier.file(state, dst_run_id)
        copier.tree(src_run.id, dst_run_id, skip=frozenset({_RUN_STATE}))
    except Exception as exc:
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"[:2000]
        record.files_copied = copier.copied
        record.save(update_fields=["status", "error", "files_copied", "updated_at"])
        log.warning(
            "clone %s/%s/%s -> %s failed: %s", source.slug, opp_slug, run_id, target.slug, exc
        )
        raise

    src_row = OppWorkspace.objects.filter(workspace=source, slug=opp_slug).first()
    OppWorkspace.objects.get_or_create(
        workspace=target,
        slug=opp_slug,
        defaults={
            "display_name": src_row.display_name if src_row else opp_slug,
            "tags": list(src_row.tags) if src_row else [],
            "created_by": owner,
            "tenancy": tenancy_mod.clean(target.default_tenancy),
        },
    )
    record.status = "done"
    record.files_copied = copier.copied
    record.save(update_fields=["status", "files_copied", "updated_at"])
    return CloneResult(
        clone_id=record.pk, opp_slug=opp_slug, run_id=run_id,
        target_run_folder_id=dst_run_id, files_copied=copier.copied,
    )
