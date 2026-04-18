"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns a fully-expanded OppSnapshot suitable for JSON serialization.

This file handles the STRUCTURED layout:
    ACE/<slug>/opp.yaml
    ACE/<slug>/pdd.md
    ACE/<slug>/runs/<run-id>/run.yaml
    ACE/<slug>/runs/<run-id>/events.jsonl
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/step.yaml
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/judge.yaml
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/gates.jsonl
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/output/<artifact>

Flat-layout fallback (for legacy ACE/<slug>/state.yaml + pdd.md + subfolders)
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
    path: str  # relative to the step's output/ folder, e.g. "pdd.md"


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
    pdd_body: str
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
        # Flat legacy layout — no opp.yaml, state.yaml at the top level.
        return _load_flat_opp(client, slug=slug, opp_folder=opp_folder, opp_children=opp_children)

    opp_manifest = parse_opp_yaml(_read_text(client, opp_yaml_file))

    # IDD→PDD rename transition: accept either primary-doc filename.
    pdd_file = _find_child(opp_children, "pdd.md") or _find_child(opp_children, "idd.md")
    pdd_body = _read_text(client, pdd_file) if pdd_file else ""

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
        pdd_body=pdd_body,
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


# --- Flat legacy layout support ---

# Map from flat-layout subfolder name to the set of skills whose artifacts
# are expected to live inside it. Derived from the ACE plugin's current
# conventions (see ../ace/docs/generated/playbook.md).
_FLAT_SUBFOLDER_SKILLS: dict[str, set[str]] = {
    "app-summaries": {"pdd-to-learn-app", "pdd-to-deliver-app"},
    "test-results": {"app-test"},
    "training-materials": {"training-materials"},
    "comms-log": {"llo-onboarding", "llo-invite", "llo-feedback"},
    "closeout": {"opp-closeout", "learnings-summary", "cycle-grade"},
}


def _load_flat_opp(
    client: DriveClient,
    *,
    slug: str,
    opp_folder: DriveFile,
    opp_children: list[DriveFile],
) -> OppSnapshot:
    """Read a legacy flat-layout opp as an implicit single run."""
    import yaml

    from apps.opps.skills import SKILL_REGISTRY

    # Parse state.yaml if present for current_step / mode hints.
    state_file = _find_child(opp_children, "state.yaml")
    state_data: dict = {}
    if state_file is not None:
        raw = _read_text(client, state_file)
        state_data = yaml.safe_load(raw) or {}

    # IDD→PDD rename transition: accept either primary-doc filename.
    pdd_file = _find_child(opp_children, "pdd.md") or _find_child(opp_children, "idd.md")
    pdd_body = _read_text(client, pdd_file) if pdd_file else ""

    # Build a map of subfolder name -> list of DriveFile (recursively) so we
    # can look up which skills have produced output.
    subfolder_files: dict[str, list[DriveFile]] = {}
    for child in opp_children:
        if child.mime_type == "application/vnd.google-apps.folder":
            subfolder_files[child.name] = client.list_files(child.id, recursive=True)

    # Build a skill_name -> [ArtifactRef] map from the subfolder mapping.
    artifacts_by_skill: dict[str, list[ArtifactRef]] = {}
    for subfolder_name, skills in _FLAT_SUBFOLDER_SKILLS.items():
        files = subfolder_files.get(subfolder_name, [])
        artifact_refs = [
            ArtifactRef(
                name=f.name,
                drive_file_id=f.id,
                drive_web_link=f.web_view_link,
                size_bytes=f.size_bytes,
                mime_type=f.mime_type,
                path=f.path,
            )
            for f in files
            if f.mime_type != "application/vnd.google-apps.folder"
        ]
        for skill in skills:
            artifacts_by_skill.setdefault(skill, []).extend(artifact_refs)

    # Also treat pdd.md (or legacy idd.md) as the artifact for idea-to-pdd.
    if pdd_file is not None:
        artifacts_by_skill.setdefault("idea-to-pdd", []).append(
            ArtifactRef(
                name=pdd_file.name,
                drive_file_id=pdd_file.id,
                drive_web_link=pdd_file.web_view_link,
                size_bytes=pdd_file.size_bytes,
                mime_type=pdd_file.mime_type,
                path=pdd_file.name,
            )
        )

    # Synthesize step rows from the canonical skill registry.
    steps: list[StepSnapshot] = []
    for skill_meta in SKILL_REGISTRY:
        artifacts = artifacts_by_skill.get(skill_meta.name, [])
        status = "complete" if artifacts else "pending"
        step_manifest = StepManifest(
            skill_name=skill_meta.name,
            phase=skill_meta.phase,
            ordinal=skill_meta.ordinal,
            status=status,
        )
        steps.append(
            StepSnapshot(
                step=step_manifest,
                judge=None,
                gates=[],
                artifacts=artifacts,
                folder_id=opp_folder.id,
            )
        )

    run_detail = RunDetail(
        run_id="r1",
        mode=state_data.get("mode", "review"),
        status="running",
        started_at=state_data.get("started_at"),
        completed_at=None,
        current_phase=state_data.get("current_phase"),
        current_step=state_data.get("current_step"),
        skill_versions={},
        notes="Legacy flat-layout opp — synthesized as implicit single run 'r1'.",
        steps=steps,
        folder_id=opp_folder.id,
    )

    opp_manifest = OppManifest(
        slug=slug,
        display_name=state_data.get("display_name", slug),
        created_at=state_data.get("started_at"),
        created_by=state_data.get("created_by"),
        labels=[],
        current_run_id="r1",
    )

    return OppSnapshot(
        opp=opp_manifest,
        pdd_body=pdd_body,
        opp_folder_id=opp_folder.id,
        all_runs=[
            RunSummary(
                run_id="r1",
                status="running",
                started_at=state_data.get("started_at"),
                completed_at=None,
                folder_id=opp_folder.id,
            )
        ],
        current_run=run_detail,
    )


def delete_opp_folder(client: DriveClient, *, ace_folder_id: str, slug: str) -> None:
    """Trash the `ACE/<slug>/` folder. Raises FileNotFoundError if missing."""
    for child in client.list_files(ace_folder_id):
        if child.name == slug and child.mime_type == "application/vnd.google-apps.folder":
            client.trash_folder(child.id)
            return
    raise FileNotFoundError(f"no opp folder named {slug!r} under ACE root")
