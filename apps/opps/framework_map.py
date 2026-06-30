"""Map the framework read model (``canopy_agent_runs.schemas``) onto ace-web's
existing ``apps/opps`` dataclasses.

This is the adapter seam for the wave-4 reader swap: ``canopy_agent_runs`` (the
Django-free run-lifecycle core packaged out of the canopy-web monorepo) reads
ACE's Drive run-folders and returns a storage-agnostic read model
(``Run`` / ``Step`` / ``Artifact`` / ``Verdict`` / ``Decision`` / ``Gate`` /
``RunSummary``). ace-web's serializers (``apps/opps/serializers.py``) read the
LEGACY dataclasses (``OppSnapshot`` / ``RunDetail`` / ``StepSnapshot`` /
``RunSummary`` / ``ArtifactRef`` and the parser dataclasses ``StepManifest`` /
``JudgeVerdict`` / ``QAResult`` / ``Decision``). This module turns the former
into the latter **field-for-field**, so the public surface (api.py,
serializers.py, schemas.py, dataclass field names) stays identical while the
read engine underneath becomes the framework lib.

WHY a mapper instead of changing the serializers: the serializers + the REST
schema are the load-bearing public contract (the React frontend, the OpenAPI
surface, the OppWorkspace model). Keeping them untouched and adapting at the
dataclass boundary makes the swap parity-gated and reversible.

----------------------------------------------------------------------------
EXTRA fields the framework read model does NOT carry (and where each comes from)
----------------------------------------------------------------------------
The framework schema is a deliberate REDUCTION of ACE's richer Drive shape.
Several ace dataclass fields therefore have no framework source. They split
into three buckets:

  (A) DERIVABLE from framework data — computed here, no extra I/O:
      * RunSummary.phases_total / phases_done / latest_phase_done / lifecycle_status
        — derived from the run's phase map. For the full ``Run`` we group its
        ``steps`` by phase (``Step.title`` carries the phase); for the list view
        we reuse ace's own ``_derive_phase_progress`` on the parsed run_state
        (parity-exact with the legacy reader).
      * RunDetail.status — ``Run.status`` is the framework's DERIVED status
        (pending|in_progress|complete). NOTE: the legacy ace reader HARDCODED
        ``status="running"`` here; the framework value is more correct, so this
        is the one known value-difference vs the legacy reader. Flagged for the
        stage-17 parity harness.
      * StepManifest.status — reverse of the framework's lossy forward map
        (qa-failed/error both collapse to ``failed``). We recover ``qa-failed``
        when the step carries a failing QA verdict, else ``error``.

  (B) STRAIGHT off run_state.yaml — supplied via the optional ``run_state``
      dict (the mapper does NOT re-read Drive; the caller passes the parsed
      run_state it already has, or omits it for the framework default):
      * RunDetail.mode is taken from ``Run.mode`` (already canonicalized by the
        framework: ACE's ``autopilot`` → ``auto``); ``run_state['mode']`` is the
        raw source if a caller wants the literal.
      * RunDetail.skill_versions — ``run_state['skill_versions']`` (legacy ace
        hardcoded ``{}``; we honor run_state if present, else ``{}``).
      * RunDetail.notes — ``run_state['notes']`` (legacy ace hardcoded ``""``).
      * RunSummary.last_actor / last_actor_at — ``run_state['last_actor']`` /
        ``run_state['last_actor_at']`` (framework RunSummary omits both).
      * OppManifest.created_by — ``run_state['created_by']`` /
        ``run_state['initiated_by']`` (framework Run has no created_by).
      * StepManifest.preview_stats — ``run_state``'s per-step ``preview_stats``
        when present, else ``{}`` (the legacy default).

  (C) Drive-identity / body fields with NO framework source — supplied by the
      caller (it built the ``DriveRunStore`` so it owns these ids):
      * RunDetail.folder_id        — the run folder's Drive id (``run_folder_id``).
      * StepSnapshot.folder_id     — same run folder id.
      * OppSnapshot.opp_folder_id  — the opp root folder id (``opp_folder_id``).
      * RunSummary.folder_id       — per-run folder id (``run_folder_id`` map).
      * OppSnapshot.pdd_body       — the PDD markdown body (``pdd_body``).

  ArtifactRef.drive_file_id / .path and the full Decision row (id / phase /
  options_considered / source / override_reasoning / conflict_signals) USED to
  be in this "no framework source, recover ace-side" bucket. The framework read
  model now carries them: ``Artifact.ref`` (the Drive file id) + ``Artifact.path``
  (run-relative), and the Decision schema ported ACE's full decisions-schema.
  They map straight across in ``map_artifact_ref`` / ``map_decision`` — ace is
  now a TRUE single reader, with no second pass over the run tree.

  Framework-only with NO ace home (NOT mapped): ``Gate`` (ace's OppSnapshot
  surface has no gate field), and ``Run.session_link`` / ``Run.forked_from``
  (the legacy snapshot does not expose them).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from canopy_agent_runs.schemas import (
    Artifact as FwArtifact,
)
from canopy_agent_runs.schemas import (
    Decision as FwDecision,
)
from canopy_agent_runs.schemas import (
    Run as FwRun,
)
from canopy_agent_runs.schemas import (
    RunSummary as FwRunSummary,
)
from canopy_agent_runs.schemas import (
    Step as FwStep,
)
from canopy_agent_runs.schemas import (
    Verdict as FwVerdict,
)

from apps.opps.parsers import (
    Decision as AceDecision,
)
from apps.opps.parsers import (
    JudgeVerdict,
    OppManifest,
    QAFailure,
    QAResult,
    StepManifest,
)
from apps.opps.sync import (
    ArtifactRef,
    OppSnapshot,
    RunDetail,
    StepSnapshot,
    _derive_phase_progress,
)
from apps.opps.sync import (
    RunSummary as AceRunSummary,
)

# Framework StepStatus (pending|running|complete|failed|skipped) → ace canonical
# StepManifest.status. ``failed`` is ambiguous (the framework collapsed both
# ``qa-failed`` and ``error`` into it); we disambiguate in ``map_step_snapshot``
# using the step's QA verdict, so it is intentionally absent here.
_FW_TO_ACE_STEP_STATUS: dict[str, str] = {
    "pending": "pending",
    "running": "running",
    "complete": "complete",
    "skipped": "skipped",
}


def _iso(value: dt.datetime | None) -> str | None:
    """Render a datetime as an ISO-8601 string with a ``Z`` UTC suffix, matching
    the string shape ace's serializers emit. ``None`` passes through."""
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# leaf mappers
# --------------------------------------------------------------------------- #
def map_artifact_ref(a: FwArtifact) -> ArtifactRef:
    """``canopy_agent_runs.Artifact`` → ``ArtifactRef``, field-for-field.

    The framework Artifact now carries the full Drive identity: ``ref`` is the
    opaque adapter handle (the Drive adapter sets it to the Drive file id) and
    ``path`` is the run-relative path. Both map straight across, so the file-id
    + path no longer need ace-side re-attribution.
    """
    return ArtifactRef(
        name=a.name,
        drive_file_id=a.ref or "",
        drive_web_link=a.url or "",
        size_bytes=a.size,
        mime_type=a.mime_type or "",
        path=a.path or "",
    )


def map_judge_verdict(v: FwVerdict | None) -> JudgeVerdict | None:
    """A framework ``kind="judge"`` Verdict → ``JudgeVerdict``."""
    if v is None:
        return None
    return JudgeVerdict(
        score=v.score,
        passed=v.passed,
        evaluated_at=_iso(v.evaluated_at),
        criteria=dict(v.criteria or {}),
        rationale=v.rationale or "",
    )


def map_qa_result(v: FwVerdict | None, *, target_skill: str) -> QAResult | None:
    """A framework ``kind="qa"`` Verdict → ``QAResult``.

    The framework QA verdict stores ``passed`` + a ``criteria`` dict
    (``checks_run`` / ``checks_passed`` / ``checks_failed`` / ``failures`` =
    list of check names) + a ``rationale`` (``"; ".join`` of failure details).
    The producing QA-skill name, per-failure ``type`` / ``auto_fix_hint``, and
    ``capture_path`` were NOT preserved by the framework schema:

      * ``skill`` (the QA skill) is reconstructed as ``"<target_skill>-qa"``.
      * each ``QAFailure.type`` defaults to ``"static"`` and ``auto_fix_hint``
        to ``""`` (unrecoverable).
      * ``capture_path`` is ``None``.
    """
    if v is None:
        return None
    crit = v.criteria or {}
    verdict = "pass" if v.passed is True else "fail" if v.passed is False else "incomplete"
    check_names = list(crit.get("failures") or [])
    details = [d.strip() for d in (v.rationale or "").split(";")] if v.rationale else []
    failures = [
        QAFailure(
            check=str(name),
            type="static",
            detail=(details[i] if i < len(details) else ""),
            auto_fix_hint="",
        )
        for i, name in enumerate(check_names)
    ]
    return QAResult(
        skill=f"{target_skill}-qa",
        target_skill=target_skill,
        verdict=verdict,
        ran_at=_iso(v.evaluated_at),
        capture_path=None,
        checks_run=int(crit.get("checks_run") or 0),
        checks_passed=int(crit.get("checks_passed") or 0),
        checks_failed=int(crit.get("checks_failed") or 0),
        failures=failures,
    )


def map_decision(d: FwDecision) -> AceDecision:
    """``canopy_agent_runs.Decision`` → ace parsers ``Decision``, field-for-field.

    The framework Decision now carries the full decisions-schema (ported from
    ACE), so every ace field maps straight across: ``skill`` ← ``step_key``,
    ``notes`` ← ``reasoning``, and ``id`` / ``phase`` / ``options_considered`` /
    ``source`` / ``override_reasoning`` / ``conflict_signals`` come directly off
    the framework Decision. No ace-side decisions re-load is needed.
    """
    return AceDecision(
        id=d.id,
        phase=d.phase,
        skill=d.step_key,
        question=d.question,
        ai_default=d.ai_default,
        override=d.override,
        options_considered=list(d.options_considered or []),
        source=d.source,
        status=d.status if d.status in ("ai-default", "overridden") else "ai-default",
        notes=d.reasoning or "",
        override_reasoning=d.override_reasoning,
        evidence_basis=d.evidence_basis or "stated",
        conflict_signals=list(d.conflict_signals or []),
    )


# --------------------------------------------------------------------------- #
# step mapper
# --------------------------------------------------------------------------- #
def map_step_snapshot(
    step: FwStep,
    artifacts: list[FwArtifact],
    verdicts: list[FwVerdict],
    *,
    folder_id: str = "",
    run_state: dict[str, Any] | None = None,
) -> StepSnapshot:
    """Reassemble one ace ``StepSnapshot`` from a framework ``Step`` plus the
    framework ``Artifact`` / ``Verdict`` rows that carry its ``step_key``.

    ``Step.title`` carries the phase (the ``DriveRunStore`` convention), so it
    maps to ``StepManifest.phase``.
    """
    key = step.key
    judge_fw = next((v for v in verdicts if v.kind == "judge"), None)
    qa_fw = next((v for v in verdicts if v.kind == "qa"), None)

    # Reverse the framework's lossy status forward-map. ``failed`` becomes
    # ``qa-failed`` when a failing QA verdict is attached, else ``error``.
    if step.status == "failed":
        status = "qa-failed" if (qa_fw is not None and qa_fw.passed is False) else "error"
    else:
        status = _FW_TO_ACE_STEP_STATUS.get(step.status, "pending")

    preview_stats = _step_preview_stats(run_state, key)

    manifest = StepManifest(
        skill_name=key,
        phase=step.title,
        ordinal=step.ordinal,
        status=status,
        started_at=_iso(step.started_at),
        completed_at=_iso(step.completed_at),
        error=step.error or None,
        preview_stats=preview_stats,
    )
    return StepSnapshot(
        step=manifest,
        judge=map_judge_verdict(judge_fw),
        artifacts=[map_artifact_ref(a) for a in artifacts],
        folder_id=folder_id,
        qa_result=map_qa_result(qa_fw, target_skill=key),
    )


def _step_preview_stats(run_state: dict[str, Any] | None, skill: str) -> dict:
    """Pull a per-step ``preview_stats`` block out of a parsed run_state.yaml.

    Walks the same ``phases -> [steps ->] <skill>`` shapes ace tolerates. Returns
    ``{}`` (the ace default) when run_state is absent or carries none.
    """
    if not isinstance(run_state, dict):
        return {}
    phases = run_state.get("phases")
    if not isinstance(phases, dict):
        return {}
    for phase_value in phases.values():
        if not isinstance(phase_value, dict):
            continue
        steps_map = phase_value.get("steps") if "steps" in phase_value else phase_value
        if not isinstance(steps_map, dict):
            continue
        sv = steps_map.get(skill)
        if isinstance(sv, dict):
            ps = sv.get("preview_stats")
            if isinstance(ps, dict):
                return dict(ps)
    return {}


# --------------------------------------------------------------------------- #
# run mapper
# --------------------------------------------------------------------------- #
def _group_by_step_key(rows: list, run: FwRun) -> dict[str, list]:
    out: dict[str, list] = {s.key: [] for s in run.steps}
    for r in rows:
        out.setdefault(r.step_key, []).append(r)
    return out


def map_run_detail(
    run: FwRun,
    *,
    folder_id: str = "",
    run_state: dict[str, Any] | None = None,
) -> RunDetail:
    """``canopy_agent_runs.Run`` → ace ``RunDetail`` (the full per-run snapshot)."""
    rs = run_state if isinstance(run_state, dict) else {}
    arts_by_step = _group_by_step_key(run.artifacts, run)
    verds_by_step = _group_by_step_key(run.verdicts, run)

    steps = [
        map_step_snapshot(
            s,
            arts_by_step.get(s.key, []),
            verds_by_step.get(s.key, []),
            folder_id=folder_id,
            run_state=run_state,
        )
        for s in run.steps
    ]
    decisions = [map_decision(d) for d in run.decisions]

    skill_versions = rs.get("skill_versions")
    return RunDetail(
        run_id=run.id,
        mode=run.mode,
        # Framework DERIVED status (legacy ace hardcoded "running" — see module docstring).
        status=run.status,
        started_at=_iso(run.created_at),
        completed_at=_iso(run.completed_at),
        current_phase=run.current_phase or None,
        current_step=run.current_step or None,
        skill_versions=dict(skill_versions) if isinstance(skill_versions, dict) else {},
        notes=str(rs.get("notes") or ""),
        steps=steps,
        folder_id=folder_id,
        decisions=decisions,
    )


def map_run_summary(
    rs_fw: FwRunSummary,
    *,
    folder_id: str = "",
    run_state: dict[str, Any] | None = None,
) -> AceRunSummary:
    """``canopy_agent_runs.RunSummary`` → ace ``RunSummary`` (one list-view row).

    Phase progress + last_actor are framework-absent; we derive/supplement them
    from the parsed ``run_state`` via ace's own ``_derive_phase_progress`` so the
    list view stays parity-exact with the legacy reader. When ``run_state`` is
    omitted the progress fields take their dataclass defaults (0 / None).
    """
    state = run_state if isinstance(run_state, dict) else {}
    progress = _derive_phase_progress(state, rs_fw.current_phase or None)
    return AceRunSummary(
        run_id=rs_fw.id,
        folder_id=folder_id,
        current_phase=rs_fw.current_phase or None,
        current_step=rs_fw.current_step or None,
        mode=rs_fw.mode,
        last_actor=state.get("last_actor"),
        last_actor_at=state.get("last_actor_at"),
        lifecycle_status=progress["status"],
        phases_total=progress["phases_total"],
        phases_done=progress["phases_done"],
        latest_phase_done=progress["latest_phase_done"],
    )


def map_opp_snapshot(
    run: FwRun,
    run_summaries: list[FwRunSummary] | None = None,
    *,
    opp_folder_id: str = "",
    run_folder_id: str = "",
    pdd_body: str = "",
    run_state: dict[str, Any] | None = None,
    run_state_by_id: dict[str, dict[str, Any]] | None = None,
    folder_id_by_run: dict[str, str] | None = None,
) -> OppSnapshot:
    """Assemble a full ``OppSnapshot`` from a framework ``Run`` (the selected
    run) plus the framework ``RunSummary`` list (the run selector).

    The Drive-identity + body fields the framework read model lacks are supplied
    by the caller: ``opp_folder_id`` (opp root), ``run_folder_id`` (selected
    run's folder), ``pdd_body``, and the per-run ``run_state`` /
    ``folder_id_by_run`` maps used to enrich the summary rows.
    """
    rs = run_state if isinstance(run_state, dict) else {}
    state_by_id = run_state_by_id or {}
    folder_by_run = folder_id_by_run or {}

    opp = OppManifest(
        slug=run.agent_slug,
        display_name=run.label or run.agent_slug,
        created_at=_iso(run.created_at),
        created_by=(rs.get("created_by") or rs.get("initiated_by")),
        labels=[],
        tags=[],
        current_run_id=run.id,
    )

    summaries = [
        map_run_summary(
            s,
            folder_id=folder_by_run.get(s.id, ""),
            run_state=state_by_id.get(s.id),
        )
        for s in (run_summaries or [])
    ]

    return OppSnapshot(
        opp=opp,
        pdd_body=pdd_body,
        opp_folder_id=opp_folder_id,
        current_run=map_run_detail(run, folder_id=run_folder_id, run_state=run_state),
        runs_summary=summaries,
    )
