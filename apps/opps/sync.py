"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns an OppSnapshot suitable for JSON serialization.

One layout, one entry point:

    ACE/<slug>/idea.md                  (required)
    ACE/<slug>/pdd.md  or  idd.md       (optional; consumed as the
                                         idea-to-pdd artifact)
    ACE/<slug>/state.yaml               (optional; written by /ace:run
                                         when the lifecycle starts)
    ACE/<slug>/<subfolder>/*            (optional; grouped artifacts
                                         per `_FLAT_SUBFOLDER_SKILLS`)

Per-opp step rows are synthesized from the canonical 19-skill registry
in ``apps.opps.skills`` — presence of a skill's expected subfolder flips
its row from `pending` to `complete`. Each opp is a single run; the
`run_id` slot always contains ``"r1"`` and exists only because the
frontend payload shape predates the drop-multi-run refactor.
See docs/plans/2026-04-20-drop-multi-run-simplify.md § deferred work.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.parsers import GateDecision, JudgeVerdict, OppManifest, StepManifest

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
class OppSnapshot:
    opp: OppManifest
    pdd_body: str
    opp_folder_id: str
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


# --- Flat layout: single-run per opp ---

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


def load_opp(
    client: DriveClient,
    *,
    ace_folder_id: str,
    slug: str,
    run_id: str | None = None,  # accepted for URL-shape compat; ignored
) -> OppSnapshot:
    """Load a full opp snapshot from ``ACE/<slug>/`` on Drive.

    Raises FileNotFoundError if no folder named ``slug`` exists under
    ``ace_folder_id``.

    ``run_id`` is accepted but ignored — there is exactly one run per
    opp. The parameter exists for URL-shape compatibility with the
    pre-refactor multi-run world; callers may pass ``"r1"`` or ``None``.
    """
    from apps.opps.skills import SKILL_REGISTRY

    # Locate the opp folder
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")

    opp_children = client.list_files(opp_folder.id)

    # Parse state.yaml if present for current_step / mode hints. Two
    # locations are checked for back-compat with opps created before
    # the drop-multi-run refactor (see docs/plans/2026-04-20-*.md):
    #   - ACE/<slug>/state.yaml   (current, written by /ace:run)
    #   - ACE/<slug>/runs/run-001/state.yaml  (legacy ace-web-created)
    state_file = _find_child(opp_children, "state.yaml")
    if state_file is None:
        runs_folder = _find_child(opp_children, "runs")
        if runs_folder is not None and runs_folder.mime_type == (
            "application/vnd.google-apps.folder"
        ):
            run_children = client.list_files(runs_folder.id)
            run1 = _find_child(run_children, "run-001")
            if run1 is not None and run1.mime_type == (
                "application/vnd.google-apps.folder"
            ):
                state_file = _find_child(
                    client.list_files(run1.id), "state.yaml"
                )
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
        notes="",
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
        current_run=run_detail,
    )


def delete_opp_folder(client: DriveClient, *, ace_folder_id: str, slug: str) -> None:
    """Trash the `ACE/<slug>/` folder. Raises FileNotFoundError if missing."""
    for child in client.list_files(ace_folder_id):
        if child.name == slug and child.mime_type == "application/vnd.google-apps.folder":
            client.trash_folder(child.id)
            return
    raise FileNotFoundError(f"no opp folder named {slug!r} under ACE root")
