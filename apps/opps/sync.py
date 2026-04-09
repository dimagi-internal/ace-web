"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns a fully-expanded OppSnapshot suitable for JSON serialization.

This file handles the STRUCTURED layout:
    ACE/<slug>/opp.yaml
    ACE/<slug>/idd.md
    ACE/<slug>/runs/<run-id>/run.yaml
    ACE/<slug>/runs/<run-id>/events.jsonl
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/step.yaml
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/judge.yaml
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/gates.jsonl
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/output/<artifact>

Flat-layout fallback (for legacy ACE/<slug>/state.yaml + idd.md + subfolders)
is in Task 11, as a second entry point in this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.parsers import (
    GateDecision,
    JudgeVerdict,
    OppManifest,
    StepManifest,
    parse_gates_jsonl,
    parse_judge_yaml,
    parse_opp_yaml,
    parse_run_yaml,
    parse_step_yaml,
)

# --- Output dataclasses ---


@dataclass
class ArtifactRef:
    name: str
    drive_file_id: str
    drive_web_link: str
    size_bytes: int | None
    mime_type: str
    path: str  # relative to the step's output/ folder, e.g. "idd.md"


@dataclass
class StepSnapshot:
    step: StepManifest
    judge: JudgeVerdict | None
    gates: list[GateDecision]
    artifacts: list[ArtifactRef]
    folder_id: str


@dataclass
class RunDetail:
    run_id: str
    mode: str
    status: str
    started_at: str | None
    completed_at: str | None
    current_phase: str | None
    current_step: str | None
    skill_versions: dict[str, str]
    notes: str
    steps: list[StepSnapshot]
    folder_id: str


@dataclass
class RunSummary:
    run_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    folder_id: str


@dataclass
class OppSnapshot:
    opp: OppManifest
    idd_body: str
    opp_folder_id: str
    all_runs: list[RunSummary]  # sorted newest-first
    current_run: RunDetail


# --- Drive helpers ---


def _find_child(files: list[DriveFile], name: str) -> DriveFile | None:
    for f in files:
        if f.name == name:
            return f
    return None


def _find_child_folder(files: list[DriveFile], name: str) -> DriveFile | None:
    f = _find_child(files, name)
    if f and f.mime_type == "application/vnd.google-apps.folder":
        return f
    return None


def _read_text(client: DriveClient, file: DriveFile) -> str:
    return client.get_content(file.id, file.mime_type).content


# --- Main entry point ---


def load_opp(
    client: DriveClient,
    *,
    ace_folder_id: str,
    slug: str,
    run_id: str | None = None,
) -> OppSnapshot:
    """Load a full opp snapshot from the STRUCTURED layout.

    If the given slug is not present under ace_folder_id, raises FileNotFoundError.
    If the slug is present but does not have an `opp.yaml` (i.e. it's a legacy
    flat layout), raises FileNotFoundError — callers should fall through to
    the flat-layout loader.
    """
    # Locate the opp folder
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")

    opp_children = client.list_files(opp_folder.id)
    opp_yaml_file = _find_child(opp_children, "opp.yaml")
    if opp_yaml_file is None:
        raise FileNotFoundError(
            f"opp {slug!r} has no opp.yaml — may be a legacy flat layout"
        )

    opp_manifest = parse_opp_yaml(_read_text(client, opp_yaml_file))

    idd_file = _find_child(opp_children, "idd.md")
    idd_body = _read_text(client, idd_file) if idd_file else ""

    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is None:
        raise FileNotFoundError(f"opp {slug!r} has no runs/ subfolder")

    run_folders = [
        f
        for f in client.list_files(runs_folder.id)
        if f.mime_type == "application/vnd.google-apps.folder"
    ]
    # Sort newest first by name (ids are date-prefixed per the spec).
    run_folders.sort(key=lambda f: f.name, reverse=True)

    if not run_folders:
        raise FileNotFoundError(f"opp {slug!r} has runs/ but no run folders inside")

    # Build lightweight summaries for the run switcher
    all_runs: list[RunSummary] = []
    for rf in run_folders:
        rf_children = client.list_files(rf.id)
        run_yaml_file = _find_child(rf_children, "run.yaml")
        if run_yaml_file is None:
            continue
        run = parse_run_yaml(_read_text(client, run_yaml_file))
        all_runs.append(
            RunSummary(
                run_id=run.run_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                folder_id=rf.id,
            )
        )

    # Resolve which run to expand
    target_run_id = run_id or opp_manifest.current_run_id or all_runs[0].run_id
    target_summary = next((r for r in all_runs if r.run_id == target_run_id), None)
    if target_summary is None:
        # Fall back to latest
        target_summary = all_runs[0]

    current_run = _load_run_detail(client, target_summary.folder_id)

    return OppSnapshot(
        opp=opp_manifest,
        idd_body=idd_body,
        opp_folder_id=opp_folder.id,
        all_runs=all_runs,
        current_run=current_run,
    )


def _load_run_detail(client: DriveClient, run_folder_id: str) -> RunDetail:
    files = client.list_files(run_folder_id)
    run_yaml_file = _find_child(files, "run.yaml")
    if run_yaml_file is None:
        raise FileNotFoundError("run folder has no run.yaml")
    run = parse_run_yaml(_read_text(client, run_yaml_file))

    steps_folder = _find_child_folder(files, "steps")
    steps: list[StepSnapshot] = []
    if steps_folder is not None:
        step_folders = [
            f
            for f in client.list_files(steps_folder.id)
            if f.mime_type == "application/vnd.google-apps.folder"
        ]
        # Sort by name (which is "<ordinal>-<skill>").
        step_folders.sort(key=lambda f: f.name)
        for sf in step_folders:
            steps.append(_load_step_snapshot(client, sf.id))

    return RunDetail(
        run_id=run.run_id,
        mode=run.mode,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        current_phase=run.current_phase,
        current_step=run.current_step,
        skill_versions=run.skill_versions,
        notes=run.notes,
        steps=steps,
        folder_id=run_folder_id,
    )


def _load_step_snapshot(client: DriveClient, step_folder_id: str) -> StepSnapshot:
    files = client.list_files(step_folder_id)

    step_yaml_file = _find_child(files, "step.yaml")
    if step_yaml_file is None:
        raise FileNotFoundError("step folder has no step.yaml")
    step = parse_step_yaml(_read_text(client, step_yaml_file))

    judge_file = _find_child(files, "judge.yaml")
    judge = parse_judge_yaml(_read_text(client, judge_file)) if judge_file else None

    gates_file = _find_child(files, "gates.jsonl")
    gates = parse_gates_jsonl(_read_text(client, gates_file)) if gates_file else []

    output_folder = _find_child_folder(files, "output")
    artifacts: list[ArtifactRef] = []
    if output_folder is not None:
        for f in client.list_files(output_folder.id, recursive=True):
            if f.mime_type == "application/vnd.google-apps.folder":
                continue
            artifacts.append(
                ArtifactRef(
                    name=f.name,
                    drive_file_id=f.id,
                    drive_web_link=f.web_view_link,
                    size_bytes=f.size_bytes,
                    mime_type=f.mime_type,
                    path=f.path,
                )
            )

    return StepSnapshot(
        step=step,
        judge=judge,
        gates=gates,
        artifacts=artifacts,
        folder_id=step_folder_id,
    )
