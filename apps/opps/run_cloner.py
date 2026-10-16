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

Speed and failure (ace-web#864): file copies run on a bounded pool
(``_COPY_WORKERS``); an ambiguous 5xx on one copy is LOOKED at before it is
retried (``_Copier._copy_one``); and a re-POST over a failed clone RESUMES into
the kept target, adopting what already landed (``RunClone.id_map``).

Spec: docs/specs/2026-09-28-clone-and-release-design.md § C.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
    # Files in the clone, adopted ones included; ``files_resumed`` of them came
    # from the earlier attempt this one resumed.
    files_copied: int
    files_resumed: int = 0


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


# Per-file copies run on a pool of this many workers (ace-web#864). A Drive
# files.copy is ~2.4 s of server time and nothing else, so copying serially was
# the whole cost of a clone: 850 files ≈ 34 min. Folders are still created
# serially, BEFORE the pool, so every copy has its parent; run_state.yaml is
# still copied first, on its own. Kept modest because Drive's per-user write
# quota is the next ceiling — the copy's 429 backoff (drive_client) absorbs it.
_COPY_WORKERS = 8

# A copy that fails with one of these may still have LANDED — see _copy_one.
_AMBIGUOUS_STATUS = frozenset({500, 502, 503, 504})
_COPY_ATTEMPTS = 4
_COPY_RETRY_BASE_DELAY = 2.0  # 2s, 4s, 8s, 16s + jitter
_sleep = time.sleep  # tests replace this


def _is_ambiguous_failure(exc: BaseException) -> bool:
    """True when a copy failed in a way that does not say whether it applied:
    a Drive 5xx (``internalError`` / ``backendError``) or a connection that
    dropped before the answer. A 403/404/400 — or a bug — is definite."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in _AMBIGUOUS_STATUS:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


@dataclass
class _Task:
    """One file to bring into the clone. ``copy_id`` is set once the clone
    holds it — adopted from an earlier attempt at plan time, or copied."""

    src: DriveFile
    dest_folder_id: str
    # The only file with this name in its source folder. A lookback after an
    # ambiguous failure matches by NAME, which is only safe when unique.
    unique_name: bool = True
    copy_id: str | None = None


class _Copier:
    """Copies trees into the clone: plan serially, copy on a pool.

    ``resume`` (a re-POST over an errored or abandoned clone, ace-web#864):
    the target folders are KEPT, and every file or folder already there is
    adopted rather than copied again — matched first by the earlier attempt's
    persisted id map, else by name + folder-ness in the destination listing
    (a worker that died before its last progress save left copies the map
    never heard of). Folders are reused the same way, never duplicated."""

    def __init__(self, drive: DriveClient, record, *, prior_ids: dict | None = None,
                 resume: bool = False):
        self.drive = drive
        self.record = record
        self.resume = resume
        self.prior_ids: dict[str, str] = dict(prior_ids or {})
        # Files the clone holds: copied by this attempt + adopted (``resumed``).
        self.copied = 0
        self.resumed = 0
        # source id -> copy id, for every file and folder in the clone. The
        # copied run_state still names the SOURCE's files (it is copied
        # verbatim), so this map is what points the clone at its own copies
        # afterwards — over resumed AND new files alike.
        self.ids: dict[str, str] = {}
        self.file_ids: dict[str, str] = {}
        # Every copy that may name source ids — text files and Google Docs —
        # as (copy id, name, mime type), in traversal order (see
        # _point_state_at_copies).
        self.text_copies: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()
        # Destination ids already standing for some source file, so a name
        # match never hands one copy to two sources.
        self._claimed: set[str] = set()
        self._since_save = 0

    # -- public ------------------------------------------------------------

    def files(self, files: list[DriveFile], dest_folder_id: str, *, existing: bool) -> None:
        dest_children = self._dest_listing(dest_folder_id, existing)
        tasks: list[_Task] = []
        for f in files:
            self._plan_file(f, dest_folder_id, dest_children, tasks, unique=True)
        self._execute(tasks)

    def tree(
        self,
        source_folder_id: str,
        dest_folder_id: str,
        *,
        existing: bool = False,
        skip: frozenset[str] = frozenset(),
        only: frozenset[str] | None = None,
        skip_if: Callable[[str], bool] | None = None,
    ) -> None:
        tasks: list[_Task] = []
        self._plan(source_folder_id, dest_folder_id, existing, tasks,
                   skip=skip, only=only, skip_if=skip_if)
        self._execute(tasks)

    def save_progress(self, *extra_fields: str) -> None:
        """Persist progress and the id map. Coordinating thread only: Django
        DB connections are per-thread, and the pool's workers never touch the DB."""
        self.record.files_copied = self.copied
        self.record.files_resumed = self.resumed
        self.record.id_map = dict(self.ids)
        self.record.save(update_fields=[
            *extra_fields, "files_copied", "files_resumed", "id_map", "updated_at",
        ])
        self._since_save = 0

    # -- planning (serial: listings + folder creation) ----------------------

    def _dest_listing(self, dest_folder_id: str, existing: bool) -> list[DriveFile]:
        # A folder this attempt just created is empty; only a kept one is listed.
        return self.drive.list_files(dest_folder_id) if (self.resume and existing) else []

    def _match(self, f: DriveFile, dest_children: list[DriveFile]) -> DriveFile | None:
        if not dest_children:
            return None
        prior = self.prior_ids.get(f.id)
        for c in dest_children:
            if c.id == prior and c.id not in self._claimed:
                return c
        is_folder = f.mime_type == _FOLDER_MIME
        for c in dest_children:
            if (c.name == f.name and (c.mime_type == _FOLDER_MIME) == is_folder
                    and c.id not in self._claimed):
                return c
        return None

    def _plan(self, source_folder_id, dest_folder_id, existing, tasks, *,
              skip=frozenset(), only=None, skip_if=None) -> None:
        dest_children = self._dest_listing(dest_folder_id, existing)
        children = [
            c for c in self.drive.list_files(source_folder_id)
            if c.name not in skip
            and (only is None or c.name in only)
            and (skip_if is None or not skip_if(c.name))
        ]
        names = Counter(c.name for c in children if c.mime_type != _FOLDER_MIME)
        for child in children:
            if child.mime_type == _FOLDER_MIME:
                match = self._match(child, dest_children)
                if match is not None:
                    self._claimed.add(match.id)
                    sub, sub_existing = match.id, True
                else:
                    sub, sub_existing = self.drive.create_folder(dest_folder_id, child.name), False
                self.ids[child.id] = sub
                self._plan(child.id, sub, sub_existing, tasks, skip_if=skip_if)
            else:
                self._plan_file(child, dest_folder_id, dest_children, tasks,
                                unique=names[child.name] == 1)

    def _plan_file(self, f, dest_folder_id, dest_children, tasks, *, unique: bool) -> None:
        task = _Task(f, dest_folder_id, unique_name=unique)
        match = self._match(f, dest_children)
        if match is not None:
            self._claimed.add(match.id)
            self._record(task, match.id, resumed=True)
        tasks.append(task)

    # -- copying (the pool) -------------------------------------------------

    def _execute(self, tasks: list[_Task]) -> None:
        pending = [t for t in tasks if t.copy_id is None]
        first_exc: BaseException | None = None
        if pending:
            workers = max(1, min(_COPY_WORKERS, len(pending)))
            queue = iter(pending)
            in_flight: dict = {}
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clone-copy") as pool:

                def submit_next() -> None:
                    task = next(queue, None)
                    if task is not None:
                        in_flight[pool.submit(self._copy_one, task)] = task

                # At most `workers` copies are ever handed out, so a failure
                # stops the clone promptly: nothing new starts after it, and
                # the copies already in flight finish and are recorded, so a
                # resume skips them.
                for _ in range(workers):
                    submit_next()
                while in_flight:
                    done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                    for fut in done:
                        task = in_flight.pop(fut)
                        exc = fut.exception()
                        if exc is not None:
                            first_exc = first_exc or exc
                            continue
                        self._record(task, fut.result())
                        if self._since_save >= _PROGRESS_EVERY:
                            self.save_progress()
                        if first_exc is None:
                            submit_next()
        # Text copies in traversal order, whatever order the pool finished in.
        for t in tasks:
            if t.copy_id is not None and _rewrite_kind(t.src.name, t.src.mime_type) is not None:
                self.text_copies.append((t.copy_id, t.src.name, t.src.mime_type))
        if first_exc is not None:
            raise first_exc

    def _record(self, task: _Task, copy_id: str, *, resumed: bool = False) -> None:
        with self._lock:
            task.copy_id = copy_id
            self.ids[task.src.id] = copy_id
            self.file_ids[task.src.id] = copy_id
            self.copied += 1
            if resumed:
                self.resumed += 1
            self._since_save += 1

    def _copy_one(self, task: _Task) -> str:
        """Copy one file (on a pool worker): look, then retry, on an ambiguous failure.

        A 5xx from ``files.copy`` does not mean the copy failed — the server
        may have applied it and lost the answer — which is exactly why
        ``drive_client``'s write retry stays 429-only: blindly retrying a 5xx
        can leave a DUPLICATE copy. So the 5xx is handled here, where the
        destination is known: wait (bounded exponential backoff), list the
        destination folder, and if a child with this name is there, the copy
        landed — adopt its id. Only when it is absent is the copy retried.
        Before this, one Drive 500 at file 851 (~25 min in) failed a whole
        clone (ace-web#864).

        The lookback matches by name, so it runs only when the name is unique
        in its source folder; a duplicate-named file fails definitively and
        the next POST resumes it."""
        f, dest = task.src, task.dest_folder_id
        for attempt in range(1, _COPY_ATTEMPTS + 1):
            try:
                new_id = self.drive.copy_file(f.id, dest, f.name)
            except Exception as exc:
                if not (_is_ambiguous_failure(exc) and task.unique_name):
                    raise
                delay = _COPY_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                delay += random.uniform(0, delay * 0.25)
                log.warning("clone copy %s (%s) failed ambiguously (attempt %d/%d): %s; "
                            "looking in %s after %.1fs", f.name, f.id, attempt,
                            _COPY_ATTEMPTS, exc, dest, delay)
                _sleep(delay)
                landed = self._landed(f, dest)
                if landed is not None:
                    log.warning("clone copy %s landed despite the error; adopting %s",
                                f.name, landed)
                    return landed
                if attempt == _COPY_ATTEMPTS:
                    raise
                continue
            with self._lock:
                self._claimed.add(new_id)
            return new_id
        raise RuntimeError("unreachable")  # pragma: no cover

    def _landed(self, f: DriveFile, dest_folder_id: str) -> str | None:
        for c in self.drive.list_files(dest_folder_id):
            if c.name != f.name or c.mime_type == _FOLDER_MIME:
                continue
            with self._lock:
                if c.id in self._claimed:
                    continue
                self._claimed.add(c.id)
                return c.id
        return None


# How long a `copying` record may go without progress before a new POST may
# replace it: the copy writes progress every _PROGRESS_EVERY files (seconds
# apart, even with an ambiguous-failure backoff), so 10 minutes of silence
# means its worker died.
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

    Fast: only listings. ``copy()`` does the Drive copy (on a pool of
    ``_COPY_WORKERS``) and is what the API runs on a background thread.
    Raises ``CloneError`` for caller-facing validation failures.

    Over an ``error`` (or stale ``copying``) record for the same run, the new
    clone RESUMES: the partial target is kept and what already landed is
    adopted, not copied again (ace-web#864 — a re-POST used to trash it and
    restart from file 0)."""
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

    last = (
        RunClone.objects.filter(target_workspace=target, opp_slug=opp_slug, run_id=run_id)
        .order_by("-created_at", "-pk")
        .first()
    )
    now = dt.datetime.now(dt.UTC)
    resume_from = last if last is not None and (
        last.status == "error"
        or (last.status == "copying" and now - last.updated_at > _STALE_AFTER)
    ) else None

    dst_opp = _child(drive.list_files(target.drive_root_folder_id), opp_slug, folder=True)
    dst_runs = None
    existing = None
    if dst_opp is not None:
        dst_runs = _child(drive.list_files(dst_opp.id), "runs", folder=True)
        existing = (
            _child(drive.list_files(dst_runs.id), run_id, folder=True) if dst_runs else None
        )
    if existing is not None and resume_from is None:
        raise CloneError(
            "already-cloned",
            f"{target.slug} already has {opp_slug}/runs/{run_id}; "
            "trash it there to re-clone",
        )
    if resume_from is not None and resume_from.status == "copying":
        resume_from.status = "error"
        resume_from.error = "abandoned: no progress; resumed by a new clone"
        resume_from.save(update_fields=["status", "error", "updated_at"])

    prior_ids = dict(resume_from.id_map or {}) if resume_from is not None else {}
    record = RunClone.objects.create(
        source_workspace=source, target_workspace=target, opp_slug=opp_slug,
        run_id=run_id, created_by=owner,
        # Seeded, so an attempt that dies before its first save loses nothing.
        id_map=prior_ids,
    )

    def copy() -> CloneResult:
        return _copy(drive, record, source, target, opp_slug, run_id, owner,
                     src_opp, src_run, dst_opp, dst_runs,
                     existing_run_id=existing.id if existing is not None else None,
                     resume=resume_from is not None, prior_ids=prior_ids)

    return record, copy


def _copy(drive, record, source, target, opp_slug, run_id, owner,
          src_opp, src_run, dst_opp, dst_runs, *, existing_run_id=None,
          resume=False, prior_ids=None) -> CloneResult:
    from apps.opps import tenancy as tenancy_mod
    from apps.opps.models import OppWorkspace

    copier = _Copier(drive, record, prior_ids=prior_ids, resume=resume)
    try:
        # Opp-level files — an ALLOWLIST, not "everything above runs/". The
        # opp root is where ACE keeps its own working notes (eval-calibration/,
        # the inbox-triage comms-log, parked email drafts), and a clone exists
        # to be shown to outside reviewers. spark-facilitator's root held all
        # of them, including an unsent draft addressed to the reviewer. Other
        # runs are not copied either — a clone is one run. Copied when the opp
        # is new to the target; a RESUMED clone walks them again (adopting what
        # is there), since the attempt it resumes may have died among them.
        if dst_opp is None:
            dst_opp_id = drive.create_folder(target.drive_root_folder_id, opp_slug)
            copier.tree(src_opp.id, dst_opp_id, only=_OPP_LEVEL_FILES)
        else:
            dst_opp_id = dst_opp.id
            if resume:
                copier.tree(src_opp.id, dst_opp_id, existing=True, only=_OPP_LEVEL_FILES)
        existing_runs = dst_runs or _child(drive.list_files(dst_opp_id), "runs", folder=True)
        dst_runs_id = existing_runs.id if existing_runs else drive.create_folder(dst_opp_id, "runs")
        run_existing = existing_run_id is not None
        dst_run_id = existing_run_id or drive.create_folder(dst_runs_id, run_id)
        # Only the RUN's copies are rewritten: opp-level files are shared by
        # every later clone of this opp into the target, and carry no run file ids.
        run_text_from = len(copier.text_copies)

        run_children = drive.list_files(src_run.id)
        state = _child(run_children, _RUN_STATE, folder=False)
        if state is not None:
            # First, alone, before the pool — see the module docstring.
            copier.files([state], dst_run_id, existing=run_existing)
        copier.tree(src_run.id, dst_run_id, existing=run_existing,
                    skip=frozenset({_RUN_STATE}), skip_if=_skip_run_child)
        copier.ids[src_run.id] = dst_run_id
        copier.ids.setdefault(src_opp.id, dst_opp_id)
        # Both passes run over the FULL map — resumed and new copies alike —
        # so a resumed clone's links and ids are as right as a fresh one's.
        _carry_link_sharing(drive, copier.file_ids)
        _point_state_at_copies(drive, copier.text_copies[run_text_from:], copier.ids)
    except Exception as exc:
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"[:2000]
        copier.save_progress("status", "error")
        log.warning(
            "clone %s/%s/%s -> %s failed after %d files (%d resumed): %s",
            source.slug, opp_slug, run_id, target.slug, copier.copied, copier.resumed, exc,
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
    copier.save_progress("status")
    return CloneResult(
        clone_id=record.pk, opp_slug=opp_slug, run_id=run_id,
        target_run_folder_id=dst_run_id, files_copied=copier.copied,
        files_resumed=copier.resumed,
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
