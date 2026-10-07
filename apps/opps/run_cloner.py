"""Copy one run, whole, into another workspace (clone-to-new-workspace).

The ace-web half of `/ace:clone-to-new-workspace`. Unlike a fork
(`opp_forker.py`), which mints a new run inside the same opp and trims it to
a fork point, a clone:

* lands under the TARGET workspace's Drive root, as
  ``<opp-slug>/runs/<same run-id>/``;
* copies the run verbatim — every phase folder, including the Phase 6
  screenshots and videos a reviewer needs (a fork skips those);
* brings the opp-level files (``opp.yaml``, ``idea.md``, ``pdd.md``,
  ``inputs/``) the first time an opp is cloned into a workspace, so the new
  opp is workable; a later clone of another run of the same opp reuses them.
  No legacy ledger rides along: the run's open asks are a filter of its own
  ``decisions.yaml``, which is copied with the run;
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

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass

from apps.opps.doc_ids import id_pattern
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
# and the inputs the PDD was built from. Anything else at the opp root is
# ACE's internal working state and stays in the source workspace.
#
# NOT carried, deliberately: the legacy ``open-questions.md`` ledger and the
# generated ``open-asks.yaml``. A run's open asks are a filter of its own
# decisions.yaml rows (`summary._open_asks`), which travel with the run. A
# carried ledger is how a never-migrated spark-facilitator ledger reached the
# `spark` workspace's review page (operator decision 2026-10-07: "when we
# created the new system we should not have carried forward any legacy
# models"). `test_run_cloner` guards both names.
_OPP_LEVEL_FILES = frozenset({"opp.yaml", "idea.md", "pdd.md", "inputs"})


class _Copier:
    def __init__(self, drive: DriveClient, record):
        self.drive = drive
        self.record = record
        self.copied = 0
        # source id -> copy id, for every file and folder copied. The copied
        # run_state still names the SOURCE's files (it is copied verbatim), so
        # this map is what points the clone at its own copies afterwards.
        self.ids: dict[str, str] = {}
        self.file_ids: dict[str, str] = {}
        # Every copy that may name source ids — text files and Google Docs —
        # as (copy id, name, mime type), in copy order (see
        # _point_state_at_copies).
        self.text_copies: list[tuple[str, str, str]] = []

    def file(self, f: DriveFile, dest_folder_id: str) -> None:
        new_id = self.drive.copy_file(f.id, dest_folder_id, f.name)
        self.ids[f.id] = new_id
        self.file_ids[f.id] = new_id
        if _rewrite_kind(f.name, f.mime_type) is not None:
            self.text_copies.append((new_id, f.name, f.mime_type))
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
        skip_if: Callable[[str], bool] | None = None,
    ) -> None:
        for child in self.drive.list_files(source_folder_id):
            if child.name in skip or (only is not None and child.name not in only):
                continue
            if skip_if is not None and skip_if(child.name):
                continue
            if child.mime_type == _FOLDER_MIME:
                sub = self.drive.create_folder(dest_folder_id, child.name)
                self.ids[child.id] = sub
                self.tree(child.id, sub, skip_if=skip_if)
            else:
                self.file(child, dest_folder_id)


# How long a `copying` record may go without progress before a new POST may
# replace it: the copy writes progress every _PROGRESS_EVERY files (~2.4 s per
# file live), so 10 minutes of silence means its worker died.
_STALE_AFTER = dt.timedelta(minutes=10)

# Never cloned, at any depth: ACE's email records. They are internal (drafts,
# cc lines, thread ids), and ACE routes inbound mail by the thread ids in a
# run's comms-log — a clone carrying them would steal the source's threads.
_RUN_SKIP = frozenset({"comms-log"})


def _skip_run_child(name: str) -> bool:
    return name in _RUN_SKIP or name.endswith("_comms-log")


def start_clone(
    *, drive: DriveClient, source, target, opp_slug: str, run_id: str, owner
) -> tuple[object, Callable[[], CloneResult]]:
    """Validate, create the ``RunClone`` record, and return ``(record, copy)``.

    Fast: only listings. ``copy()`` does the Drive copy (one call per file —
    ~14 min for a 347-file run) and is what the API runs on a background
    thread. Raises ``CloneError`` for caller-facing validation failures."""
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

    dst_opp = _child(drive.list_files(target.drive_root_folder_id), opp_slug, folder=True)
    dst_runs = None
    if dst_opp is not None:
        dst_runs = _child(drive.list_files(dst_opp.id), "runs", folder=True)
        existing = (
            _child(drive.list_files(dst_runs.id), run_id, folder=True) if dst_runs else None
        )
        if existing is not None:
            last = (
                RunClone.objects.filter(target_workspace=target, opp_slug=opp_slug, run_id=run_id)
                .order_by("-created_at")
                .first()
            )
            now = dt.datetime.now(dt.UTC)
            replaceable = last is not None and (
                last.status == "error"
                or (last.status == "copying" and now - last.updated_at > _STALE_AFTER)
            )
            if not replaceable:
                raise CloneError(
                    "already-cloned",
                    f"{target.slug} already has {opp_slug}/runs/{run_id}; "
                    "trash it there to re-clone",
                )
            # A clone that failed, or whose worker died mid-copy, left a partial
            # run. Replace it rather than making someone trash it by hand.
            drive.trash_folder(existing.id)
            if last.status == "copying":
                last.status = "error"
                last.error = "abandoned: no progress; replaced by a new clone"
                last.save(update_fields=["status", "error", "updated_at"])

    record = RunClone.objects.create(
        source_workspace=source, target_workspace=target, opp_slug=opp_slug,
        run_id=run_id, created_by=owner,
    )

    def copy() -> CloneResult:
        return _copy(drive, record, source, target, opp_slug, run_id, owner,
                     src_opp, src_run, dst_opp, dst_runs)

    return record, copy


def _copy(drive, record, source, target, opp_slug, run_id, owner,
          src_opp, src_run, dst_opp, dst_runs) -> CloneResult:
    from apps.opps import tenancy as tenancy_mod
    from apps.opps.models import OppWorkspace

    copier = _Copier(drive, record)
    try:
        if dst_opp is None:
            dst_opp_id = drive.create_folder(target.drive_root_folder_id, opp_slug)
            # Opp-level files, once — an ALLOWLIST, not "everything above
            # runs/". The opp root is where ACE keeps its own working notes
            # (eval-calibration/, the inbox-triage comms-log, parked email
            # drafts), and a clone exists to be shown
            # to outside reviewers. spark-facilitator's root held all of them,
            # including an unsent draft addressed to the reviewer. Other runs
            # are not copied either — a clone is one run.
            copier.tree(src_opp.id, dst_opp_id, only=_OPP_LEVEL_FILES)
        else:
            dst_opp_id = dst_opp.id
        existing_runs = dst_runs or _child(drive.list_files(dst_opp_id), "runs", folder=True)
        dst_runs_id = existing_runs.id if existing_runs else drive.create_folder(dst_opp_id, "runs")
        dst_run_id = drive.create_folder(dst_runs_id, run_id)
        # Only the RUN's copies are rewritten: opp-level files are shared by
        # every later clone of this opp into the target, and carry no run file ids.
        run_text_from = len(copier.text_copies)

        run_children = drive.list_files(src_run.id)
        state = _child(run_children, _RUN_STATE, folder=False)
        if state is not None:
            copier.file(state, dst_run_id)
        copier.tree(src_run.id, dst_run_id, skip=frozenset({_RUN_STATE}),
                    skip_if=_skip_run_child)
        copier.ids[src_run.id] = dst_run_id
        copier.ids.setdefault(src_opp.id, dst_opp_id)
        _carry_link_sharing(drive, copier.file_ids)
        _point_state_at_copies(drive, copier.text_copies[run_text_from:], copier.ids)
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


def clone_run(
    *, drive: DriveClient, source, target, opp_slug: str, run_id: str, owner
) -> CloneResult:
    """Copy ``source``'s ``opp_slug/runs/run_id`` into ``target``, blocking.
    The API runs the same two halves with the copy on a thread."""
    _, copy = start_clone(drive=drive, source=source, target=target, opp_slug=opp_slug,
                          run_id=run_id, owner=owner)
    return copy()


# The copied files rewritten to name the clone's own copies. Every YAML file in
# the run — run_state.yaml and decisions.yaml, and the indexes that list files
# by id (each previews/<output>/_previews.yaml, Phase 6's capture manifest) —
# and, since ace#2607, every other text file (the markdown companions:
# training-onboarding-email.md, the guides' .source.md, phase summaries) and
# every Google Doc, whose hyperlinks named the source run's files too.
_YAML_SUFFIXES = (".yaml", ".yml")
_TEXT_SUFFIXES = _YAML_SUFFIXES + (
    ".md", ".markdown", ".txt", ".json", ".csv", ".html", ".xml",
)
_GOOGLE_NATIVE = "application/vnd.google-apps."
_GOOGLE_DOC = "application/vnd.google-apps.document"


def _rewrite_kind(name: str, mime_type: str) -> str | None:
    """How a copy is pointed at the clone's files: ``"text"`` (read, rewrite,
    write back as text), ``"doc"`` (retarget a Google Doc's links and visible
    ids in place via the Docs API), or None (binaries and other Google types —
    slides, sheets — are left as copied).

    A Google Doc NAMED *.yaml is ACE's YAML stored as a Doc (run_state,
    decisions, verdicts): it keeps the text path it always had. Any other Doc
    is formatted prose and is never written back as text — that would flatten it."""
    mime = mime_type or ""
    if name.endswith(_YAML_SUFFIXES):
        return "text"
    if mime == _GOOGLE_DOC:
        return "doc"
    if mime.startswith(_GOOGLE_NATIVE):
        return None
    if name.endswith(_TEXT_SUFFIXES) or mime.startswith("text/"):
        return "text"
    if any(t in mime for t in ("json", "yaml", "xml")):
        return "text"
    return None


def _carry_link_sharing(drive: DriveClient, file_ids: dict[str, str]) -> int:
    """Give each copy its original's anyone-with-link role. ``files.copy``
    does not carry permissions, so without this every document the source
    run shared (the PDD, the training guides, the screenshots the page
    embeds) is a "You need access" wall on the clone. Measured on the first
    Spark clone: 26 of its files had link sharing to carry."""
    roles = drive.anyone_roles(list(file_ids))
    carried = 0
    for src_id, role in roles.items():
        if role:
            drive.set_anyone_role(file_ids[src_id], role)
            carried += 1
    return carried


def _point_state_at_copies(
    drive: DriveClient, text_copies: list[tuple[str, str, str]], ids: dict[str, str]
) -> int:
    """Replace every source Drive id in the copied text files and Docs with its copy.

    The run is copied verbatim, so its YAML names the SOURCE run's files: on
    the first Spark clone all eight documents on the reviewer-facing summary
    (PDD, work order, build memo, five training docs) opened the source
    workspace's Docs — reviewers would have read and commented on another
    workspace's files. 99 ids / 125 occurrences in that run_state. The preview
    indexes had the same fault and a worse symptom (ace-web#851): the viewer
    drops a frame whose id is outside the run's own tree, so every
    screenshot-backed output on the clone showed nothing. Ids of files the
    clone deliberately leaves behind (comms-logs) stay pointing at the source,
    which is Dimagi-only.

    ace#2607: YAML was not the only carrier. The markdown companions and the
    Google Docs rendered from them linked the source run too — on the second
    Spark clone the partner-facing onboarding email opened the source FAQ,
    deck and quick reference, and the FLW guide Doc hid 23 source screenshot
    links behind link text (a text export shows no id). Plain text files are
    rewritten as text and keep their own media type; a Doc is retargeted in
    place (links + visible ids), never rewritten as text."""
    pattern = id_pattern(ids)
    if pattern is None or not text_copies:
        return 0
    replaced = 0
    for file_id, name, mime_type in text_copies:
        if _rewrite_kind(name, mime_type) == "doc":
            replaced += drive.retarget_doc_ids(file_id, ids)
            continue
        content = drive.get_content(file_id, mime_type)
        if content.encoding == "base64":
            continue  # not text after all
        text = content.content
        new, n = pattern.subn(lambda m: ids[m.group(1)], text)
        if n:
            # A plain file keeps its own media type; a Google Doc holding YAML
            # is updated from text/yaml, as it always was.
            write_as = "text/yaml" if mime_type.startswith(_GOOGLE_NATIVE) else mime_type
            fallback = "text/yaml" if name.endswith(_YAML_SUFFIXES) else "text/plain"
            drive.update_file(file_id, new, write_as or fallback)
            replaced += n
    return replaced
