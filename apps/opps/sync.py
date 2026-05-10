"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns an OppSnapshot suitable for JSON serialization.

Folder shape (the one the ACE plugin writes today):

    ACE/<slug>/idea.md                           (required)
    ACE/<slug>/pdd.md  or  idd.md                (optional; legacy name accepted)
    ACE/<slug>/opp.yaml                          (multi-run layout: opp-level metadata)
    ACE/<slug>/runs/<run-id>/run_state.yaml      (multi-run layout, current — written by /ace:run)
    ACE/<slug>/state.yaml                        (legacy flat layout, pre-0.11.3 rename)
    ACE/<slug>/<subfolder>/*                     (per skill, per manifest)
    ACE/<slug>/verdicts/<skill>-*.yaml           (LLM-as-Judge verdicts)

Per-opp step rows are synthesized from the dynamic skill registry in
``apps.opps.skills`` (loaded from plugin agent frontmatter). The
artifact manifest (`lib/artifact-manifest.ts` in the plugin) drives
file→skill attribution — each manifest entry declares which skill
produces a given path. Each opp is a single run; the ``run_id`` slot
always contains ``"r1"`` and exists only because the frontend payload
shape predates the drop-multi-run refactor.

See docs/plans/2026-04-20-drop-multi-run-simplify.md § deferred work.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from django.conf import settings

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.parsers import (
    Decision,
    JudgeVerdict,
    OppManifest,
    QAFailure,
    QAResult,
    StepManifest,
)

log = logging.getLogger(__name__)

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
    artifacts: list[ArtifactRef]
    folder_id: str
    qa_result: QAResult | None = None  # added in PR #146 (QA/Eval split)


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
    # Per-run decisions log (added with the decisions-log framework, May
    # 2026). Each row carries its own ``phase`` tag; the UI groups them
    # per phase. Empty list when the run predates the framework or hasn't
    # written ``decisions.yaml`` yet.
    decisions: list[Decision] = field(default_factory=list)


@dataclass
class OppSnapshot:
    opp: OppManifest
    pdd_body: str
    opp_folder_id: str
    current_run: RunDetail
    runs_summary: list[RunSummary] = field(default_factory=list)


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


def _find_state_file(files: list[DriveFile]) -> DriveFile | None:
    """Return the per-run state file from a folder listing.

    The plugin renamed ``state.yaml`` → ``run_state.yaml`` in 0.11.3 to make
    the per-run scope explicit (vs opp-level metadata in ``opp.yaml``). Some
    opps in Drive still carry the old name because the rename is only
    applied as opps are touched. Prefer ``run_state.yaml``; fall back to
    ``state.yaml`` for unmigrated opps.
    """
    return _find_child(files, "run_state.yaml") or _find_child(files, "state.yaml")


def _read_text(client: DriveClient, file: DriveFile) -> str:
    return client.get_content(file.id, file.mime_type).content


def _is_folder(f: DriveFile) -> bool:
    return f.mime_type == "application/vnd.google-apps.folder"


# --- Multi-run support ---


@dataclass
class RunSummary:
    """One row in the runs[] list — lightweight summary, no step iteration.

    Used by:
    - The opp page's run-selector (does not need full step detail).
    - The opp card on the list page (latest run only).
    """
    run_id: str
    folder_id: str
    current_phase: str | None
    current_step: str | None
    mode: str | None
    last_actor: str | None
    last_actor_at: str | None
    # Two-state model: a run is either in progress or complete. There's
    # no proactive "pause" — when the plugin stops between phases, halts
    # at a HITL gate, or sits idle after kickoff, it's all the same
    # conceptual state ("in_progress, just not actively executing right
    # now"). The frontend uses the phase-count fields below to render an
    # accurate "where is it?" label without needing more enum values.
    #
    # "in_progress" — anything that isn't fully complete (init, mid-step,
    #                 between phases, or halted-at-HITL).
    # "complete"    — every phase carries a done/complete status.
    # None          — no recognizable phases map (legacy / malformed);
    #                 the frontend falls back to the older
    #                 `!current_phase && last_actor_at` heuristic.
    lifecycle_status: str | None = None
    # Phase-level progress, derived from the phases map. Lets the
    # Hierarchy view render a "where is this run?" label like
    # "after design-review · 1/9" without re-fetching per-step state.
    phases_total: int = 0
    phases_done: int = 0
    latest_phase_done: str | None = None


def list_opp_runs(
    client: DriveClient,
    *,
    ace_root_folder_id: str,
    opp_slug: str,
    opp_children: list[DriveFile] | None = None,
) -> list[RunSummary]:
    """List runs under <opp>/runs/, newest-first by run-id (sorts as string).

    Returns empty list if the opp folder doesn't exist or has no runs/
    subfolder. Each RunSummary is loaded by reading state.yaml from the
    run folder.

    ``opp_children``: if the caller has already listed the opp folder, pass
    the result here to avoid a redundant Drive call.  When ``None``, the opp
    folder is re-listed via the ACE-root listing.
    """
    if opp_children is None:
        opp_folder = _find_child_folder(client.list_folder(ace_root_folder_id), opp_slug)
        if opp_folder is None:
            return []
        opp_children = client.list_folder(opp_folder.id)
    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is None:
        return []

    out: list[RunSummary] = []
    for child in client.list_folder(runs_folder.id):
        if not _is_folder(child):
            continue
        state_file = _find_state_file(client.list_folder(child.id))
        if state_file is None:
            continue
        try:
            body = _read_text(client, state_file)
            state = yaml.safe_load(body) or {}
        except (yaml.YAMLError, OSError) as exc:
            log.warning("list_opp_runs: failed to read %s: %s", state_file.id, exc)
            continue
        current_phase = state.get("phase") or state.get("current_phase")
        progress = _derive_phase_progress(state, current_phase)
        out.append(
            RunSummary(
                run_id=child.name,
                folder_id=child.id,
                current_phase=current_phase,
                current_step=state.get("step") or state.get("current_step"),
                mode=state.get("mode"),
                last_actor=state.get("last_actor"),
                last_actor_at=state.get("last_actor_at"),
                lifecycle_status=progress["status"],
                phases_total=progress["phases_total"],
                phases_done=progress["phases_done"],
                latest_phase_done=progress["latest_phase_done"],
            )
        )

    out.sort(key=lambda r: r.run_id, reverse=True)
    return out


# Status values the plugin uses for "this phase finished." Both shapes
# coexist across run_state.yaml versions: 1448 used "done", 2204 uses
# "complete". Treat both as terminal so we don't over-classify a run as
# "paused" just because the plugin upgraded its vocabulary.
_PHASE_DONE_STATUSES = frozenset({"done", "complete"})


def _derive_phase_progress(
    state: dict, current_phase: str | None,
) -> dict:
    """Compute lifecycle_status + phase counts + latest-done-phase.

    Two-state lifecycle: the run is either in_progress or complete.
    "Complete" requires every phase in the map to carry a done/complete
    status; anything else (no cursor + 0 phases done, mid-step with
    cursor, between phases, halted at a HITL gate) is in_progress.

    Returns a dict (not a dataclass) to keep the caller's construction
    simple. Phase order is taken from the YAML's insertion order, which
    is the plugin's authored phase order.
    """
    result = {
        "status": None,
        "phases_total": 0,
        "phases_done": 0,
        "latest_phase_done": None,
    }

    phases = state.get("phases")
    if not isinstance(phases, dict):
        # Legacy / malformed — the frontend falls back to its older
        # "no cursor + has activity" heuristic. We still report
        # "in_progress" if a top-level cursor is set, since that signal
        # is independent of the phases map.
        if current_phase:
            result["status"] = "in_progress"
        return result

    phases_total = 0
    phases_done = 0
    latest_phase_done: str | None = None
    has_pending = False

    for phase_name, phase_value in phases.items():
        if not isinstance(phase_value, dict):
            # Legacy shape: phase entry is a flat step-name → string map
            # (e.g. ``execution-management: {llo-onboarding: pending}``).
            # Treat those as pending phases so a run halted at the
            # phase-7-to-8 boundary isn't mis-flagged as complete.
            phases_total += 1
            has_pending = True
            continue

        phases_total += 1
        phase_status = phase_value.get("status")
        if phase_status in _PHASE_DONE_STATUSES:
            phases_done += 1
            latest_phase_done = phase_name
        else:
            # No status, "pending", or any other value: treat as not-done.
            has_pending = True

    result["phases_total"] = phases_total
    result["phases_done"] = phases_done
    result["latest_phase_done"] = latest_phase_done

    if phases_total > 0 and not has_pending:
        result["status"] = "complete"
    else:
        result["status"] = "in_progress"

    return result


# --- Manifest-driven skill attribution ---


_DATE_TOKEN = re.compile(r"YYYY-MM-DD")
_DATE_LITERAL = re.compile(r"\d{4}-\d{2}-\d{2}")


def _manifest_path_to_regex(path: str) -> re.Pattern[str]:
    """Convert a manifest path (possibly with YYYY-MM-DD placeholders) to a regex."""
    escaped = re.escape(path)
    escaped = escaped.replace(r"YYYY\-MM\-DD", r"\d{4}-\d{2}-\d{2}")
    return re.compile(rf"^{escaped}$")


def _artifact_matchers(artifacts: list[dict[str, Any]]) -> list[tuple[re.Pattern[str], str]]:
    """Build (regex, produced_by) pairs from the artifact manifest.

    ``produced_by`` == "external" entries are skipped (those are inputs,
    not skill outputs — e.g. ``idea.md``).
    """
    out: list[tuple[re.Pattern[str], str]] = []
    for art in artifacts:
        path = art.get("path") or ""
        producer = art.get("produced_by") or ""
        if not path or not producer or producer == "external":
            continue
        out.append((_manifest_path_to_regex(path), producer))
    return out


_FILENAME_PREFIX_RE = re.compile(r"^([a-z0-9][a-z0-9-]*?)(?:_|-eval[_.]|\.)")


def _attribute_files_to_skills(
    files: list[DriveFile],
    matchers: list[tuple[re.Pattern[str], str]],
    registered_skills: set[str] | None = None,
) -> dict[str, list[DriveFile]]:
    """Group Drive files by the skill that produces them.

    Primary path: each file's ``.path`` is matched against the
    plugin-declared manifest entries. The manifest is the source of
    truth.

    Fallback: when a file lives under a ``<N>-<phase>/`` folder and has
    a kebab-cased filename prefix that matches a registered skill (the
    plugin convention is ``<skill>_<role>.<ext>`` and
    ``<skill>-eval_verdict.<ext>``), attribute it to that skill anyway.
    This rescues files that the plugin writes but forgets to declare in
    the manifest — like ``app-release_summary.md``, observed in the
    wild — without dropping them silently.

    Files with no manifest match and no recognizable filename prefix
    are attributed to ``""`` so callers can surface them as
    "unclassified" if desired.
    """
    by_skill: dict[str, list[DriveFile]] = {}
    for f in files:
        if _is_folder(f):
            continue
        matched: str | None = None
        for pattern, producer in matchers:
            if pattern.match(f.path):
                matched = producer
                break
        if matched is None and registered_skills:
            matched = _filename_prefix_skill(f, registered_skills)
        key = matched or ""
        by_skill.setdefault(key, []).append(f)
    return by_skill


def _filename_prefix_skill(
    f: DriveFile, registered_skills: set[str]
) -> str | None:
    """Attribute a file via its ``<skill>_…`` or ``<skill>-eval_…`` prefix.

    Only fires for files under a phase-prefixed folder
    (``<N>-<phase>/…``) since that's where lifecycle skill outputs live;
    avoids false positives at the opp root or in shared subdirs.
    """
    # f.path looks like "2-commcare/app-release_summary.md" — require the
    # phase-prefixed parent.
    parts = f.path.split("/")
    if len(parts) < 2 or not re.match(r"^\d+-", parts[0]):
        return None
    name = parts[-1]
    m = _FILENAME_PREFIX_RE.match(name)
    if not m:
        return None
    candidate = m.group(1)
    if candidate in registered_skills:
        return candidate
    # Also try stripping `-eval` for verdict-style names like
    # `idea-to-pdd-eval_verdict.yaml` where the prefix is the eval skill.
    if candidate.endswith("-eval"):
        target = candidate[: -len("-eval")]
        if target in registered_skills:
            return target
    return None


def _drive_file_to_artifact_ref(f: DriveFile) -> ArtifactRef:
    return ArtifactRef(
        name=f.name,
        drive_file_id=f.id,
        drive_web_link=f.web_view_link,
        size_bytes=f.size_bytes,
        mime_type=f.mime_type,
        path=f.path,
    )


# --- Verdict extraction ---


# Two layouts are recognised because the plugin moved verdict files in
# 0.13.0 and again in 0.13.6:
#
#   Old (pre-0.13.0):  verdicts/<skill>[-quick|-deep|-monitor].yaml
#   New (0.13.0+):     <N>-<phase>/<producer>[-eval]_verdict[-<variant>]?.yaml
#
# `<producer>` is the producing skill from the manifest. For eval skills
# (named `<target>-eval`) we strip the suffix to attach the verdict to
# the target skill; for self-evaluating skills like `app-screenshot-capture`
# the producer IS the target.
_OLD_VERDICT_PATH_RE = re.compile(r"^verdicts/(?P<stem>[^/]+)\.ya?ml$")
_NEW_VERDICT_PATH_RE = re.compile(
    r"^[^/]+/(?P<producer>[^/]+?)_verdict(?P<variant>-[a-z]+)?\.ya?ml$"
)

# QA result files (added by ACE PR #146 / 0.13.88 — first migration is
# idea-to-pdd-qa). Filename convention: ``<phase>/<producer>-qa_result.yaml``
# where ``<producer>`` is the QA skill name (e.g. ``idea-to-pdd-qa``).
# QA is binary and structurally distinct from eval verdicts:
#   - No score / dimensions
#   - Verdict tier is pass | fail | incomplete
#   - Failures carry auto_fix_hints the orchestrator passes to producer
_QA_RESULT_PATH_RE = re.compile(
    r"^[^/]+/(?P<qa_skill>[^/]+?-qa)_result\.ya?ml$"
)


def _skill_from_verdict_stem(stem: str) -> str:
    """Derive skill name from an old-layout verdict filename stem.

    Examples:
      - "ocs-chatbot-eval-quick"   -> "ocs-chatbot-eval"
      - "ocs-chatbot-eval-deep"    -> "ocs-chatbot-eval"
      - "ocs-chatbot-eval-monitor" -> "ocs-chatbot-eval"
      - "opp-eval-deep"            -> "opp-eval"
      - "opp-eval-monitor"         -> "opp-eval"
      - "idea-to-pdd"              -> "idea-to-pdd"
    """
    for suffix in ("-quick", "-deep", "-monitor", "-shallow"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _skill_from_verdict_producer(
    producer: str, registered_skills: set[str]
) -> str | None:
    """Derive the target skill (lifecycle row) for a verdict-file producer.

    The plugin uses two conventions side-by-side:

      - Eval-suffix:  `<target>-eval` evaluates `<target>`. Strip the
        suffix, attach the verdict to `<target>`. Most common case.
      - Self-eval:    Some lifecycle skills (`ocs-chatbot-eval`,
        `app-ux-eval`, `opp-eval`) are themselves the workbench row
        and produce their own verdict files.

    The registered-skill set disambiguates: prefer attaching the verdict
    to whichever name is actually a row in the workbench. Returns None
    when neither candidate matches a known skill (we'd rather drop the
    verdict than attach it to a phantom row).
    """
    if producer in registered_skills:
        return producer
    if producer.endswith("-eval"):
        trimmed = producer[: -len("-eval")]
        if trimmed in registered_skills:
            return trimmed
    return None


_SCALE_RE = re.compile(r"^\s*0\s*-\s*(\d+(?:\.\d+)?)\s*$")


def _detect_score_scale(data: dict) -> float | None:
    """Pull the highest declared ``scale: "0-N"`` from a verdict YAML.

    Walks ``dimensions`` (the per-skill rubric output) and any top-level
    ``scale`` field. Returns the upper bound ``N`` as a float, or None if
    no explicit scale is present (callers fall back to a heuristic).
    """
    candidates: list[float] = []

    def _consume(value):
        if isinstance(value, str):
            m = _SCALE_RE.match(value)
            if m:
                try:
                    candidates.append(float(m.group(1)))
                except ValueError:
                    pass
        elif isinstance(value, (int, float)):
            candidates.append(float(value))

    top = data.get("scale")
    _consume(top)

    dims = data.get("dimensions")
    if isinstance(dims, dict):
        for v in dims.values():
            if isinstance(v, dict):
                _consume(v.get("scale"))

    if not candidates:
        return None
    return max(candidates)


def _parse_qa_result_yaml(body: str, qa_skill: str) -> QAResult | None:
    """Parse a QA result YAML body into a ``QAResult``.

    Schema canonical at ACE's ``lib/qa-types.ts`` (PR #146). Filename
    convention: ``<phase>/<producer>-qa_result.yaml`` where ``<producer>``
    is the QA skill (e.g. ``idea-to-pdd-qa``). The target lifecycle skill
    (``idea-to-pdd``) is the QA skill name with the ``-qa`` suffix stripped.
    """
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    verdict = str(data.get("verdict") or "").lower()
    if verdict not in ("pass", "fail", "incomplete"):
        return None

    target_skill = qa_skill[: -len("-qa")] if qa_skill.endswith("-qa") else qa_skill

    failures: list[QAFailure] = []
    raw_failures = data.get("failures") or []
    if isinstance(raw_failures, list):
        for entry in raw_failures:
            if not isinstance(entry, dict):
                continue
            failures.append(
                QAFailure(
                    check=str(entry.get("check") or ""),
                    type=str(entry.get("type") or "static"),
                    detail=str(entry.get("detail") or ""),
                    auto_fix_hint=str(entry.get("auto_fix_hint") or ""),
                )
            )

    stats = data.get("stats") or {}
    auto_fix = data.get("auto_fix") or {}

    return QAResult(
        skill=qa_skill,
        target_skill=target_skill,
        verdict=verdict,
        ran_at=str(data.get("ran_at")) if data.get("ran_at") else None,
        capture_path=str(data.get("capture_path")) if data.get("capture_path") else None,
        checks_run=int(stats.get("checks_run") or 0) if isinstance(stats, dict) else 0,
        checks_passed=int(stats.get("checks_passed") or 0) if isinstance(stats, dict) else 0,
        checks_failed=int(stats.get("checks_failed") or 0) if isinstance(stats, dict) else 0,
        failures=failures,
        auto_fix_attempted=auto_fix.get("attempted") if isinstance(auto_fix, dict) else None,
        auto_fix_attempts=auto_fix.get("attempts") if isinstance(auto_fix, dict) else None,
        auto_fix_succeeded=auto_fix.get("succeeded") if isinstance(auto_fix, dict) else None,
    )


def _load_decisions(
    client: DriveClient,
    run_files: list[DriveFile],
) -> list[Decision]:
    """Read ``decisions.yaml`` from the run-folder root and return rows.

    Single file at the run root (``ACE/<opp>/runs/<run-id>/decisions.yaml``);
    no per-phase split — each row carries its own ``phase`` tag. Schema
    canonical at ACE ``lib/decisions-schema.ts``. Returns an empty list
    when the file is missing or unparseable; consumers should treat
    "no decisions log" as a normal state for legacy runs that predate
    the framework.
    """
    file = _find_child(run_files, "decisions.yaml") or _find_child(run_files, "decisions.yml")
    if file is None or _is_folder(file):
        return []
    try:
        body = _read_text(client, file)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to read decisions.yaml: %s", exc)
        return []
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    raw_rows = data.get("decisions") or []
    if not isinstance(raw_rows, list):
        return []
    out: list[Decision] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        opts = row.get("options_considered") or []
        out.append(
            Decision(
                id=rid,
                phase=str(row.get("phase") or "").strip(),
                skill=str(row.get("skill") or "").strip(),
                question=str(row.get("question") or "").strip(),
                default=str(row.get("default") or "").strip(),
                options_considered=[str(o) for o in opts] if isinstance(opts, list) else [],
                source=str(row.get("source") or "").strip(),
                status=str(row.get("status") or "applied").strip().lower(),
                notes=str(row.get("notes") or "").strip(),
            )
        )
    return out


def _load_qa_results(
    client: DriveClient,
    opp_files: list[DriveFile],
) -> dict[str, QAResult]:
    """Walk the file tree for ``<phase>/<producer>-qa_result.yaml`` and
    return ``{target_skill: QAResult}``.

    Mirrors ``_load_verdicts`` but for QA results. Keyed on the *target*
    lifecycle skill (e.g. ``idea-to-pdd``), not the QA skill itself, so
    consumers can attach the QA result alongside the matching judge
    verdict on the same StepSnapshot.

    Multiple QA results per skill (re-runs after auto-fix) are coalesced
    by ``ran_at``: latest wins.
    """
    candidates: dict[str, tuple[str, QAResult]] = {}
    for f in opp_files:
        if _is_folder(f):
            continue
        match = _QA_RESULT_PATH_RE.match(f.path)
        if match is None:
            continue
        qa_skill = match.group("qa_skill")
        try:
            body = _read_text(client, f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to read QA result %s: %s", f.path, exc)
            continue
        result = _parse_qa_result_yaml(body, qa_skill)
        if result is None:
            continue
        ts = result.ran_at or ""
        existing = candidates.get(result.target_skill)
        if existing is None or ts > existing[0]:
            candidates[result.target_skill] = (ts, result)
    return {skill: r for skill, (_, r) in candidates.items()}


def _parse_verdict_yaml(body: str) -> JudgeVerdict | None:
    """Parse a verdict YAML body into a JudgeVerdict.

    Tolerant of both the old short shape ({score, passed, ...}) and the
    plugin's current eval shape ({overall_score, verdict, dimensions, ...}).

    Score is normalized to a 0-100 scale at parse time. The plugin emits
    scores on at least three scales (0-3 for ocs-chatbot-eval, 0-10 for
    most per-skill rubrics, 0-100 for opp-eval). When the verdict YAML
    declares an explicit scale (``dimensions.<key>.scale: "0-N"``) we use
    that; otherwise we fall back to a magnitude heuristic that's right for
    0-10 and 0-100 inputs but wrong for 0-3 — hence the explicit-scale
    preference.
    """
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    # Score: prefer explicit ``score``; otherwise ``overall_score``.
    score_raw = data.get("score")
    if score_raw is None:
        score_raw = data.get("overall_score")
    try:
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None

    if score is not None:
        scale_max = _detect_score_scale(data)
        if scale_max is not None and scale_max > 0:
            # Normalize to 0-100 here so downstream callers don't have to
            # carry the scale around. score=3 on 0-3 → 100; score=8.5 on
            # 0-10 → 85; score=87 on 0-100 → 87 (idempotent).
            score = (score / scale_max) * 100.0

    # Passed: explicit boolean, or derived from ``verdict``/``gate``.
    passed_raw = data.get("passed")
    if isinstance(passed_raw, bool):
        passed: bool | None = passed_raw
    else:
        verdict = str(data.get("verdict") or data.get("gate") or "").lower()
        if verdict in ("pass", "approved"):
            passed = True
        elif verdict in ("fail", "rejected"):
            passed = False
        else:
            passed = None

    evaluated_at = (
        data.get("evaluated_at")
        or data.get("ran_at")
        or data.get("timestamp")
    )

    # Criteria: pass through either the legacy ``criteria`` map or the
    # plugin's ``dimensions`` map.
    criteria_raw = data.get("criteria") or data.get("dimensions") or {}
    criteria = criteria_raw if isinstance(criteria_raw, dict) else {}

    rationale = data.get("rationale") or data.get("summary") or ""

    return JudgeVerdict(
        score=score,
        passed=passed,
        evaluated_at=evaluated_at,
        criteria=criteria,
        rationale=str(rationale),
    )


def _load_verdicts(
    client: DriveClient,
    opp_files: list[DriveFile],
    registered_skills: set[str] | None = None,
) -> dict[str, JudgeVerdict]:
    """Read every verdict YAML in the tree and return {skill_name: JudgeVerdict}.

    Two layouts are matched:

      - Old (pre-0.13.0): ``verdicts/<skill>[-variant].yaml``
      - New (0.13.0+):    ``<N>-<phase>/<producer>[-eval]_verdict[-variant].yaml``

    When multiple verdicts exist for one skill (e.g. quick + deep +
    monitor for ocs-chatbot-eval), keep the latest by ``evaluated_at``,
    with deep > monitor > shallow > quick as tiebreakers.

    ``registered_skills`` is the set of skill names that exist in the
    workbench (the lifecycle rows). Used to disambiguate eval-suffix vs
    self-eval producers; pass ``None`` to skip that check (every parsed
    producer is taken at face value, matching the legacy behaviour).
    """
    ranking = {"-deep": 4, "-monitor": 3, "-shallow": 2, "-quick": 1}

    def _variant_rank(path: str) -> int:
        for suffix, score in ranking.items():
            if suffix in path:
                return score
        return 0

    candidates: dict[str, tuple[int, str, JudgeVerdict]] = {}
    for f in opp_files:
        if _is_folder(f):
            continue
        skill: str | None = None
        old = _OLD_VERDICT_PATH_RE.match(f.path)
        if old is not None:
            skill = _skill_from_verdict_stem(old.group("stem"))
        else:
            new = _NEW_VERDICT_PATH_RE.match(f.path)
            if new is not None:
                producer = new.group("producer")
                if registered_skills is not None:
                    skill = _skill_from_verdict_producer(
                        producer, registered_skills
                    )
                else:
                    # Best-effort fallback when registry isn't passed.
                    skill = (
                        producer[: -len("-eval")]
                        if producer.endswith("-eval")
                        else producer
                    )
        if skill is None:
            continue
        try:
            body = _read_text(client, f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to read %s: %s", f.path, exc)
            continue
        verdict = _parse_verdict_yaml(body)
        if verdict is None:
            continue
        rank = _variant_rank(f.path)
        # PyYAML auto-parses ISO-8601 timestamps into datetime; older
        # verdicts may carry strings instead. Coerce to str so the
        # tiebreaker comparison below stays type-stable across the mix.
        ts = str(verdict.evaluated_at) if verdict.evaluated_at else ""
        existing = candidates.get(skill)
        if existing is None or (rank, ts) > (existing[0], existing[1]):
            candidates[skill] = (rank, ts, verdict)

    return {skill: v for skill, (_, _, v) in candidates.items()}


# --- Lean event aggregation (for the activity feed) ---


def list_opp_events_lean(
    client: DriveClient,
    *,
    ace_folder_id: str,
    slug: str,
) -> dict[str, JudgeVerdict]:
    """Fast verdict aggregation for the activity feed.

    Skips the expensive parts of ``load_opp``:
      - No recursive walk of the whole opp folder (saves the bulk of
        Drive API time — easily 5-15s per opp on cold cache)
      - No pdd.md read
      - No artifact-manifest attribution
      - No skill registry / system overview load

    Drive calls per opp:
      1. List ACE root (typically already done by caller; we re-list
         here for safety because the caller may pass a stale cache).
      2. List opp folder top-level (1 call).
      3. List ``verdicts/`` if present (1 call).
      4. Read each verdict YAML in that folder (N calls).

    Total: 3 + N. Compare with load_opp's ~30+ calls (the recursive
    walk dominates at depth-2+ trees).

    Returns ``{skill: JudgeVerdict}`` — same shape the activity feed
    consumes via ``_verdict_events_from_dict``.

    Multi-run aware: when the opp has a ``runs/`` subfolder (current
    ACE-plugin shape), reads ``verdicts/`` from the latest run instead
    of the opp root. Without this, new-layout opps silently produce
    empty timelines.
    """
    # 1. Locate the opp folder
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        return {}

    # 2. List opp folder top-level (NOT recursive)
    opp_children = client.list_files(opp_folder.id)

    # Multi-run layout: verdicts/ lives under runs/<latest>/. Pick the
    # newest run-folder by name (sorts as string — timestamp run-IDs are
    # lexicographically newest-first when reversed). Fall through to the
    # opp root if no usable run is found, matching the flat-layout behaviour.
    verdict_source_children: list[DriveFile] = opp_children
    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is not None:
        run_children = client.list_files(runs_folder.id)
        run_folders = sorted(
            (c for c in run_children if _is_folder(c)),
            key=lambda f: f.name, reverse=True,
        )
        for rf in run_folders:
            run_inner = client.list_files(rf.id)
            if _find_state_file(run_inner) is not None:
                verdict_source_children = run_inner
                break

    # 3. Find verdicts/ folder + list its contents
    verdicts_folder = _find_child_folder(verdict_source_children, "verdicts")
    verdict_files: list[DriveFile] = []
    if verdicts_folder is not None:
        # Set path on each so _load_verdicts' regex matches "verdicts/<stem>.yaml"
        children = client.list_files(verdicts_folder.id)
        for f in children:
            f.path = f"verdicts/{f.name}"
            verdict_files.append(f)

    # 4. Reuse existing _load_verdicts (parses + dedupes by skill).
    return _load_verdicts(client, verdict_files)


# --- opp.yaml helper ---


def _read_opp_yaml(client: DriveClient, opp_folder_id: str) -> dict:
    """Read and parse opp.yaml from the opp root folder. Returns {} if missing."""
    opp_children = client.list_folder(opp_folder_id)
    opp_yaml_file = _find_child(opp_children, "opp.yaml")
    if opp_yaml_file is None:
        return {}
    try:
        body = _read_text(client, opp_yaml_file)
        return yaml.safe_load(body) or {}
    except yaml.YAMLError as exc:
        log.warning("opp.yaml parse error for folder %s: %s", opp_folder_id, exc)
        return {}


# --- Main entry point ---


@dataclass
class OppCard:
    """Minimal opp snapshot for the /api/opps/ list.

    Populated from a bounded number of Drive calls per opp:
      - Folder listing (already performed by the caller for the signal
        check) — reused, no extra call.
      - ``state.yaml`` ``get_content`` (skipped when absent).
      - When (and only when) the opp has a ``verdicts/`` subfolder: one
        ``list_files`` of that folder plus one ``get_content`` for the
        highest-rank ``opp-eval-*.yaml`` (deep > monitor > quick).

    ``load_opp`` does ~6 calls per opp including a recursive tree scan
    and N verdict reads — too expensive for a list view.

    Note on ``status`` and ``last_activity_at``: ace-web has no live
    process signal — we only see what Drive shows us. ``status`` reports
    what we observed (``ok`` = state.yaml present and parsable; ``no-state``
    = no state.yaml; ``error`` set by callers when load failed). It does
    NOT claim "running"; the plugin may have exited hours ago.
    ``last_activity_at`` is state.yaml's Drive modifiedTime — the plugin
    updates state.yaml on every step transition, so this is the best
    cheap proxy for "when did anything happen here."
    """
    opp: OppManifest
    current_phase: str | None
    current_step: str | None
    status: str
    eval_score: float | None            # latest opp-eval overall_score (0-100), if any
    eval_passed: bool | None            # latest opp-eval verdict pass/fail, if any
    last_activity_at: str | None        # state.yaml modifiedTime (ISO-8601), if present
    run_count: int = 1                  # number of runs; legacy flat opps are always 1


def load_opp_card(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    opp_children: list[DriveFile],
) -> OppCard:
    """Read the subset of ``ACE/<slug>/`` needed for a list card.

    Handles three Drive layouts in one pass:

    1. **Flat** (pre-2026-05-02): ``state.yaml`` + ``idea.md`` at opp root,
       with ``verdicts/`` and per-skill subfolders alongside.
    2. **Legacy multi-run**: ``runs/run-001/state.yaml`` (older convention).
    3. **Multi-run with timestamp run IDs** (current ACE plugin shape):
       ``opp.yaml`` at root, ``runs/<YYYYMMDD-HHMM>/{state.yaml,verdicts/,...}``,
       and inputs/pdd.md as the canonical PDD source.

    ``opp_children`` is the caller-provided listing of the opp folder
    (they already fetched it to decide whether this folder is an opp),
    so we don't re-list. We only fetch the body of ``state.yaml`` /
    ``opp.yaml`` when they're present.
    """
    slug = opp_folder.name

    # opp.yaml at root carries multi-run-layout metadata (display_name,
    # created_at, created_by). Absent in flat-layout opps — safe no-op.
    opp_yaml_data: dict = {}
    if _find_child(opp_children, "opp.yaml") is not None:
        opp_yaml_data = _read_opp_yaml(client, opp_folder.id)

    # Locate state.yaml + the folder we'll search for verdicts/.
    # state.yaml lives next to verdicts/ — root for flat, run folder for
    # multi-run. Tracking both keeps _load_opp_eval_summary's reads on
    # the right children list.
    state_file: DriveFile | None = None
    state_source_children: list[DriveFile] = opp_children
    run_count = 1
    latest_run_name: str | None = None

    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is not None:
        run_children = client.list_files(runs_folder.id)
        run_folders = sorted(
            (c for c in run_children if _is_folder(c)),
            key=lambda f: f.name, reverse=True,
        )
        if run_folders:
            run_count = len(run_folders)
            # Try newest run first; fall through to older runs if newest
            # has no state.yaml (e.g. a half-initialized run dir).
            for rf in run_folders:
                run_inner = client.list_files(rf.id)
                sf = _find_state_file(run_inner)
                if sf is not None:
                    state_file = sf
                    state_source_children = run_inner
                    latest_run_name = rf.name
                    break

    if state_file is None:
        # Flat layout: state.yaml at opp root.
        state_file = _find_state_file(opp_children)
        if state_file is not None:
            state_source_children = opp_children

    state_data: dict = {}
    if state_file is not None:
        try:
            state_data = yaml.safe_load(_read_text(client, state_file)) or {}
        except yaml.YAMLError:
            log.warning("state.yaml for %s is not valid YAML", slug)

    # current_run_id: latest run-folder name when multi-run, "r1" when flat
    # (the synthesised single-run id the frontend payload still expects).
    current_run_id = latest_run_name or "r1"

    # display_name precedence: opp.yaml (multi-run) → state.yaml → slug.
    display_name = (
        opp_yaml_data.get("display_name")
        or state_data.get("display_name")
        or slug
    )
    created_at = (
        opp_yaml_data.get("created_at")
        or state_data.get("started_at")
        or state_data.get("created")
    )
    created_by = (
        opp_yaml_data.get("created_by")
        or state_data.get("created_by")
        or state_data.get("initiated_by")
    )

    opp_manifest = OppManifest(
        slug=slug,
        display_name=display_name,
        created_at=created_at,
        created_by=created_by,
        labels=[],
        current_run_id=current_run_id,
    )

    # opp-eval verdict — only fetched when the run/opp has a verdicts/
    # subfolder AND it contains an opp-eval-*.yaml.
    eval_score, eval_passed = _load_opp_eval_summary(client, state_source_children)

    # The plugin's state.yaml key names diverged between layouts:
    # flat opps use ``current_phase`` / ``current_step``; multi-run runs
    # use ``phase`` / ``step`` (matching ``list_opp_runs``). Accept both
    # so this card loader works regardless of which the plugin emits.
    return OppCard(
        opp=opp_manifest,
        current_phase=state_data.get("current_phase") or state_data.get("phase"),
        current_step=state_data.get("current_step") or state_data.get("step"),
        status="ok" if state_file is not None else "no-state",
        eval_score=eval_score,
        eval_passed=eval_passed,
        last_activity_at=state_file.modified_time if state_file is not None else None,
        run_count=run_count,
    )


def load_opp_card_by_slug(
    client: DriveClient, *, ace_folder_id: str, slug: str
) -> OppCard:
    """Locate ``ACE/<slug>/`` and return its OppCard.

    Convenience wrapper for callers that have a slug but not the
    pre-listed children (e.g. the compare endpoint). Raises
    FileNotFoundError when the opp folder doesn't exist.
    """
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")
    opp_children = client.list_files(opp_folder.id)
    return load_opp_card(client, opp_folder=opp_folder, opp_children=opp_children)


_OPP_EVAL_VARIANTS = ("opp-eval-deep.yaml", "opp-eval-monitor.yaml", "opp-eval-quick.yaml")


def _load_opp_eval_summary(
    client: DriveClient, opp_children: list[DriveFile]
) -> tuple[float | None, bool | None]:
    """Return (score, passed) from the opp's latest opp-eval verdict.

    Looks for ``verdicts/opp-eval-{deep,monitor,quick}.yaml`` in the
    opp's ``verdicts/`` subfolder, prefers deep over monitor over quick,
    parses the chosen file, and returns its score + pass/fail.

    Returns (None, None) when the opp has no verdicts/ folder or no
    matching opp-eval verdict. Drive errors / malformed YAML degrade
    silently — the list page should never 500 because of one bad file.
    """
    verdicts_folder = _find_child_folder(opp_children, "verdicts")
    if verdicts_folder is None:
        return (None, None)

    try:
        verdict_files = client.list_files(verdicts_folder.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to list verdicts/ for opp: %s", exc)
        return (None, None)

    # Pick highest-rank variant present.
    by_name = {f.name: f for f in verdict_files if not _is_folder(f)}
    chosen: DriveFile | None = None
    for variant in _OPP_EVAL_VARIANTS:
        if variant in by_name:
            chosen = by_name[variant]
            break
    if chosen is None:
        return (None, None)

    try:
        body = _read_text(client, chosen)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to read %s: %s", chosen.name, exc)
        return (None, None)

    verdict = _parse_verdict_yaml(body)
    if verdict is None:
        return (None, None)
    return (verdict.score, verdict.passed)


def load_opp(
    client: DriveClient,
    *,
    ace_folder_id: str | None = None,
    slug: str | None = None,
    ace_root_folder_id: str | None = None,
    opp_slug: str | None = None,
    run_id: str | None = None,
) -> OppSnapshot:
    """Load a full opp snapshot from ``ACE/<slug>/`` on Drive.

    Supports two calling conventions (both sets of kwargs are equivalent):

    **Legacy**::

        load_opp(client, ace_folder_id=<id>, slug=<slug>)

    **New** (multi-run-aware)::

        load_opp(client, ace_root_folder_id=<id>, opp_slug=<slug>)

    ``run_id`` is optional in both modes. When the opp folder has a
    ``runs/`` subfolder (v0.11.0+ multi-run layout), ``run_id`` selects a
    specific run; omitting it picks the newest. When no ``runs/`` subfolder
    exists (legacy flat layout), ``run_id`` is ignored and ``"r1"`` is used.

    Raises FileNotFoundError if the opp folder doesn't exist.
    """
    # Normalise the two kwarg variants.
    _ace_folder_id: str = ace_folder_id or ace_root_folder_id or ""
    _slug: str = slug or opp_slug or ""
    if not _ace_folder_id or not _slug:
        raise ValueError(
            "load_opp requires (ace_folder_id, slug) or (ace_root_folder_id, opp_slug)"
        )

    from apps.opps.skills import SKILL_REGISTRY
    from apps.system.reader import load_system_overview

    plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "") or ""
    overview = load_system_overview(plugin_path)

    # Locate the opp folder. Use list_folder (non-recursive) for the ACE root.
    ace_children = client.list_folder(_ace_folder_id)
    opp_folder = _find_child_folder(ace_children, _slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {_slug!r} under ACE/")

    opp_children = client.list_folder(opp_folder.id)
    runs_folder = _find_child_folder(opp_children, "runs")

    if runs_folder is not None:
        # Multi-run layout: dispatch through list_opp_runs to pick the target.
        # Pass opp_children to avoid re-listing the opp folder a second time.
        run_summaries = list_opp_runs(
            client,
            ace_root_folder_id=_ace_folder_id,
            opp_slug=_slug,
            opp_children=opp_children,
        )
        if not run_summaries:
            raise FileNotFoundError(
                f"opp {_slug!r} has runs/ subfolder but no runs inside"
            )
        if run_id is None:
            target = run_summaries[0]
        else:
            target = next((r for r in run_summaries if r.run_id == run_id), None)
            if target is None:
                raise FileNotFoundError(f"run {run_id!r} not found under opp {_slug!r}")

        return _load_opp_run(
            client,
            opp_folder=opp_folder,
            run_summary=target,
            run_summaries=run_summaries,
            skill_registry=SKILL_REGISTRY,
            overview=overview,
        )

    # Flat layout (no runs/ subfolder) — original reader path (uses list_files
    # for the recursive tree scan, which the real GoogleDriveClient supports).
    opp_children_via_list_files = client.list_files(opp_folder.id)
    return _load_opp_flat(
        client,
        opp_folder=opp_folder,
        opp_children=opp_children_via_list_files,
        slug=_slug,
        run_id=run_id,
        skill_registry=SKILL_REGISTRY,
        overview=overview,
    )


def _load_opp_flat(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    opp_children: list[DriveFile],
    slug: str,
    run_id: str | None,
    skill_registry,
    overview: dict,
) -> OppSnapshot:
    """Load an OppSnapshot from the legacy flat layout (state.yaml at opp root)."""
    # Single flat recursive listing of the opp folder — one round-trip.
    opp_tree = client.list_files(opp_folder.id, recursive=True)

    # state.yaml lives at root (new shape) or runs/run-001/ (legacy).
    state_file = _find_state_file(opp_children)
    if state_file is None:
        runs_folder = _find_child(opp_children, "runs")
        if runs_folder is not None and _is_folder(runs_folder):
            run_children = client.list_files(runs_folder.id)
            run1 = _find_child(run_children, "run-001")
            if run1 is not None and _is_folder(run1):
                state_file = _find_child(
                    client.list_files(run1.id), "state.yaml"
                )
    state_data: dict = {}
    if state_file is not None:
        raw = _read_text(client, state_file)
        try:
            state_data = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            log.warning("state.yaml for %s is not valid YAML", slug)
            state_data = {}

    # IDD→PDD rename transition: accept either primary-doc filename.
    pdd_file = _find_child(opp_children, "pdd.md") or _find_child(opp_children, "idd.md")
    pdd_body = _read_text(client, pdd_file) if pdd_file else ""

    matchers = _artifact_matchers(overview.get("artifacts") or [])
    files_by_skill = _attribute_files_to_skills(
        opp_tree, matchers,
        registered_skills={s.name for s in skill_registry},
    )

    artifacts_by_skill: dict[str, list[ArtifactRef]] = {
        skill: [_drive_file_to_artifact_ref(f) for f in files]
        for skill, files in files_by_skill.items()
        if skill
    }

    if pdd_file is not None and not any(
        a.name == pdd_file.name for a in artifacts_by_skill.get("idea-to-pdd", [])
    ):
        artifacts_by_skill.setdefault("idea-to-pdd", []).append(
            _drive_file_to_artifact_ref(pdd_file)
        )

    registered_skills = {s.name for s in skill_registry}
    verdicts_by_skill = _load_verdicts(client, opp_tree, registered_skills)
    qa_results_by_skill = _load_qa_results(client, opp_tree)
    decisions = _load_decisions(client, opp_tree)

    steps = _build_steps(
        skill_registry,
        artifacts_by_skill,
        verdicts_by_skill,
        opp_folder.id,
        qa_results_by_skill=qa_results_by_skill,
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
        decisions=decisions,
    )

    opp_manifest = OppManifest(
        slug=slug,
        display_name=state_data.get("display_name", slug),
        created_at=state_data.get("started_at") or state_data.get("created"),
        created_by=state_data.get("created_by") or state_data.get("initiated_by"),
        labels=[],
        current_run_id="r1",
    )

    return OppSnapshot(
        opp=opp_manifest,
        pdd_body=pdd_body,
        opp_folder_id=opp_folder.id,
        current_run=run_detail,
        runs_summary=[],
    )


def _load_opp_run(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    run_summary: RunSummary,
    run_summaries: list[RunSummary],
    skill_registry,
    overview: dict,
) -> OppSnapshot:
    """Load an OppSnapshot from a specific run in the multi-run layout."""
    run_folder_id = run_summary.folder_id
    slug = opp_folder.name

    # List the run folder's immediate children for state.yaml lookup.
    run_children = client.list_folder(run_folder_id)

    # state.yaml is already parsed into run_summary — just read for extra fields.
    state_file = _find_state_file(run_children)
    state_data: dict = {}
    if state_file is not None:
        try:
            state_data = yaml.safe_load(_read_text(client, state_file)) or {}
        except yaml.YAMLError:
            log.warning("state.yaml for run %s/%s is not valid YAML", slug, run_summary.run_id)

    # pdd.md / idea.md: prefer run folder, fall back to opp root inputs/.
    opp_folder_children = client.list_folder(opp_folder.id)
    pdd_file = (
        _find_child(run_children, "pdd.md")
        or _find_child(run_children, "idd.md")
        or _find_child(run_children, "idea.md")
    )
    if pdd_file is None:
        # Try inputs/ subfolder at opp root.
        inputs_folder = _find_child_folder(opp_folder_children, "inputs")
        if inputs_folder is not None:
            inputs_children = client.list_folder(inputs_folder.id)
            pdd_file = (
                _find_child(inputs_children, "pdd.md")
                or _find_child(inputs_children, "idea.md")
            )
    pdd_body = _read_text(client, pdd_file) if pdd_file else ""

    # Attribute run-folder files to skills via artifact manifest.
    # Must use recursive=True so files in skill subfolders (verdicts/, scorecards/,
    # app-summaries/, etc.) are included — without this every skill would appear
    # "pending" even after a complete run.
    run_tree = client.list_files(run_folder_id, recursive=True)
    matchers = _artifact_matchers(overview.get("artifacts") or [])
    files_by_skill = _attribute_files_to_skills(
        run_tree, matchers,
        registered_skills={s.name for s in skill_registry},
    )

    artifacts_by_skill: dict[str, list[ArtifactRef]] = {
        skill: [_drive_file_to_artifact_ref(f) for f in files]
        for skill, files in files_by_skill.items()
        if skill
    }

    if pdd_file is not None and not any(
        a.name == pdd_file.name for a in artifacts_by_skill.get("idea-to-pdd", [])
    ):
        artifacts_by_skill.setdefault("idea-to-pdd", []).append(
            _drive_file_to_artifact_ref(pdd_file)
        )

    registered_skills = {s.name for s in skill_registry}
    verdicts_by_skill = _load_verdicts(client, run_tree, registered_skills)
    qa_results_by_skill = _load_qa_results(client, run_tree)
    decisions = _load_decisions(client, run_tree)

    steps = _build_steps(
        skill_registry,
        artifacts_by_skill,
        verdicts_by_skill,
        run_folder_id,
        qa_results_by_skill=qa_results_by_skill,
    )

    # Read opp.yaml for display_name; fall back to state.yaml then slug.
    opp_data = _read_opp_yaml(client, opp_folder.id)
    display_name = opp_data.get("display_name") or state_data.get("display_name") or slug

    run_detail = RunDetail(
        run_id=run_summary.run_id,
        mode=run_summary.mode or state_data.get("mode", "review"),
        status="running",
        started_at=state_data.get("started_at"),
        completed_at=None,
        current_phase=run_summary.current_phase,
        current_step=run_summary.current_step,
        skill_versions={},
        notes="",
        steps=steps,
        folder_id=run_folder_id,
        decisions=decisions,
    )

    opp_manifest = OppManifest(
        slug=slug,
        display_name=display_name,
        created_at=opp_data.get("created_at") or state_data.get("started_at"),
        created_by=opp_data.get("created_by") or state_data.get("initiated_by"),
        labels=[],
        current_run_id=run_summary.run_id,
    )

    return OppSnapshot(
        opp=opp_manifest,
        pdd_body=pdd_body,
        opp_folder_id=opp_folder.id,
        current_run=run_detail,
        runs_summary=run_summaries,
    )


def _build_steps(
    skill_registry,
    artifacts_by_skill: dict[str, list[ArtifactRef]],
    verdicts_by_skill: dict[str, JudgeVerdict],
    folder_id: str,
    qa_results_by_skill: dict[str, QAResult] | None = None,
) -> list[StepSnapshot]:
    """Synthesize StepSnapshot rows from the skill registry + Drive data."""
    qa_results_by_skill = qa_results_by_skill or {}
    steps: list[StepSnapshot] = []
    for skill_meta in skill_registry:
        artifacts = artifacts_by_skill.get(skill_meta.name, [])
        qa_result = qa_results_by_skill.get(skill_meta.name)
        if qa_result is not None and qa_result.verdict == "fail":
            # QA failed irrecoverably; eval was skipped.
            # Surface as a distinct status so the UI can show the
            # auto-fix attempts + remaining failures.
            status = "qa-failed"
        elif artifacts:
            status = "complete"
        else:
            status = "pending"

        step_manifest = StepManifest(
            skill_name=skill_meta.name,
            phase=skill_meta.phase,
            ordinal=skill_meta.ordinal,
            status=status,
        )
        steps.append(
            StepSnapshot(
                step=step_manifest,
                judge=verdicts_by_skill.get(skill_meta.name),
                artifacts=artifacts,
                folder_id=folder_id,
                qa_result=qa_result,
            )
        )
    return steps


@dataclass
class ScorecardSnapshot:
    """Run-level opp-eval summary: latest verdict + latest scorecard + trend.

    Produced by the plugin's ``opp-eval`` umbrella skill. Lives on the
    Workbench header as the "improvement loop" surface:

        verdicts/opp-eval-{deep,monitor}.yaml   → latest_verdict
        scorecards/YYYY-MM-DD-opp-eval-*.md     → latest_scorecard (newest)
        scorecards/trend.md                     → trend
    """
    latest_verdict: JudgeVerdict | None
    latest_verdict_variant: str | None          # "deep" | "monitor" | "quick"
    latest_scorecard_path: str | None
    latest_scorecard_body: str
    trend_path: str | None
    trend_body: str


_SCORECARD_FILE_RE = re.compile(
    r"^scorecards/(\d{4}-\d{2}-\d{2})-opp-eval-(?P<variant>quick|deep|monitor)\.md$"
)
_OPP_EVAL_VERDICT_RE = re.compile(
    r"^verdicts/opp-eval-(?P<variant>quick|deep|monitor)\.ya?ml$"
)


def load_scorecard(
    client: DriveClient, *, ace_folder_id: str, slug: str
) -> ScorecardSnapshot:
    """Load the latest opp-eval scorecard, verdict, and trend for an opp.

    Returns an all-empty ScorecardSnapshot if the opp has no ``scorecards/``
    or ``verdicts/`` content yet (opp-eval is ad-hoc, not part of the
    default 6-phase pipeline).

    Raises FileNotFoundError if the opp folder itself doesn't exist.
    """
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")

    tree = client.list_files(opp_folder.id, recursive=True)

    # --- latest verdict ------------------------------------------------
    # deep > monitor > quick for tiebreak; otherwise newest evaluated_at.
    variant_rank = {"deep": 3, "monitor": 2, "quick": 1}
    best: tuple[int, str, JudgeVerdict, str] | None = None
    for f in tree:
        if _is_folder(f):
            continue
        m = _OPP_EVAL_VERDICT_RE.match(f.path)
        if not m:
            continue
        variant = m.group("variant")
        try:
            body = _read_text(client, f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to read %s: %s", f.path, exc)
            continue
        verdict = _parse_verdict_yaml(body)
        if verdict is None:
            continue
        rank = variant_rank.get(variant, 0)
        ts = verdict.evaluated_at or ""
        if best is None or (rank, ts) > (best[0], best[1]):
            best = (rank, ts, verdict, variant)

    # --- latest scorecard ---------------------------------------------
    scorecards: list[tuple[str, str, DriveFile]] = []
    for f in tree:
        if _is_folder(f):
            continue
        m = _SCORECARD_FILE_RE.match(f.path)
        if m:
            scorecards.append((m.group(1), m.group("variant"), f))
    # newest date wins; deep > monitor > quick on ties
    scorecards.sort(
        key=lambda t: (t[0], variant_rank.get(t[1], 0)), reverse=True
    )
    sc_path: str | None = None
    sc_body: str = ""
    if scorecards:
        _, _, f = scorecards[0]
        sc_path = f.path
        try:
            sc_body = _read_text(client, f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to read %s: %s", f.path, exc)

    # --- trend --------------------------------------------------------
    trend_path: str | None = None
    trend_body = ""
    for f in tree:
        if not _is_folder(f) and f.path == "scorecards/trend.md":
            trend_path = f.path
            try:
                trend_body = _read_text(client, f)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to read %s: %s", f.path, exc)
            break

    if best is None:
        return ScorecardSnapshot(
            latest_verdict=None,
            latest_verdict_variant=None,
            latest_scorecard_path=sc_path,
            latest_scorecard_body=sc_body,
            trend_path=trend_path,
            trend_body=trend_body,
        )
    _, _, verdict, variant = best
    return ScorecardSnapshot(
        latest_verdict=verdict,
        latest_verdict_variant=variant,
        latest_scorecard_path=sc_path,
        latest_scorecard_body=sc_body,
        trend_path=trend_path,
        trend_body=trend_body,
    )


def delete_opp_folder(client: DriveClient, *, ace_folder_id: str, slug: str) -> None:
    """Trash the `ACE/<slug>/` folder. Raises FileNotFoundError if missing."""
    for child in client.list_files(ace_folder_id):
        if child.name == slug and child.mime_type == "application/vnd.google-apps.folder":
            client.trash_folder(child.id)
            return
    raise FileNotFoundError(f"no opp folder named {slug!r} under ACE root")


def delete_run_folder(
    client: DriveClient,
    *,
    ace_folder_id: str,
    opp_slug: str,
    run_id: str,
) -> None:
    """Trash a single run subfolder at ``ACE/<opp_slug>/runs/<run_id>/``.

    Lets operators clean up old / failed / experimental runs without
    nuking the whole opp. Drive trash is 30-day recoverable.

    Raises FileNotFoundError if the opp folder, runs/ subfolder, or the
    specific run subfolder doesn't exist. The caller decides whether to
    surface that as 404 (run never existed) or treat it as already-deleted.
    """
    opp_folder = _find_child_folder(client.list_files(ace_folder_id), opp_slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {opp_slug!r}")
    runs_folder = _find_child_folder(client.list_files(opp_folder.id), "runs")
    if runs_folder is None:
        raise FileNotFoundError(f"opp {opp_slug!r} has no runs/ subfolder")
    run_folder = _find_child_folder(client.list_files(runs_folder.id), run_id)
    if run_folder is None:
        raise FileNotFoundError(
            f"no run named {run_id!r} under {opp_slug!r}"
        )
    client.trash_folder(run_folder.id)
