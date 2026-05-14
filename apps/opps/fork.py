"""Fork a run: create a new run folder, copy artifacts upstream of the
fork point, create a new working session seeded with context.

Two modes:
- with-feedback: copy step folders for all skills upstream of `from_skill`
  (by ordinal) and seed a new working session with the user's feedback.
- empty: inherit only a minimal run_state.yaml. Create a fresh empty run.

See docs/specs/2026-04-15-web-native-opp-lifecycle-design.md § 4.5.

## Naming conventions — must match the ACE plugin

The ACE plugin and ace-web operate on the same Drive folder tree, so
both sides MUST agree on:

- **Run-id format.** `YYYYMMDD-HHMM` (UTC), with a `-N` collision suffix
  if two forks fire within the same minute. The ACE plugin's `/ace:run`
  command generates run-ids in this format; mismatching `run-NNN` here
  would create runs the plugin's commands can't address.

- **State file name.** `run_state.yaml` (renamed from `state.yaml` in
  ACE plugin v0.11.3). The orchestrator at
  `agents/ace-orchestrator.md` only reads `run_state.yaml`; a forked
  run with state under any other name is uninvokable via `/ace:run`.

Both alignments shipped 2026-05-14 in response to the ACE plugin's
fork-run skill (see ace#346 / ace PR #284).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from django.db import transaction

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.models import OppWorkspace
from apps.opps.sync import load_opp
from apps.sessions.models import Message, Session


class ForkError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ForkResult:
    new_run_id: str
    working_session: Session


def _next_run_id(existing: list[str]) -> str:
    """Generate a `YYYYMMDD-HHMM`-format run-id matching the ACE plugin
    convention. If a run with the same minute timestamp already exists
    (rare but possible when forks fire in rapid succession), append a
    `-N` suffix and increment until a free slot is found.

    Matches `commands/run.md` and `agents/ace-orchestrator.md` § State
    Schema in the ACE plugin. Avoid drift here — runs created with
    other formats are uninvokable via the plugin's `/ace:run <opp>/<id>`.
    """
    base = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    if base not in existing:
        return base
    suffix = 1
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def fork_run(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    slug: str,
    from_run_id: str,
    from_skill: str,
    mode: str,
    feedback: str | None,
    owner,
) -> ForkResult:
    if mode not in ("with-feedback", "empty"):
        raise ForkError("invalid-mode", f"invalid mode {mode!r}")
    if mode == "with-feedback" and not feedback:
        raise ForkError("feedback-required", "with-feedback requires feedback text")

    # Load the source run to discover the fork step's ordinal.
    try:
        snap = load_opp(
            drive, ace_folder_id=ace_root_folder_id, slug=slug, run_id=from_run_id,
        )
    except FileNotFoundError as exc:
        raise ForkError("opp-not-found", f"opp {slug!r} not found") from exc

    fork_step = next(
        (s for s in snap.current_run.steps if s.step.skill_name == from_skill), None,
    )
    if fork_step is None:
        raise ForkError(
            "step-not-found", f"skill {from_skill!r} not in run {from_run_id}",
        )
    fork_ordinal = fork_step.step.ordinal

    opp_folder_id = snap.opp_folder_id
    opp_children = drive.list_files(opp_folder_id)
    runs_folder = next(
        (
            f for f in opp_children
            if f.name == "runs" and f.mime_type.endswith("folder")
        ),
        None,
    )
    if runs_folder is None:
        raise ForkError("no-runs-folder", "runs/ folder not found")

    run_children = drive.list_files(runs_folder.id)
    existing_run_names = [
        f.name for f in run_children if f.mime_type.endswith("folder")
    ]
    new_run_id = _next_run_id(existing_run_names)

    new_run_folder_id = drive.create_folder(runs_folder.id, new_run_id)

    src_run = next((f for f in run_children if f.name == from_run_id), None)
    if src_run is None:
        raise ForkError("src-run-missing", f"run {from_run_id!r} not found")

    if mode == "with-feedback":
        _copy_upstream_steps(
            drive=drive,
            src_run=src_run,
            dst_run_folder_id=new_run_folder_id,
            fork_ordinal=fork_ordinal,
        )
        # Carry forward run_state.yaml (if present at the run root) so the
        # new run starts with the same overall metadata. The file was
        # renamed from state.yaml → run_state.yaml in ACE plugin v0.11.3;
        # this side matches the current name (see module docstring).
        src_state = next(
            (
                f for f in drive.list_files(src_run.id)
                if f.name == "run_state.yaml"
            ),
            None,
        )
        if src_state is not None:
            content = drive.get_content(src_state.id, src_state.mime_type).content
            drive.upload_file(
                new_run_folder_id, "run_state.yaml", content,
                src_state.mime_type or "application/yaml",
            )
    else:  # mode == "empty"
        state = (
            f"opp: {slug}\n"
            f"mode: review\n"
            f"current_run: {new_run_id}\n"
            f"forked_from: {from_run_id} (empty fork)\n"
        )
        drive.upload_file(
            new_run_folder_id, "run_state.yaml", state, "application/yaml",
        )

    # Seed a new working session, repoint the workspace to it.
    with transaction.atomic():
        session = Session.objects.create(
            owner=owner,
            title=f"{slug} — {new_run_id}",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id=new_run_id,
        )
        seed_system = (
            f"Forked from {from_run_id} at step `{from_skill}` ({mode} fork). "
            f"Inherited artifacts live in the new run."
        )
        Message.objects.create(
            session=session, turn_index=0, role="system",
            sender_user=owner,
            content={"type": "system", "source": "opps-fork"},
            plaintext=seed_system, status="complete",
        )
        if mode == "with-feedback":
            user_text = (
                f"Rerun /ace:step {from_skill} for {slug} with feedback: {feedback}"
            )
            user_source = "opps-fork-feedback"
        else:
            user_text = (
                f"Run /ace:step idea-to-pdd for {slug} "
                f"(empty fork from {from_run_id})."
            )
            user_source = "opps-fork-empty"
        Message.objects.create(
            session=session, turn_index=1, role="user",
            sender_user=owner,
            content={"type": "text", "source": user_source},
            plaintext=user_text, status="complete",
        )
        try:
            workspace = OppWorkspace.objects.get(slug=slug)
            workspace.working_session = session
            workspace.save(update_fields=["working_session", "updated_at"])
        except OppWorkspace.DoesNotExist:
            pass

    return ForkResult(new_run_id=new_run_id, working_session=session)


def _copy_upstream_steps(
    *,
    drive: DriveClient,
    src_run: DriveFile,
    dst_run_folder_id: str,
    fork_ordinal: int,
) -> None:
    """Copy each step folder whose ordinal is strictly less than fork_ordinal."""
    src_steps_folder = next(
        (
            f for f in drive.list_files(src_run.id)
            if f.name == "steps" and f.mime_type.endswith("folder")
        ),
        None,
    )
    if src_steps_folder is None:
        return
    new_steps_folder_id = drive.create_folder(dst_run_folder_id, "steps")
    for step_folder in drive.list_files(src_steps_folder.id):
        if not step_folder.mime_type.endswith("folder"):
            continue
        # Step folder names are "<ordinal>-<skill>", e.g. "01-idea-to-idd".
        m = re.match(r"^(\d+)-", step_folder.name)
        if not m:
            continue
        if int(m.group(1)) >= fork_ordinal:
            continue
        _copy_tree_into(drive, step_folder, new_steps_folder_id)


def _copy_tree_into(
    drive: DriveClient, src: DriveFile, dst_parent_id: str,
) -> None:
    """Recursively copy src (folder or file) into dst_parent_id, preserving name."""
    if src.mime_type.endswith("folder"):
        new_folder_id = drive.create_folder(dst_parent_id, src.name)
        for child in drive.list_files(src.id):
            _copy_tree_into(drive, child, new_folder_id)
    else:
        drive.copy_file(src.id, dst_parent_id, new_name=src.name)
