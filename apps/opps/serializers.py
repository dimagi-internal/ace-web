"""Plain dict serializers for the Workbench payload.

Not DRF Serializer classes — just pure functions that convert the sync layer's
dataclasses into plain dicts matching the shape the React frontend expects.
The choice is deliberate: DRF serializers shine for model-backed reads/writes
with validation, but everything here is read-only from Drive and we already
have strict validation in the parsers.

Phase + per-skill metadata (display names, ordinals, has_judge, is_recurring)
is read from the ACE plugin via ``apps.system.reader.load_system_overview`` —
the same source the System tab uses. This keeps the Workbench in lock-step
with the plugin's agent frontmatter; adding a phase or skill is a one-file
edit in the plugin, not a code change here.
"""
from __future__ import annotations

import datetime
from typing import Any

from django.conf import settings

from apps.opps.parsers import Decision, JudgeVerdict, OppManifest, QAResult
from apps.opps.previews import build_preview
from apps.opps.sync import (
    ArtifactRef,
    OppSnapshot,
    RunDetail,
    ScorecardSnapshot,
    StepSnapshot,
)
from apps.system.reader import load_system_overview

_SYSTEM_OVERVIEW_CACHE: dict[str, Any] | None = None


def _system_overview() -> dict[str, Any]:
    """Lazy-load the system overview (phase + skill metadata from the ACE
    plugin). Computed once per process; tests can clear it via
    ``reset_system_overview_cache()`` when they swap ``ACE_PLUGIN_PATH``."""
    global _SYSTEM_OVERVIEW_CACHE
    if _SYSTEM_OVERVIEW_CACHE is None:
        _SYSTEM_OVERVIEW_CACHE = load_system_overview(
            getattr(settings, "ACE_PLUGIN_PATH", "") or ""
        )
    return _SYSTEM_OVERVIEW_CACHE


def reset_system_overview_cache() -> None:
    """Test helper — clear the cached system overview so the next call
    reloads from the (possibly overridden) ``ACE_PLUGIN_PATH``.

    Also clears ``apps.system.reader``'s per-path caches; this wrapper
    pre-dates those caches and tests still expect a single reset call to
    flush every layer."""
    global _SYSTEM_OVERVIEW_CACHE
    _SYSTEM_OVERVIEW_CACHE = None
    from apps.system.reader import clear_caches as _clear_reader_caches  # noqa: PLC0415

    _clear_reader_caches()


def serialize_artifact(a: ArtifactRef) -> dict:
    return {
        "name": a.name,
        "drive_file_id": a.drive_file_id,
        "drive_web_link": a.drive_web_link,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "path": a.path,
    }


def normalize_score_pct(score: float | None) -> float | None:
    """Project a judge score onto a 0-100 scale.

    ``apps.opps.sync._parse_verdict_yaml`` already normalizes scores to
    0-100 at parse time when the verdict YAML declares an explicit
    ``scale:`` annotation (covers 0-3, 0-10, 0-100 and any custom
    rubric). For verdicts without that annotation we fall back to a
    magnitude heuristic — same shape as the legacy inline branching.

    The heuristic is right for 0-10 and 0-100 inputs but is necessarily
    wrong for 0-3 unannotated rubrics (score=3 reads as already-100, but
    looks like 30/100 if normalized as 0-10). Plugin convention is to
    declare the scale explicitly; this is the floor when it doesn't.
    """
    if score is None:
        return None
    if score > 10:
        return float(score)
    return float(score) * 10.0


def serialize_judge(j: JudgeVerdict | None) -> dict | None:
    if j is None:
        return None
    return {
        "score": j.score,
        "score_pct": normalize_score_pct(j.score),
        "passed": j.passed,
        "evaluated_at": j.evaluated_at,
        "criteria": j.criteria,
        "rationale": j.rationale,
    }


def serialize_qa_result(qa: QAResult | None) -> dict | None:
    """Serialize a QAResult for the API.

    QA is binary (no scores) and structurally distinct from eval verdicts.
    Front-end renders it as green check / red X with the failed-checks
    list (vs the eval's score donut). The ``failures`` array preserves
    each ``auto_fix_hint`` so operators can see exactly what the
    orchestrator tried (or would try) to remediate.
    """
    if qa is None:
        return None
    return {
        "skill": qa.skill,
        "target_skill": qa.target_skill,
        "verdict": qa.verdict,
        "ran_at": qa.ran_at,
        "capture_path": qa.capture_path,
        "stats": {
            "checks_run": qa.checks_run,
            "checks_passed": qa.checks_passed,
            "checks_failed": qa.checks_failed,
        },
        "failures": [
            {
                "check": f.check,
                "type": f.type,
                "detail": f.detail,
                "auto_fix_hint": f.auto_fix_hint,
            }
            for f in qa.failures
        ],
        "auto_fix": {
            "attempted": qa.auto_fix_attempted,
            "attempts": qa.auto_fix_attempts,
            "succeeded": qa.auto_fix_succeeded,
        }
        if qa.auto_fix_attempted is not None
        else None,
    }


def serialize_step_snapshot(
    step_snap: StepSnapshot, bodies: dict[str, str] | None = None
) -> dict:
    bodies = bodies or {}
    overview = _system_overview()
    skill_lookup = {s["name"]: s for s in overview.get("skills") or []}
    phase_lookup = {p["name"]: p for p in overview.get("phases") or []}

    skill_meta = skill_lookup.get(step_snap.step.skill_name)
    phase_name = (skill_meta or {}).get("phase") or step_snap.step.phase
    phase_meta = phase_lookup.get(phase_name)
    phase_display = (phase_meta or {}).get("display_name") or phase_name

    has_judge = bool((skill_meta or {}).get("has_judge"))
    is_recurring = bool((skill_meta or {}).get("is_recurring"))

    display_name = (skill_meta or {}).get("display_name") or step_snap.step.skill_name

    return {
        "skill_name": step_snap.step.skill_name,
        "display_name": display_name,
        "phase": phase_name,
        "phase_display": phase_display,
        "ordinal": step_snap.step.ordinal,
        "status": step_snap.step.status,
        "started_at": step_snap.step.started_at,
        "completed_at": step_snap.step.completed_at,
        "error": step_snap.step.error,
        "has_judge": has_judge,
        "is_recurring": is_recurring,
        "preview_text": build_preview(step_snap, bodies),
        "judge": serialize_judge(step_snap.judge),
        "qa_result": serialize_qa_result(step_snap.qa_result),
        "artifacts": [serialize_artifact(a) for a in step_snap.artifacts],
    }


def _phase_name_by_ordinal() -> dict[int, str]:
    """Map phase ordinal → phase name (e.g. 1 → "design-review").

    The decisions log tags rows with the artifact-manifest folder
    convention (``1-design``, ``2-commcare``, …) — short, ordinal-prefixed.
    The system overview uses the agent-name form (``design-review``,
    ``commcare-setup``, …). Front-end groups decisions by phase, so we
    project decisions onto the snapshot's phase taxonomy here.
    """
    overview = _system_overview()
    out: dict[int, str] = {}
    for p in overview.get("phases") or []:
        ordinal = p.get("ordinal")
        name = p.get("name")
        if isinstance(ordinal, int) and isinstance(name, str):
            out[ordinal] = name
    return out


def _project_decision_phase(raw: str) -> str:
    """Project a decision row's ``phase`` tag onto the canonical phase
    name used by the snapshot. ``"1-design"`` → ``"design-review"``.

    Returns the raw tag unchanged when we can't parse an ordinal — this
    keeps unknown phases visible (just unfilterable) rather than dropping
    rows silently.
    """
    if not raw:
        return raw
    head = raw.split("-", 1)[0]
    try:
        ordinal = int(head)
    except ValueError:
        return raw
    return _phase_name_by_ordinal().get(ordinal, raw)


def serialize_decision(d: Decision) -> dict:
    return {
        "id": d.id,
        "phase": _project_decision_phase(d.phase),
        "phase_raw": d.phase,
        "skill": d.skill,
        "question": d.question,
        "ai_default": d.ai_default,
        "override": d.override,
        "options_considered": list(d.options_considered),
        "source": d.source,
        "status": d.status,
        "notes": d.notes,
        "override_reasoning": d.override_reasoning,
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
        "decisions": [serialize_decision(d) for d in run.decisions],
    }


def serialize_opp_card(opp: OppManifest, current_run: RunDetail | None) -> dict:
    return {
        "slug": opp.slug,
        "display_name": opp.display_name,
        "labels": opp.labels,
        "tags": list(opp.tags),
        "created_at": opp.created_at,
        "created_by": opp.created_by,
        "current_run_id": opp.current_run_id,
        "current_phase": current_run.current_phase if current_run else None,
        "current_step": current_run.current_step if current_run else None,
        "status": current_run.status if current_run else "unknown",
    }


def serialize_opp_snapshot(snap: OppSnapshot) -> dict:
    overview = _system_overview()
    out = {
        "opp": serialize_opp_card(snap.opp, snap.current_run),
        "pdd_body": snap.pdd_body,
        "current_run": serialize_run_detail(snap.current_run),
        "phases": list(overview.get("phases") or []),
    }
    out["runs"] = [
        {
            "run_id": r.run_id,
            "current_phase": r.current_phase,
            "current_step": r.current_step,
            "mode": r.mode,
            "last_actor": r.last_actor,
            # PyYAML may parse ISO timestamps as datetime objects; normalise to str.
            "last_actor_at": (
                r.last_actor_at.isoformat().replace("+00:00", "Z")
                if isinstance(r.last_actor_at, datetime.datetime)
                else r.last_actor_at
            ),
        }
        for r in (getattr(snap, "runs_summary", None) or [])
    ]
    out["selected_run_id"] = (
        snap.current_run.run_id if snap.current_run is not None else None
    )
    return out


def serialize_scorecard(sc: ScorecardSnapshot) -> dict:
    """Run-level opp-eval payload for the Workbench header."""
    return {
        "latest_verdict": serialize_judge(sc.latest_verdict),
        "latest_verdict_variant": sc.latest_verdict_variant,
        "latest_scorecard_path": sc.latest_scorecard_path,
        "latest_scorecard_body": sc.latest_scorecard_body,
        "trend_path": sc.trend_path,
        "trend_body": sc.trend_body,
    }
