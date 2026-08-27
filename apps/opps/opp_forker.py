"""Fork a run within an opp.

Per the ACE plugin's canonical fork contract
(``agents/orchestrator-reference.md`` § Fork Points, ace 0.13.151),
forking does NOT create a new opp. It mints a new run-id under the
**same** opp folder and seeds it from a prior run's outputs.

Per-opp resources stay untouched — ``opp.yaml``, ``inputs/``,
``eval-calibration/``, ``open-questions.md``, ``connect-state.yaml``,
``current/``. They live above ``runs/`` and every run shares them.

Per-run resources get a fresh home under ``runs/<new-run-id>/``. They
are written in a deliberate ORDER — ``run_state.yaml`` first, then the
bulk copy — because ``run_state.yaml`` is what makes the folder a run
and everything else is optional-but-expensive. A fork interrupted
partway (Drive stall, ECS task replacement mid-copy) then leaves a
resumable-but-incomplete run rather than an unrunnable pile of copied
artifacts. See ace-web#734.

* Phase folders ``<N>-<phase>/`` from the source run, copied only when
  ``N < fork_ordinal``. The plugin lays out per-phase artifacts in
  numbered folders so the folder name carries the phase ordinal — no
  manifest introspection needed.
* ``decisions.yaml`` carried over from the source run, with rows for
  phases >= the fork ordinal trimmed.
* ``idea.md`` (only when the source had a ``--idea`` seed) and
  ``inputs-manifest.yaml`` carried over verbatim — they describe the
  source pack the kept phases worked from.
* A fresh ``run_state.yaml`` synthesized from scratch per the State
  Schema in orchestrator-reference: ``opportunity``, ``run_id``,
  ``mode``, ``created``, ``initiated_by``, ``last_actor`` +
  ``last_actor_at``, and a ``phases`` map seeded ``done`` for kept
  phases and ``pending`` for everything from ``fork_at_phase`` onward.
  Written FIRST, ahead of every copy — it depends on nothing the copy
  produces.

Drive cost: O(N) calls where N is the number of files we end up
copying — proportional to the *kept* phase count, not the source's
total. For a fork at phase 2 of a fully-completed 8-phase opp, we
copy roughly 1/8 of the source's run artifacts.
"""
from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from apps.opps.decisions_edit import (
    apply_edits_to_decisions_data,
    upgrade_decisions_v1_to_v2,
)
from apps.opps.drive_client import DriveClient, DriveFile
from apps.sessions.models import Message, Session

# Fork modes — both copy upstream artifacts; they differ only in how
# decisions.yaml rows from upstream phases are filtered.
#
# * keep-overrides-only: only rows where status == "overridden" carry
#   forward (and only from phases strictly before the fork point).
#   AI defaults from upstream are dropped so downstream phases re-derive.
# * keep-all: every row upstream of the fork point carries forward
#   regardless of status — both AI defaults and overrides.
#
# In both modes, rows at or downstream of the fork-phase are dropped.
FORK_MODES = ("keep-overrides-only", "keep-all")
DEFAULT_FORK_MODE = "keep-all"

_FOLDER_MIME = "application/vnd.google-apps.folder"

# Phase folders the plugin writes look like ``1-design`` / ``2-commcare``.
# The leading integer is the phase ordinal, which lets us decide what to
# carry forward without looking up anything skill-side. The trailing
# ``[a-z]`` is what keeps us from misclassifying run-id folders like
# ``20260501-1200`` (numeric timestamp) as phase folders.
_PHASE_FOLDER_RE = re.compile(r"^(\d+)-[a-z]")

# Files inside the source run folder that get carried over verbatim
# (alongside the kept ``<N>-phase/`` subtrees). decisions.yaml gets a
# post-copy trim; everything else here is just a straight copy.
_RUN_ROOT_FILES_TO_COPY = (
    "decisions.yaml",
    "decisions.yml",
    "idea.md",
    "inputs-manifest.yaml",
)


class ForkOppError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ForkOppResult:
    opp_slug: str            # unchanged — fork stays within the same opp
    new_run_id: str          # YYYYMMDD-HHMM, the new run folder name
    new_run_folder_id: str   # Drive folder id of the new run
    working_session: Session | None  # None when create_session=False (seeded-run drives its own)


ProgressCb = Callable[[dict], None]


def fork_opp(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    owner,
    source_slug: str,
    fork_at_phase: str | None = None,
    fork_at_skill: str | None = None,
    source_run_id: str | None = None,
    workspace=None,
    progress_cb: ProgressCb | None = None,
    edits: list[dict[str, str]] | None = None,
    mode: str = DEFAULT_FORK_MODE,
    feedback: str | None = None,
    now: _dt.datetime | None = None,
    run_phases: list[int] | None = None,
    create_session: bool = True,
) -> ForkOppResult:
    """Fork the source opp's named run (or its latest if ``source_run_id``
    is None) into a new run under the same opp.

    ``mode`` controls how upstream decisions carry forward:
    ``keep-overrides-only`` keeps only ``status: overridden`` rows from
    phases strictly before the fork point; ``keep-all`` keeps every
    upstream row regardless of status. See ``FORK_MODES`` at module top.

    ``run_phases`` (seeded-run path, ace#672): when given, the synthesized
    ``run_state.yaml`` is written in the plugin's **phase-level contract shape**
    (``phases.<phase>.{status, ...}``) and shaped for a structural resume —
    phases below the fork point ``done``/``verdict: seeded``, the listed
    ordinals ``pending``, and every other phase from the fork point onward
    ``skipped`` — plus a ``seeded_from`` root key. When ``None`` (the plain
    fork-run endpoint) the legacy per-skill phases map is written unchanged.

    ``create_session=False`` skips the fork's working-session creation (the
    seeded-run action drives its own headless session); ``working_session`` is
    ``None`` in that case.

    Raises ``ForkOppError`` for caller-friendly validation failures
    (source not found, no runs to fork from, run-id collision, unknown
    mode). Drive failures during the copy bubble up, after a final
    ``status: error`` progress payload carrying ``new_run_id``; partial
    state may be left behind (the run folder exists, carries a valid
    ``run_state.yaml``, and is missing some artifacts) and the operator
    can either resume it with ``/ace:run <opp>/<run-id>`` or delete it
    via the existing run-trash flow.

    **This call is BLOCKING and can run for minutes** — one Drive
    ``copy_file`` per artifact at ~150 ms each. Callers that can't hold
    the connection should poll ``GET .../fork/status``, which reports
    ``new_run_id`` from the moment the run folder is minted.
    """
    if mode not in FORK_MODES:
        raise ForkOppError(
            "invalid-mode",
            f"mode {mode!r} is not valid; expected one of {FORK_MODES}",
        )

    from apps.opps.skills import resolve_fork_point

    if (fork_at_phase is None) == (fork_at_skill is None):
        raise ForkOppError(
            "invalid-fork-point",
            "provide exactly one of fork_at_phase / fork_at_skill",
        )

    try:
        point = resolve_fork_point(phase=fork_at_phase, skill=fork_at_skill)
    except KeyError as exc:
        # Fail fast rather than degenerate to "copy everything." A fork
        # against an unknown point silently producing a no-op trim (i.e.
        # cloning the source run wholesale) is the bug the per-run fork
        # contract exists to prevent — the next /ace:run would see every
        # phase already done. The most likely cause is ACE_PLUGIN_PATH
        # pointing at a missing/stale plugin checkout.
        kind = "phase" if fork_at_phase else "skill"
        raise ForkOppError(
            f"unknown-{kind}",
            f"{kind} {exc.args[0]!r} is not in the skill registry — "
            "check ACE_PLUGIN_PATH",
        ) from exc

    fork_ordinal = point.phase_ordinal
    # Everything downstream reports the fork point by phase name; a skill
    # fork resolves to its owning phase, so run_state / decisions trimming
    # is identical either way.
    fork_at_phase = point.phase

    source_folder = _find_child_folder(
        drive.list_files(ace_root_folder_id), source_slug
    )
    if source_folder is None:
        raise ForkOppError(
            "source-not-found", f"no opp folder named {source_slug!r}"
        )

    runs_folder = _find_child_folder(
        drive.list_files(source_folder.id), "runs"
    )
    if runs_folder is None:
        raise ForkOppError(
            "no-runs",
            f"opp {source_slug!r} has no runs/ subfolder to fork from",
        )

    run_children = drive.list_files(runs_folder.id)
    if source_run_id is None:
        source_run = _latest_run(run_children)
    else:
        source_run = _find_child_folder(run_children, source_run_id)
        if source_run is None:
            raise ForkOppError(
                "source-run-not-found",
                f"opp {source_slug!r} has no run named {source_run_id!r}",
            )
    if source_run is None:
        raise ForkOppError(
            "no-runs", f"opp {source_slug!r} has no runs to fork from"
        )

    now_utc = now or _dt.datetime.now(_dt.UTC)
    new_run_id = _mint_run_id(now_utc, run_children)

    progress = _Progress(cb=progress_cb, opp_slug=source_slug)

    # Pre-walk to count files we'll actually copy. Cheaper than the
    # copy itself (one list_files per kept folder vs. ~150 ms per
    # copy_file), so the UX win — accurate "X of Y" — is worth it.
    progress.emit("counting")
    progress.total = _count_files_to_copy(drive, source_run.id, point=point)

    new_run_folder_id = drive.create_folder(runs_folder.id, new_run_id)
    # From here on every progress payload carries the new run-id. The POST
    # blocks for the whole copy (minutes on a large run), so this poll is
    # the only channel a caller has to learn what was created before the
    # response lands — and a caller who can't learn it retries the POST
    # and produces a SECOND partial fork (ace-web#734).
    progress.new_run_id = new_run_id

    try:
        # run_state.yaml FIRST, before the bulk copy. It is small, and it
        # is the file that makes the folder a run: ACE's resume path
        # derives execution order from `run_state.yaml.phases.*.status`,
        # so a folder without it cannot be resumed at all. Written last
        # (as it was until ace-web#734), any stall in the copy left an
        # expensive pile of copied artifacts that was not a run and had
        # to be hand-repaired. Written first, the same stall leaves a
        # resumable-but-incomplete run — `/ace:run <opp>/<run-id>` picks
        # it up and re-derives what's missing.
        #
        # We intentionally DON'T copy the source run's run_state — its
        # phases map and timestamps belong to the prior run. Generating
        # fresh keeps the new run's state honest about done vs. pending,
        # and it depends on nothing the copy produces.
        new_state = _build_run_state_yaml(
            opp_slug=source_slug,
            run_id=new_run_id,
            owner_email=getattr(owner, "email", "") or "unknown",
            fork_at_phase=fork_at_phase,
            fork_ordinal=fork_ordinal,
            forked_from_run_id=source_run.name,
            now_utc=now_utc,
            run_phases=run_phases,
        )
        drive.upload_file(
            new_run_folder_id, "run_state.yaml", new_state, "text/yaml",
        )

        progress.emit("copying", current="")
        decisions_dest_id, decisions_source_body = _copy_run_subtree(
            drive=drive,
            source_run_folder_id=source_run.id,
            dest_run_folder_id=new_run_folder_id,
            point=point,
            progress=progress,
        )

        progress.emit("finalizing")

        # Trim decisions.yaml to pre-fork rows (only if the source run had
        # one — otherwise nothing to trim).
        if decisions_dest_id is not None:
            trimmed = _rewrite_decisions_yaml(
                decisions_source_body or "",
                fork_ordinal=fork_ordinal,
                edits=edits,
                mode=mode,
            )
            drive.update_file(decisions_dest_id, trimmed, "text/yaml")
        session: Session | None = None
        if create_session:
            session = Session.create_with_owner(
                owner=owner,
                title=f"{source_slug} — new run {new_run_id} (fork @ {point.label()})",
                backend_kind="cli",
                status="active",
                source="web",
                opp_slug=source_slug,
                opp_run_id=new_run_id,
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
                    "opp_slug": source_slug,
                    "fork_at_phase": fork_at_phase,
                    "fork_at_skill": point.skill,
                    "source_run_id": source_run.name,
                    "new_run_id": new_run_id,
                },
                plaintext=(
                    f"Forked run `{new_run_id}` from `{source_run.name}` at "
                    f"{'skill' if point.is_skill_fork else 'phase'} "
                    f"`{point.label()}`. Re-run /ace:run to continue from there."
                ),
                status="complete",
            )
            if feedback:
                # Seed the operator's reason as the first USER turn, so the
                # agent picking up the fork reads the intent instead of
                # inferring it from artifacts. This restored a capability lost
                # when apps/opps/fork.py was deleted (2026-04-20), where it was
                # the whole point of the `with-feedback` mode.
                Message.objects.create(
                    session=session,
                    turn_index=1,
                    role="user",
                    sender_user=owner,
                    content={"type": "text", "text": feedback},
                    plaintext=feedback,
                    status="complete",
                )
    except Exception as exc:
        # Report the failure AND the run folder it left behind. Staying
        # silent here is what made a slow fork indistinguishable from a
        # fork that never started; the caller needs to know there's a
        # partial run to inspect or trash, not to retry blindly.
        progress.emit("error", error=f"{type(exc).__name__}: {exc}")
        raise

    progress.emit("done")
    return ForkOppResult(
        opp_slug=source_slug,
        new_run_id=new_run_id,
        new_run_folder_id=new_run_folder_id,
        working_session=session,
    )


# ── Drive helpers ──────────────────────────────────────────────────


def _find_child_folder(files: list[DriveFile], name: str) -> DriveFile | None:
    for f in files:
        if f.name == name and f.mime_type == _FOLDER_MIME:
            return f
    return None


def _latest_run(run_children: list[DriveFile]) -> DriveFile | None:
    """Pick the lex-newest run subfolder. Run-ids follow ``YYYYMMDD-HHMM``
    so lex-sort matches chronological order."""
    runs = [f for f in run_children if f.mime_type == _FOLDER_MIME]
    if not runs:
        return None
    runs.sort(key=lambda f: f.name)
    return runs[-1]


def _mint_run_id(
    now_utc: _dt.datetime, existing_run_children: list[DriveFile],
) -> str:
    """Build a ``YYYYMMDD-HHMM`` run-id and bump until it's unique.

    Two forks from the same UI in the same minute would collide
    otherwise; appending a ``-N`` suffix is the simplest disambiguator
    that stays sortable.
    """
    base = now_utc.strftime("%Y%m%d-%H%M")
    existing = {f.name for f in existing_run_children}
    if base not in existing:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


# ── Pre-walk / count ───────────────────────────────────────────────


@dataclass
class _Progress:
    """Counts the copy walk and reports it in ``ForkProgress`` shape.

    Counting and reporting live on one object because they were the same
    bug: ace-web#734 shipped a walk that incremented ``copied`` and an
    ``_emit`` that published key names (``copied`` / ``total`` /
    ``current`` / ``opp_slug``) the strict ``ForkProgress`` response
    schema rejects, so nothing the walk counted ever reached a caller.
    Every payload now leaves through :meth:`emit`, which builds the
    schema's field names and nothing else.
    """

    cb: ProgressCb | None
    opp_slug: str
    total: int = 0
    copied: int = 0
    #: Set the moment the new run folder is minted. Reported on EVERY
    #: payload from then on: a caller whose blocking POST hung has no
    #: other way to learn which run was created, and a poll that says
    #: "unknown" while a fork is mid-copy invites the retry that
    #: produces a second partial fork.
    new_run_id: str | None = None

    def emit(
        self, status: str, *, current: str | None = None,
        error: str | None = None,
    ) -> None:
        if self.cb is None:
            return
        payload: dict = {
            "status": status,
            "progress": (self.copied / self.total) if self.total else 0.0,
            "files_total": self.total,
            "files_copied": self.copied,
            "current": current,
            "error": error,
            "new_slug": self.opp_slug,
            "new_run_id": self.new_run_id,
        }
        try:
            self.cb(payload)
        except Exception:  # noqa: BLE001 — reporting must never break the fork
            pass

    def tick(self, current: str) -> None:
        """Record one copied file and report it."""
        self.copied += 1
        self.emit("copying", current=current)


def _count_files_to_copy(
    drive: DriveClient, source_run_folder_id: str, *, point: ForkPoint | None,
) -> int:
    """Count files we'll actually copy from the source run folder.

    Mirrors the filter applied by ``_copy_run_subtree`` — files at the
    run root that aren't in ``_RUN_ROOT_FILES_TO_COPY`` aren't counted,
    phase folders past the fork point aren't recursed into, and on a skill
    fork the fork-point phase is counted through the SAME predicate the
    copy uses. If the two ever diverge the progress bar lies, so they are
    deliberately written against one shared helper.
    """
    n = 0
    for child in drive.list_files(source_run_folder_id):
        if child.mime_type == _FOLDER_MIME:
            if not _PHASE_FOLDER_RE.match(child.name):
                # Run-root folders other than `<N>-phase/` aren't part
                # of the canonical per-run layout; skip them rather than
                # blindly copying unknown content.
                continue
            disposition = _phase_folder_disposition(child.name, point)
            if disposition == "skip":
                continue
            n += _count_files_recursive(
                drive,
                child.id,
                keep_file=(
                    (lambda name: _keep_artifact_for_skill_fork(name, point))
                    if disposition == "partial"
                    else None
                ),
            )
        else:
            if child.name in _RUN_ROOT_FILES_TO_COPY:
                n += 1
    return n


def _count_files_recursive(
    drive: DriveClient,
    folder_id: str,
    keep_file: Callable[[str], bool] | None = None,
) -> int:
    """Count files under ``folder_id``, honouring the same ``keep_file``
    predicate ``_copy_subtree_verbatim`` applies, so counts and copies
    cannot disagree."""
    n = 0
    for child in drive.list_files(folder_id):
        if child.mime_type == _FOLDER_MIME:
            n += _count_files_recursive(drive, child.id, keep_file)
        elif keep_file is None or keep_file(child.name):
            n += 1
    return n


def _should_skip_phase_folder(folder_name: str, fork_ordinal: int | None) -> bool:
    """True iff ``folder_name`` is a phase folder for a phase at or after
    the fork point. Folders not matching ``<N>-…`` are never skipped here.

    Phase-granularity only. For skill forks the fork-point phase is copied
    PARTIALLY, which this predicate can't express — see
    :func:`_phase_folder_disposition`.
    """
    if fork_ordinal is None:
        return False
    m = _PHASE_FOLDER_RE.match(folder_name)
    if not m:
        return False
    return int(m.group(1)) >= fork_ordinal


def _phase_folder_disposition(folder_name: str, point: ForkPoint | None) -> str:
    """How to treat one ``<N>-<phase>/`` folder: keep | partial | skip.

    - ``keep``    — phase strictly before the fork point; copy verbatim.
    - ``partial`` — the fork-point phase on a SKILL fork; copy only the
      artifacts produced by skills with a lower ordinal than the fork skill.
    - ``skip``    — at/after the fork point; leave empty so it re-runs.

    A phase fork never yields ``partial``: naming a phase means re-running
    all of it.
    """
    if point is None:
        return "keep"
    m = _PHASE_FOLDER_RE.match(folder_name)
    if not m:
        return "keep"
    ordinal = int(m.group(1))
    if ordinal < point.phase_ordinal:
        return "keep"
    if ordinal > point.phase_ordinal:
        return "skip"
    return "partial" if point.is_skill_fork else "skip"


def _keep_artifact_for_skill_fork(basename: str, point: ForkPoint) -> bool:
    """True iff ``basename`` should survive a skill fork of its phase.

    Attribution comes from the artifact manifest's ``produced_by`` map, not
    from filename parsing — the 0.13.0+ convention is
    ``<skill>[_<role>].<ext>``, but real runs also contain files that don't
    follow it (e.g. ``deliver-connect-coverage.md``), and guessing a producer
    by string-splitting would silently drop them.

    Unattributed files are KEPT. Copying one needlessly costs a Drive call;
    dropping one loses an artifact the fork was meant to preserve.
    """
    # Deferred, like every other skills import here: opp_forker loads during
    # view import and the registry pulls in the heavier system reader.
    from apps.opps.skills import skill_ordinal_for_artifact

    ordinal = skill_ordinal_for_artifact(basename)
    if ordinal is None:
        return True
    assert point.skill_ordinal is not None  # guaranteed by is_skill_fork
    return ordinal < point.skill_ordinal


if TYPE_CHECKING:  # annotations only — the runtime import stays deferred
    from apps.opps.skills import ForkPoint


# ── Copy ───────────────────────────────────────────────────────────


def _copy_run_subtree(
    *,
    drive: DriveClient,
    source_run_folder_id: str,
    dest_run_folder_id: str,
    point: ForkPoint | None,
    progress: _Progress,
) -> tuple[str | None, str | None]:
    """Copy kept phase folders + carried run-root files into the new run.

    Returns ``(decisions_dest_id, decisions_source_body)`` so the caller
    can trim decisions.yaml after the copy. Either is None when the
    source run had no decisions log.
    """
    decisions_dest_id: str | None = None
    decisions_source_body: str | None = None
    for child in drive.list_files(source_run_folder_id):
        if child.mime_type == _FOLDER_MIME:
            if not _PHASE_FOLDER_RE.match(child.name):
                # Per the canonical layout, run-root subfolders are all
                # `<N>-phase/`. Anything else is unrecognized; leave it
                # in the source and don't propagate to the new run.
                continue
            disposition = _phase_folder_disposition(child.name, point)
            if disposition == "skip":
                continue
            sub_id = drive.create_folder(dest_run_folder_id, child.name)
            _copy_subtree_verbatim(
                drive=drive,
                source_folder_id=child.id,
                dest_folder_id=sub_id,
                rel_path=child.name,
                progress=progress,
                # On a skill fork the fork-point phase is kept only up to
                # the fork skill; every other kept phase copies whole.
                keep_file=(
                    (lambda name: _keep_artifact_for_skill_fork(name, point))
                    if disposition == "partial"
                    else None
                ),
            )
        else:
            if child.name not in _RUN_ROOT_FILES_TO_COPY:
                continue
            new_id = drive.copy_file(child.id, dest_run_folder_id, child.name)
            if child.name in ("decisions.yaml", "decisions.yml"):
                decisions_dest_id = new_id
                decisions_source_body = _read_text_or_empty(drive, child)
            progress.tick(child.name)
    return decisions_dest_id, decisions_source_body


def _copy_subtree_verbatim(
    *,
    drive: DriveClient,
    source_folder_id: str,
    dest_folder_id: str,
    rel_path: str,
    progress: _Progress,
    keep_file: Callable[[str], bool] | None = None,
) -> None:
    """Copy the children of a kept phase folder.

    ``keep_file`` is None for a whole-phase copy. On a skill fork it's a
    per-basename predicate that keeps only artifacts produced by skills
    before the fork point. Nested folders inherit the predicate — a phase's
    sub-folders (``screenshots/``, ``recipes/``) are still skill-owned.
    """
    for child in drive.list_files(source_folder_id):
        new_path = f"{rel_path}/{child.name}"
        if child.mime_type == _FOLDER_MIME:
            sub_id = drive.create_folder(dest_folder_id, child.name)
            _copy_subtree_verbatim(
                drive=drive,
                source_folder_id=child.id,
                dest_folder_id=sub_id,
                rel_path=new_path,
                progress=progress,
                keep_file=keep_file,
            )
        else:
            if keep_file is not None and not keep_file(child.name):
                continue
            drive.copy_file(child.id, dest_folder_id, child.name)
            progress.tick(new_path)


def _read_text_or_empty(drive: DriveClient, f: DriveFile) -> str:
    """Best-effort body read. Returns empty string on failure — the
    caller falls back to leaving the original content alone."""
    try:
        content = drive.get_content(f.id, f.mime_type)
        return getattr(content, "content", "") or ""
    except Exception:  # noqa: BLE001
        return ""


# ── State synthesis ────────────────────────────────────────────────


def _resolve_phase_ordinal(phase_name: str) -> int | None:
    """Look up a phase's ordinal from the agent registry. Returns None if
    the phase is unknown — in which case the copy degenerates to "copy
    everything" (safer than silently dropping content)."""
    # Deferred import: opp_forker is imported during view module load and
    # the skill registry pulls in the heavier system reader.
    from apps.opps.skills import all_phases

    phases = all_phases()
    try:
        return phases.index(phase_name) + 1
    except ValueError:
        return None


def _phase_block(phase: str, status: str, iso_now: str) -> dict:
    """One phase block in the plugin's **canonical run_state shape** (ace#673):
    a phase-level ``status`` (what the orchestrator's resume path reads off
    ``phases.<phase>.status``) PLUS a ``steps`` sub-map ``{skill: {status}}``
    (what ace-web's ``_extract_step_statuses`` renders as Workbench step rows).

    Done phases also carry ``verdict: seeded`` (the forked prefix is a copy of a
    prior run) and a ``completed_at`` seed timestamp so ``status: done`` doesn't
    warn for a missing one. The ``steps`` wrapper is always present so a phase
    block with a bare ``status`` key never leaks ``status`` as a fake skill into
    ``_extract_step_statuses``. Recurring skills are excluded — they aren't
    phase steps.
    """
    from apps.opps.skills import skills_in_phase

    block: dict = {"status": status}
    if status == "done":
        block["verdict"] = "seeded"
        block["completed_at"] = iso_now
    block["steps"] = {
        s.name: {"status": status}
        for s in skills_in_phase(phase)
        if not s.is_recurring
    }
    return block


def _build_phases_map(
    fork_ordinal: int | None,
    iso_now: str,
    run_phases: list[int] | None = None,
) -> dict[str, dict]:
    """Build the ``phases`` map for a forked run in the plugin's **canonical
    phase-level shape** ``phases.<phase>.{status, steps, ...}`` (ace#672/#673).

    Per phase ordinal (position in ``all_phases()``, the convention
    ``_resolve_phase_ordinal`` relies on):

    * ``< fork_ordinal`` (the copied prefix) → ``done``/``verdict: seeded``.
    * ``>= fork_ordinal``:
        - plain fork (``run_phases is None``) → ``pending`` (re-run from the
          fork point onward, the historical fork-run behavior).
        - seeded run (``run_phases`` given) → ``pending`` if the ordinal is a
          target, else ``skipped`` (the orchestrator steps over these and ends
          when no ``pending`` phase remains — the "only 3,4,6 then stop").
    * ``fork_ordinal is None`` (unknown fork phase) → all ``pending``.

    Emitting the canonical shape — phase-level ``status`` + a ``steps`` wrapper —
    is the ace#673 fix: it's what lets the plugin's resume read
    ``phases.<phase>.status`` AND ace-web's ``_extract_step_statuses`` render the
    seeded step rows. The previous per-skill map (``phases.<phase>.<skill>:
    status``) had neither a phase-level status (so the plugin's structural resume
    couldn't classify it) nor a ``steps`` wrapper.
    """
    from apps.opps.skills import all_phases

    targets = set(run_phases) if run_phases is not None else None
    phases_map: dict[str, dict] = {}
    for idx, phase in enumerate(all_phases(), start=1):
        if fork_ordinal is None:
            status = "pending"
        elif idx < fork_ordinal:
            status = "done"
        elif targets is None or idx in targets:
            status = "pending"
        else:
            status = "skipped"
        phases_map[phase] = _phase_block(phase, status, iso_now)
    return phases_map


def _build_run_state_yaml(
    *,
    opp_slug: str,
    run_id: str,
    owner_email: str,
    fork_at_phase: str,
    fork_ordinal: int | None,
    forked_from_run_id: str,
    now_utc: _dt.datetime,
    run_phases: list[int] | None = None,
) -> str:
    """Synthesize a fresh ``run_state.yaml`` per the State Schema in the
    plugin's orchestrator-reference (§ State Schema, defensive init).

    Adds ``forked_from`` (the source run id, as a STRING — see the inline
    note below) plus ``forked_from_phase`` / ``forked_at`` so lineage is
    visible without diving into Drive.

    The ``phases`` map is always built in the plugin's canonical phase-level
    shape (``phases.<phase>.{status, steps, ...}`` — see ``_build_phases_map``).
    When ``run_phases`` is given (seeded-run path, ace#672) the non-target
    phases from the fork point onward are ``skipped`` and a ``seeded_from`` root
    key is added; otherwise (plain fork-run) everything from the fork point
    onward is ``pending``.
    """
    iso_now = now_utc.isoformat()
    phases_map = _build_phases_map(fork_ordinal, iso_now, run_phases=run_phases)
    data: dict = {
        "opportunity": opp_slug,
        "run_id": run_id,
        "mode": "default",
        "created": iso_now,
        "initiated_by": owner_email,
        "last_actor": owner_email,
        "last_actor_at": iso_now,
        "current_phase": fork_at_phase,
        "phases": phases_map,
        # A top-level STRING, not a block. ``canopy_agent_runs`` reads this
        # field (``RunSummary.forked_from: str | None``) and its Drive store
        # documents the contract explicitly; a dict raises pydantic
        # ValidationError inside ``store.list_runs``, which 500s every
        # uncached ``load_opp`` for the opp — killing artifact download and,
        # once the snapshot cache expires, the whole workbench.
        # The lineage detail a dict used to carry lives in the sibling keys.
        "forked_from": forked_from_run_id,
        "forked_from_phase": fork_at_phase,
        "forked_at": iso_now,
    }
    if run_phases is not None:
        # Informational lineage for a seeded run (not read by any skill; the
        # plugin's resume drives off phases.*.status). Mirrors the plugin's
        # § Step 4b seeded_from root key.
        data["seeded_from"] = forked_from_run_id
    return yaml.safe_dump(data, sort_keys=False)


def _rewrite_decisions_yaml(
    original: str,
    *,
    fork_ordinal: int | None,
    edits: list[dict[str, str]] | None = None,
    mode: str = DEFAULT_FORK_MODE,
) -> str:
    """Trim ``decisions.yaml`` to rows from phases strictly before the fork,
    filter by ``mode``, then apply any human answer edits.

    Schema upgrade: v1 inputs are upgraded in memory to the v2 shape
    (``default`` → ``ai-default``, ``open`` → ``applied``, add ``override``
    where ``status: overridden``) before any filtering. Output is always
    serialized in v2 shape.

    Each row carries its own ``phase`` tag (agent-declared phase name).
    Rows whose phase ordinal >= ``fork_ordinal`` are dropped. Rows whose
    phase isn't recognized stay (safer than silently dropping content
    when the registry / decisions file disagree).

    Mode filter (applied after the phase trim):

    * ``keep-all``: no further filtering. Every surviving upstream row
      carries forward regardless of status.
    * ``keep-overrides-only``: only rows where ``status == "overridden"``
      survive. AI defaults from upstream are dropped so downstream
      phases re-derive them.

    If ``edits`` is provided, edits are applied **before** the phase
    trim so the edited rows flip to ``status: overridden`` and survive
    the trim — user-supplied edits are authoritative human intent and
    must survive regardless of which phase they target.

    Edits whose ``row_id`` doesn't match any row in the source are
    silently ignored — the forker can't synthesize a new decision row
    out of thin air; the source must already contain it.
    """
    if fork_ordinal is None and not edits and mode == DEFAULT_FORK_MODE:
        # Nothing to do: no trim, no edits, default mode is keep-all.
        # But we still want to upgrade v1 → v2 if needed for consistency.
        # Only short-circuit when input is empty or unparseable; otherwise
        # fall through to the upgrade + reserialize.
        if not original.strip():
            return original

    try:
        data = yaml.safe_load(original) or {}
        if not isinstance(data, dict):
            return original
    except yaml.YAMLError:
        return original

    # Upgrade v1 → v2 in memory so all subsequent filtering / edits / output
    # use the canonical schema. Idempotent for v2 inputs.
    data = upgrade_decisions_v1_to_v2(data)

    rows = data.get("decisions")
    if not isinstance(rows, list):
        return original

    # 1. Apply user edits FIRST. apply_edits_to_decisions_data flips
    #    affected rows to status=overridden, populating the v2 `override`
    #    field. This means the trim (step 2) sees the row as overridden
    #    and preserves it — without this ordering, a Phase-1 edit forked
    #    at Phase 1 would be silently eaten by the trim. (See #544.)
    if edits:
        data = apply_edits_to_decisions_data(data, edits=edits)

    # 2. Phase trim: drop rows whose phase ordinal >= fork_ordinal, with
    #    one exception — `status: overridden` rows survive the trim
    #    regardless of which phase they belong to. Overrides represent
    #    explicit human intent: the override is honored when the relevant
    #    phase next runs (whether re-running as part of this fork, or
    #    later in fresh execution).
    if fork_ordinal is not None:
        kept: list = []
        for row in data["decisions"]:
            if not isinstance(row, dict):
                kept.append(row)
                continue
            if row.get("status") == "overridden":
                kept.append(row)
                continue
            phase_name = str(row.get("phase") or "").strip()
            if not phase_name:
                kept.append(row)
                continue
            ordinal = _resolve_phase_ordinal(phase_name)
            if ordinal is None or ordinal < fork_ordinal:
                kept.append(row)
        data["decisions"] = kept

    # 3. Mode filter: keep-overrides-only drops AI defaults from upstream
    #    so downstream phases re-derive them with the new overrides in
    #    context. keep-all is a no-op here.
    if mode == "keep-overrides-only":
        data["decisions"] = [
            row for row in data["decisions"]
            if isinstance(row, dict) and row.get("status") == "overridden"
        ]

    return yaml.safe_dump(data, sort_keys=False)
