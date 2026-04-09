"""Plain dict serializers for the Workbench payload.

Not DRF Serializer classes — just pure functions that convert the sync layer's
dataclasses into plain dicts matching the shape the React frontend expects.
The choice is deliberate: DRF serializers shine for model-backed reads/writes
with validation, but everything here is read-only from Drive and we already
have strict validation in the parsers.
"""
from __future__ import annotations

from apps.opps.parsers import GateDecision, JudgeVerdict, OppManifest
from apps.opps.previews import build_preview
from apps.opps.skills import PHASE_DISPLAY_NAMES, get_skill
from apps.opps.sync import (
    ArtifactRef,
    OppSnapshot,
    RunDetail,
    RunSummary,
    StepSnapshot,
)


def serialize_artifact(a: ArtifactRef) -> dict:
    return {
        "name": a.name,
        "drive_file_id": a.drive_file_id,
        "drive_web_link": a.drive_web_link,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "path": a.path,
    }


def serialize_judge(j: JudgeVerdict | None) -> dict | None:
    if j is None:
        return None
    return {
        "score": j.score,
        "passed": j.passed,
        "evaluated_at": j.evaluated_at,
        "criteria": j.criteria,
        "rationale": j.rationale,
    }


def serialize_gate(g: GateDecision) -> dict:
    return {
        "ts": g.ts,
        "decision": g.decision,
        "decided_by": g.decided_by,
        "note": g.note,
    }


def serialize_step_snapshot(
    step_snap: StepSnapshot, bodies: dict[str, str] | None = None
) -> dict:
    bodies = bodies or {}
    try:
        skill_meta = get_skill(step_snap.step.skill_name)
        phase_display = PHASE_DISPLAY_NAMES.get(skill_meta.phase, skill_meta.phase)
        has_judge = skill_meta.has_judge
        is_gate = skill_meta.is_gate
        is_recurring = skill_meta.is_recurring
    except KeyError:
        phase_display = step_snap.step.phase
        has_judge = False
        is_gate = False
        is_recurring = False

    return {
        "skill_name": step_snap.step.skill_name,
        "phase": step_snap.step.phase,
        "phase_display": phase_display,
        "ordinal": step_snap.step.ordinal,
        "status": step_snap.step.status,
        "started_at": step_snap.step.started_at,
        "completed_at": step_snap.step.completed_at,
        "error": step_snap.step.error,
        "has_judge": has_judge,
        "is_gate": is_gate,
        "is_recurring": is_recurring,
        "preview_text": build_preview(step_snap, bodies),
        "judge": serialize_judge(step_snap.judge),
        "gates": [serialize_gate(g) for g in step_snap.gates],
        "artifacts": [serialize_artifact(a) for a in step_snap.artifacts],
    }


def serialize_run_detail(run: RunDetail) -> dict:
    return {
        "run_id": run.run_id,
        "mode": run.mode,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "current_phase": run.current_phase,
        "current_step": run.current_step,
        "skill_versions": run.skill_versions,
        "notes": run.notes,
        "steps": [serialize_step_snapshot(s) for s in run.steps],
    }


def serialize_run_summary(run: RunSummary) -> dict:
    return {
        "run_id": run.run_id,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


def serialize_opp_card(opp: OppManifest, current_run: RunDetail | None) -> dict:
    return {
        "slug": opp.slug,
        "display_name": opp.display_name,
        "labels": opp.labels,
        "created_at": opp.created_at,
        "created_by": opp.created_by,
        "current_run_id": opp.current_run_id,
        "current_phase": current_run.current_phase if current_run else None,
        "current_step": current_run.current_step if current_run else None,
        "status": current_run.status if current_run else "unknown",
    }


def serialize_opp_snapshot(snap: OppSnapshot) -> dict:
    return {
        "opp": serialize_opp_card(snap.opp, snap.current_run),
        "idd_body": snap.idd_body,
        "runs": [serialize_run_summary(r) for r in snap.all_runs],
        "current_run": serialize_run_detail(snap.current_run),
    }
