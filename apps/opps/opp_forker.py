"""Fork a run within an opp.

Per the ACE plugin's canonical fork contract
(``agents/orchestrator-reference.md`` § Fork Points, ace 0.13.151),
forking does NOT create a new opp. It mints a new run-id under the
**same** opp folder and seeds it from a prior run's outputs.

Per-opp resources stay untouched — ``opp.yaml``, ``inputs/``,
``eval-calibration/``, ``open-questions.md``, ``connect-state.yaml``,
``current/``. They live above ``runs/`` and every run shares them.

Per-run resources get a fresh home under ``runs/<new-run-id>/``:

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
    working_session: Session


ProgressCb = Callable[[dict], None]


def fork_opp(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    owner,
    source_slug: str,
    fork_at_phase: str,
    source_run_id: str | None = None,
    workspace=None,
    progress_cb: ProgressCb | None = None,
    edits: list[dict[str, str]] | None = None,
    mode: str = DEFAULT_FORK_MODE,
    now: _dt.datetime | None = None,
) -> ForkOppResult:
    """Fork the source opp's named run (or its latest if ``source_run_id``
    is None) into a new run under the same opp.

    ``mode`` controls how upstream decisions carry forward:
    ``keep-overrides-only`` keeps only ``status: overridden`` rows from
    phases strictly before the fork point; ``keep-all`` keeps every
    upstream row regardless of status. See ``FORK_MODES`` at module top.

    Raises ``ForkOppError`` for caller-friendly validation failures
    (source not found, no runs to fork from, run-id collision, unknown
    mode). Drive failures during the copy bubble up; partial state may
    be left behind (the new run folder will exist but be incomplete)
    and the operator can delete it via the existing run-trash flow.
    """
    if mode not in FORK_MODES:
        raise ForkOppError(
            "invalid-mode",
            f"mode {mode!r} is not valid; expected one of {FORK_MODES}",
        )

    fork_ordinal = _resolve_phase_ordinal(fork_at_phase)
    if fork_ordinal is None:
        # Fail fast rather than degenerate to "copy everything." A fork
        # against an unknown phase silently producing a no-op trim (i.e.
        # cloning the source run wholesale) is the bug the per-run fork
        # contract exists to prevent — the next /ace:run would see every
        # phase already done. The most likely cause is ACE_PLUGIN_PATH
        # pointing at a missing/stale plugin checkout.
        raise ForkOppError(
            "unknown-phase",
            f"phase {fork_at_phase!r} is not in the skill registry — "
            "check ACE_PLUGIN_PATH",
        )

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

    # Pre-walk to count files we'll actually copy. Cheaper than the
    # copy itself (one list_files per kept folder vs. ~150 ms per
    # copy_file), so the UX win — accurate "X of Y" — is worth it.
    _emit(progress_cb, {"status": "counting", "copied": 0, "total": 0})
    total_files = _count_files_to_copy(
        drive, source_run.id, fork_ordinal=fork_ordinal,
    )
    counter = _Counter(total=total_files)
    _emit(progress_cb, {
        "status": "copying", "copied": 0, "total": total_files, "current": "",
    })

    new_run_folder_id = drive.create_folder(runs_folder.id, new_run_id)
    decisions_dest_id, decisions_source_body = _copy_run_subtree(
        drive=drive,
        source_run_folder_id=source_run.id,
        dest_run_folder_id=new_run_folder_id,
        fork_ordinal=fork_ordinal,
        counter=counter,
        progress_cb=progress_cb,
    )

    _emit(progress_cb, {
        "status": "finalizing", "copied": counter.copied, "total": total_files,
    })

    # Synthesize the new run's run_state.yaml. We intentionally DON'T
    # copy the source run's run_state — its phases map and timestamps
    # belong to the prior run. Generating fresh keeps the new run's
    # state honest about what's done vs. pending.
    new_state = _build_run_state_yaml(
        opp_slug=source_slug,
        run_id=new_run_id,
        owner_email=getattr(owner, "email", "") or "unknown",
        fork_at_phase=fork_at_phase,
        fork_ordinal=fork_ordinal,
        forked_from_run_id=source_run.name,
        now_utc=now_utc,
    )
    drive.upload_file(
        new_run_folder_id, "run_state.yaml", new_state, "text/yaml",
    )

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

    session = Session.create_with_owner(
        owner=owner,
        title=f"{source_slug} — new run {new_run_id} (fork @ {fork_at_phase})",
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
            "source_run_id": source_run.name,
            "new_run_id": new_run_id,
        },
        plaintext=(
            f"Forked run `{new_run_id}` from `{source_run.name}` at phase "
            f"`{fork_at_phase}`. Re-run /ace:run to continue from there."
        ),
        status="complete",
    )

    _emit(progress_cb, {
        "status": "done",
        "copied": counter.copied,
        "total": total_files,
        "opp_slug": source_slug,
        "new_run_id": new_run_id,
    })
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
class _Counter:
    total: int
    copied: int = 0


def _count_files_to_copy(
    drive: DriveClient, source_run_folder_id: str, *, fork_ordinal: int | None,
) -> int:
    """Count files we'll actually copy from the source run folder.

    Mirrors the filter applied by ``_copy_run_subtree`` — files at the
    run root that aren't in ``_RUN_ROOT_FILES_TO_COPY`` aren't counted,
    and phase folders past the fork point aren't recursed into.
    """
    n = 0
    for child in drive.list_files(source_run_folder_id):
        if child.mime_type == _FOLDER_MIME:
            if _should_skip_phase_folder(child.name, fork_ordinal):
                continue
            if not _PHASE_FOLDER_RE.match(child.name):
                # Run-root folders other than `<N>-phase/` aren't part
                # of the canonical per-run layout; skip them rather than
                # blindly copying unknown content.
                continue
            n += _count_files_recursive(drive, child.id)
        else:
            if child.name in _RUN_ROOT_FILES_TO_COPY:
                n += 1
    return n


def _count_files_recursive(drive: DriveClient, folder_id: str) -> int:
    n = 0
    for child in drive.list_files(folder_id):
        if child.mime_type == _FOLDER_MIME:
            n += _count_files_recursive(drive, child.id)
        else:
            n += 1
    return n


def _should_skip_phase_folder(folder_name: str, fork_ordinal: int | None) -> bool:
    """True iff ``folder_name`` is a phase folder for a phase at or after
    the fork point. Folders not matching ``<N>-…`` are never skipped here."""
    if fork_ordinal is None:
        return False
    m = _PHASE_FOLDER_RE.match(folder_name)
    if not m:
        return False
    return int(m.group(1)) >= fork_ordinal


# ── Copy ───────────────────────────────────────────────────────────


def _copy_run_subtree(
    *,
    drive: DriveClient,
    source_run_folder_id: str,
    dest_run_folder_id: str,
    fork_ordinal: int | None,
    counter: _Counter,
    progress_cb: ProgressCb | None,
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
            if _should_skip_phase_folder(child.name, fork_ordinal):
                continue
            if not _PHASE_FOLDER_RE.match(child.name):
                # Per the canonical layout, run-root subfolders are all
                # `<N>-phase/`. Anything else is unrecognized; leave it
                # in the source and don't propagate to the new run.
                continue
            sub_id = drive.create_folder(dest_run_folder_id, child.name)
            _copy_subtree_verbatim(
                drive=drive,
                source_folder_id=child.id,
                dest_folder_id=sub_id,
                rel_path=child.name,
                counter=counter,
                progress_cb=progress_cb,
            )
        else:
            if child.name not in _RUN_ROOT_FILES_TO_COPY:
                continue
            new_id = drive.copy_file(child.id, dest_run_folder_id, child.name)
            if child.name in ("decisions.yaml", "decisions.yml"):
                decisions_dest_id = new_id
                decisions_source_body = _read_text_or_empty(drive, child)
            counter.copied += 1
            _emit(progress_cb, {
                "status": "copying",
                "copied": counter.copied,
                "total": counter.total,
                "current": child.name,
            })
    return decisions_dest_id, decisions_source_body


def _copy_subtree_verbatim(
    *,
    drive: DriveClient,
    source_folder_id: str,
    dest_folder_id: str,
    rel_path: str,
    counter: _Counter,
    progress_cb: ProgressCb | None,
) -> None:
    """Copy every child of a kept phase folder, no filtering."""
    for child in drive.list_files(source_folder_id):
        new_path = f"{rel_path}/{child.name}"
        if child.mime_type == _FOLDER_MIME:
            sub_id = drive.create_folder(dest_folder_id, child.name)
            _copy_subtree_verbatim(
                drive=drive,
                source_folder_id=child.id,
                dest_folder_id=sub_id,
                rel_path=new_path,
                counter=counter,
                progress_cb=progress_cb,
            )
        else:
            drive.copy_file(child.id, dest_folder_id, child.name)
            counter.copied += 1
            _emit(progress_cb, {
                "status": "copying",
                "copied": counter.copied,
                "total": counter.total,
                "current": new_path,
            })


def _emit(progress_cb: ProgressCb | None, payload: dict) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(payload)
    except Exception:  # noqa: BLE001 — progress reporting must never break the fork
        pass


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


def _build_phases_map(fork_ordinal: int | None) -> dict[str, dict[str, str]]:
    """Build the ``phases`` map for a fresh run_state.yaml.

    Skills in phases ``< fork_ordinal`` are seeded ``done`` (we just
    carried their artifacts forward); skills in phases ``>= fork``
    start ``pending`` for the new run to overwrite.
    """
    from apps.opps.skills import SKILL_REGISTRY, all_phases

    phases_map: dict[str, dict[str, str]] = {}
    phase_order = all_phases()
    for skill in SKILL_REGISTRY:
        if skill.is_recurring:
            # Recurring skills aren't tracked in the per-phase map.
            continue
        try:
            phase_idx = phase_order.index(skill.phase) + 1
        except ValueError:
            continue
        if fork_ordinal is None:
            status = "pending"
        elif phase_idx < fork_ordinal:
            status = "done"
        else:
            status = "pending"
        phases_map.setdefault(skill.phase, {})[skill.name] = status
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
) -> str:
    """Synthesize a fresh ``run_state.yaml`` per the State Schema in the
    plugin's orchestrator-reference (§ State Schema, defensive init).

    Adds a ``forked_from`` block so lineage is visible without diving
    into Drive — the plugin doesn't read this field but humans will.
    """
    iso_now = now_utc.isoformat()
    data: dict = {
        "opportunity": opp_slug,
        "run_id": run_id,
        "mode": "default",
        "created": iso_now,
        "initiated_by": owner_email,
        "last_actor": owner_email,
        "last_actor_at": iso_now,
        "current_phase": fork_at_phase,
        "phases": _build_phases_map(fork_ordinal),
        "forked_from": {
            "run_id": forked_from_run_id,
            "phase": fork_at_phase,
            "forked_at": iso_now,
        },
    }
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
