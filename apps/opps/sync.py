"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns an OppSnapshot suitable for JSON serialization.

Folder shape (the one the ACE plugin writes today):

    ACE/<slug>/idea.md                           (required)
    ACE/<slug>/pdd.md  or  idd.md                (optional; legacy name accepted)
    ACE/<slug>/opp.yaml                          (multi-run layout: opp-level metadata)
    ACE/<slug>/runs/<run-id>/run_state.yaml      (multi-run layout, current — written by /ace:run)
    ACE/<slug>/run_state.yaml                    (flat layout, single-run)
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

import yaml
from django.conf import settings

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.parsers import (
    Decision,
    JudgeVerdict,
    OppManifest,
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
    # Durable overrides from <opp>/inputs/decision-overrides.yaml keyed by
    # row_id (see apps/opps/decision_overrides.py). Kept fresh on cache
    # hits by the saved_overrides freshness overlay — the file lives in a
    # listing the Drive Changes API doesn't reliably invalidate.
    saved_overrides: dict[str, dict] = field(default_factory=dict)


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
    """Return the per-run state file from a folder listing."""
    return _find_child(files, "run_state.yaml")


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
    # Per-phase status in authored order: [{ordinal, name, status}]. Powers
    # the cross-run strip's per-phase segments; a count alone cannot show a
    # run that errored mid-way and then recovered.
    phase_states: list[dict] = field(default_factory=list)


def list_opp_runs(
    client: DriveClient,
    *,
    ace_root_folder_id: str,
    opp_slug: str,
    opp_children: list[DriveFile] | None = None,
) -> list[RunSummary]:
    """List runs under <opp>/runs/, newest-first by run-id (sorts as string).

    Returns empty list if the opp folder doesn't exist or has no runs/
    subfolder. Each RunSummary is loaded by reading run_state.yaml from the
    run folder. Run folders without run_state.yaml are skipped.

    ``opp_children``: if the caller has already listed the opp folder, pass
    the result here to avoid a redundant Drive call.  When ``None``, the opp
    folder is re-listed via the ACE-root listing.
    """
    # Resolve the opp folder (the store is rooted at it). When opp_children was
    # supplied we still need the opp folder id, which Drive listings don't carry
    # as a back-pointer — so re-resolve from the ACE root (cheap + cached).
    opp_folder = _find_child_folder(client.list_folder(ace_root_folder_id), opp_slug)
    if opp_folder is None:
        return []
    if opp_children is None:
        opp_children = client.list_folder(opp_folder.id)
    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is None:
        return []

    # Wave-4 reader swap: the per-run summaries are sourced from the framework's
    # DriveRunStore and mapped back onto ace's RunSummary via framework_map.
    from apps.opps import framework_reader
    from apps.opps.skills import SKILL_REGISTRY
    from apps.system.reader import load_system_overview

    overview = load_system_overview(getattr(settings, "ACE_PLUGIN_PATH", "") or "")
    return framework_reader.runs_summary_via_store(
        client,
        opp_folder=opp_folder,
        runs_folder=runs_folder,
        slug=opp_slug,
        overview=overview,
        skill_registry=list(SKILL_REGISTRY),
    )


# What the plugin considers a "still pending" phase or step. Anything
# NOT in this set (and not absent / empty) counts as "done enough" — we
# accept the variety of terminal status strings the plugin emits across
# versions: "done", "complete", "pass", "skipped", "skipped-by-design",
# "proceed-with-warn", etc. Whitelisting "done" alone made 2128 (which
# uses bare per-step strings like ``idea-to-pdd: done`` directly under
# the phase, no ``status:`` key) read as zero progress and label every
# completed older run as "queued".
_PENDING_STATUSES = frozenset({"pending", "", None})


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
        # Per-phase status, in authored order. `phases_done` is a COUNT, which
        # cannot express a run that cleared phases 1-5, errored in 6 and then
        # completed 7 — a real shape in the record. The cross-run strip renders
        # one segment per phase off this list. Derived inside the existing loop
        # below, so it costs no extra Drive read and no extra parse.
        "phase_states": [],
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
    phase_states: list[dict] = []

    def _record(name: str, status: str) -> None:
        phase_states.append({
            "ordinal": len(phase_states) + 1,
            "name": name,
            "status": status,
        })

    for phase_name, phase_value in phases.items():
        if not isinstance(phase_value, dict):
            # Phase entry is a non-dict (e.g. a bare string). Treat as
            # pending so we don't false-positive a missing-data row as
            # complete.
            phases_total += 1
            has_pending = True
            _record(phase_name, "pending")
            continue

        phases_total += 1

        # Phase shape A — current plugin: explicit ``status:`` field.
        #   design-review:
        #     status: complete
        #     steps: {...}
        explicit_status = phase_value.get("status")
        if explicit_status is not None:
            if explicit_status in _PENDING_STATUSES:
                has_pending = True
            else:
                phases_done += 1
                latest_phase_done = phase_name
            # Keep the AUTHORED status verbatim rather than collapsing to
            # done/pending — `error`, `blocked`, `skipped` and `in_progress`
            # are the whole point of the per-phase strip.
            _record(phase_name, str(explicit_status))
            continue

        # Phase shape B — older plugin: bare step-name → status-string
        # under the phase (no ``status:`` field, no ``steps:`` wrapper).
        #   design-review:
        #     idea-to-pdd: done
        #     pdd-to-test-prompts: done
        # Or shape C — newer-plugin variant where ``status:`` is omitted
        # but ``steps:`` is present. Treat steps the same way: phase is
        # done iff every step has a non-pending status.
        steps_map = phase_value.get("steps") if "steps" in phase_value else phase_value
        if isinstance(steps_map, dict) and steps_map:
            any_pending_step = any(
                _is_pending_step(v) for v in steps_map.values()
            )
            if any_pending_step:
                has_pending = True
                _record(phase_name, "in_progress" if any(
                    not _is_pending_step(v) for v in steps_map.values()
                ) else "pending")
            else:
                phases_done += 1
                latest_phase_done = phase_name
                _record(phase_name, "done")
        else:
            # Empty / unparseable phase block — conservatively pending.
            has_pending = True
            _record(phase_name, "pending")

    result["phases_total"] = phases_total
    result["phases_done"] = phases_done
    result["latest_phase_done"] = latest_phase_done
    result["phase_states"] = phase_states

    if phases_total > 0 and not has_pending:
        result["status"] = "complete"
    else:
        result["status"] = "in_progress"

    return result


def _is_pending_step(step_value) -> bool:
    """Return True iff this step value reads as not-yet-done.

    Step shapes vary: a bare string (``idea-to-pdd: done``) or a dict
    with ``status:`` (``idea-to-pdd: {status: done, verdict: pass}``).
    A step with no recognizable status is considered pending so we
    don't over-claim progress on malformed entries.
    """
    if isinstance(step_value, str):
        return step_value in _PENDING_STATUSES
    if isinstance(step_value, dict):
        status = step_value.get("status")
        return status in _PENDING_STATUSES
    return True


# --- Manifest-driven skill attribution ---
#
# Artifact attribution (manifest matchers + filename-prefix fallback +
# DriveFile→ArtifactRef) was removed in the wave-4 single-reader swap. The
# framework ``canopy_agent_runs.drive.store.DriveRunStore`` now owns attribution and
# surfaces each Artifact's Drive id (``ref``) + run-relative ``path`` directly,
# so ace no longer re-attributes files (see ``apps/opps/framework_map`` +
# ``apps/opps/framework_reader``).


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


# decisions.yaml loading/parsing (``_load_decisions`` + ``_extract_decision_rows``
# + ``_parse_decision_rows``) was removed in the wave-4 single-reader swap. The
# framework ``canopy_agent_runs.drive.store.DriveRunStore`` ported ACE's full
# decisions-schema and surfaces each Decision row (id / phase /
# options_considered / source / override_reasoning / conflict_signals included)
# directly; ace maps it straight across in ``apps/opps/framework_map`` rather
# than re-reading decisions.yaml a second time.


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
      - ``run_state.yaml`` ``get_content`` (skipped when absent).
      - When (and only when) the opp has a ``verdicts/`` subfolder: one
        ``list_files`` of that folder plus one ``get_content`` for the
        highest-rank ``opp-eval-*.yaml`` (deep > monitor > quick).

    ``load_opp`` does ~6 calls per opp including a recursive tree scan
    and N verdict reads — too expensive for a list view.

    Note on ``status`` and ``last_activity_at``: ace-web has no live
    process signal — we only see what Drive shows us. ``status`` reports
    what we observed (``ok`` = run_state.yaml present and parsable;
    ``no-state`` = no run_state.yaml; ``error`` set by callers when load
    failed). It does NOT claim "running"; the plugin may have exited hours
    ago. ``last_activity_at`` is run_state.yaml's Drive modifiedTime — the
    plugin updates run_state.yaml on every step transition, so this is the
    best cheap proxy for "when did anything happen here."
    """
    opp: OppManifest
    current_phase: str | None
    current_step: str | None
    status: str
    eval_score: float | None            # latest opp-eval overall_score (0-100), if any
    eval_passed: bool | None            # latest opp-eval verdict pass/fail, if any
    last_activity_at: str | None        # run_state.yaml modifiedTime (ISO-8601), if present
    run_count: int = 1                  # number of runs; flat-layout opps are always 1
    # Lightweight per-run rows so the Opps-list page can render the
    # phase-chip strip without each card firing a /opps/<slug>/runs call.
    # Newest-first (same order as list_opp_runs). Empty for flat-layout
    # opps that have no runs/ subfolder. Lives on the card cache; the
    # Drive Changes API invalidates the card when any run's state.yaml
    # changes. See #512.
    runs_summary: list[RunSummary] = field(default_factory=list)


def load_opp_card(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    opp_children: list[DriveFile],
) -> OppCard:
    """Read the subset of ``ACE/<slug>/`` needed for a list card.

    Handles two Drive layouts in one pass:

    1. **Flat**: ``run_state.yaml`` + ``idea.md`` at opp root, with
       ``verdicts/`` and per-skill subfolders alongside.
    2. **Multi-run** (current ACE plugin shape): ``opp.yaml`` at root,
       ``runs/<YYYYMMDD-HHMM>/{run_state.yaml,verdicts/,...}``, and
       inputs/pdd.md as the canonical PDD source.

    ``opp_children`` is the caller-provided listing of the opp folder
    (they already fetched it to decide whether this folder is an opp),
    so we don't re-list. We only fetch the body of ``run_state.yaml`` /
    ``opp.yaml`` when they're present.
    """
    slug = opp_folder.name

    # Wave-4 reader swap: the per-run summaries on the card are sourced from the
    # framework's DriveRunStore (via framework_reader). The card's ace-specific
    # surface (eval score, last_activity, status, run_count, opp manifest) stays
    # ace-side — those have no framework read-model source.
    from apps.opps import framework_reader
    from apps.opps.skills import SKILL_REGISTRY
    from apps.system.reader import load_system_overview

    _overview = load_system_overview(getattr(settings, "ACE_PLUGIN_PATH", "") or "")
    _registry = list(SKILL_REGISTRY)

    # opp.yaml at root carries multi-run-layout metadata (display_name,
    # created_at, created_by). Absent in flat-layout opps — safe no-op.
    opp_yaml_data: dict = {}
    if _find_child(opp_children, "opp.yaml") is not None:
        opp_yaml_data = _read_opp_yaml(client, opp_folder.id)

    # Locate run_state.yaml + the folder we'll search for verdicts/.
    # run_state.yaml lives next to verdicts/ — root for flat, run folder
    # for multi-run. Tracking both keeps _load_opp_eval_summary's reads on
    # the right children list.
    state_file: DriveFile | None = None
    state_source_children: list[DriveFile] = opp_children
    run_count = 1
    latest_run_name: str | None = None
    runs_summary: list[RunSummary] = []

    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is not None:
        # The store sources the per-run summaries (newest-first by run-id) and
        # the run definition (only folders carrying run_state.yaml count) — the
        # half-initialized / partially-deleted run folders the legacy loop
        # filtered out are filtered the same way by the store.
        runs_summary = framework_reader.runs_summary_via_store(
            client,
            opp_folder=opp_folder,
            runs_folder=runs_folder,
            slug=slug,
            overview=_overview,
            skill_registry=_registry,
        )
        run_count = len(runs_summary)
        if runs_summary:
            latest = runs_summary[0]
            latest_run_name = latest.run_id
            # The latest run's children back the opp-eval read + last_activity.
            state_source_children = client.list_folder(latest.folder_id)
            state_file = _find_state_file(state_source_children)

    if state_file is None:
        # Flat layout: run_state.yaml at opp root.
        state_file = _find_state_file(opp_children)
        if state_file is not None:
            state_source_children = opp_children

    state_data: dict = {}
    if state_file is not None:
        try:
            state_data = yaml.safe_load(_read_text(client, state_file)) or {}
        except yaml.YAMLError:
            log.warning("run_state.yaml for %s is not valid YAML", slug)

    # current_run_id: latest run-folder name when multi-run, "r1" when flat
    # (the synthesised single-run id the frontend payload still expects).
    current_run_id = latest_run_name or "r1"

    # display_name precedence: opp.yaml (multi-run) → run_state.yaml → slug.
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

    # Flat-layout fallback: no runs/ subfolder but the opp has its own
    # run_state.yaml at the root. Synthesise a single RunSummary (sourced from
    # the store via the flat synthetic-run adapter) so the Opps-list strip can
    # still render a chip on those opps.
    if not runs_summary and runs_folder is None and state_data:
        runs_summary = framework_reader.flat_runs_summary_via_store(
            client,
            opp_folder=opp_folder,
            slug=slug,
            overview=_overview,
            skill_registry=_registry,
        )

    return OppCard(
        opp=opp_manifest,
        current_phase=state_data.get("current_phase") or state_data.get("phase"),
        current_step=state_data.get("current_step") or state_data.get("step"),
        status="ok" if state_file is not None else "no-state",
        eval_score=eval_score,
        eval_passed=eval_passed,
        last_activity_at=state_file.modified_time if state_file is not None else None,
        run_count=run_count,
        runs_summary=runs_summary,
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

    # Wave-4 reader swap: the read engine is now the framework's DriveRunStore
    # (via apps.opps.framework_reader), mapped back onto the ace dataclasses by
    # framework_map. Signatures + return types are unchanged; only the engine
    # underneath moved. See framework_reader's module docstring.
    from apps.opps import framework_reader

    registry = list(SKILL_REGISTRY)

    if runs_folder is not None:
        # Multi-run layout: the store sources the run set + per-run summaries.
        run_summaries = framework_reader.runs_summary_via_store(
            client,
            opp_folder=opp_folder,
            runs_folder=runs_folder,
            slug=_slug,
            overview=overview,
            skill_registry=registry,
        )
        if not run_summaries:
            # "Multi-run layout but runs/ is empty" is a valid state — the
            # opp was created (has idea.md / pdd.md) but /ace:run hasn't
            # produced its first run yet. Fall through to the flat path so
            # we synthesise a placeholder RunDetail from whatever's at the
            # opp root. Result: an empty Workbench with a "no runs yet"
            # affordance instead of a 404 page.
            return framework_reader.load_opp_flat_via_store(
                client,
                opp_folder=opp_folder,
                slug=_slug,
                overview=overview,
                skill_registry=registry,
            )
        return framework_reader.load_opp_run_via_store(
            client,
            opp_folder=opp_folder,
            run_id=run_id,
            runs_summary=run_summaries,
            slug=_slug,
            overview=overview,
            skill_registry=registry,
        )

    # Flat layout (no runs/ subfolder): present the opp folder to the store as
    # a single synthetic run.
    return framework_reader.load_opp_flat_via_store(
        client,
        opp_folder=opp_folder,
        slug=_slug,
        overview=overview,
        skill_registry=registry,
    )


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


_EMPTY_SCORECARD = ScorecardSnapshot(
    latest_verdict=None,
    latest_verdict_variant=None,
    latest_scorecard_path=None,
    latest_scorecard_body="",
    trend_path=None,
    trend_body="",
)


def load_scorecard(
    client: DriveClient, *, ace_folder_id: str, slug: str
) -> ScorecardSnapshot:
    """Load the latest opp-eval scorecard, verdict, and trend for an opp.

    Returns an all-empty ScorecardSnapshot if the opp has no ``scorecards/``
    or ``verdicts/`` content yet (opp-eval is ad-hoc, not part of the
    default 6-phase pipeline).

    Raises FileNotFoundError if the opp folder itself doesn't exist.

    Fast-path (issue #467): the opp-eval scorecard + verdict + trend files
    all live at the opp root under ``scorecards/`` and ``verdicts/``.
    Walking the entire opp tree (``runs/*`` included) just to find them is
    5-12s on a real opp and returns null for the common case. Instead, list
    the opp's immediate children first; if neither subfolder exists, return
    an empty snapshot without recursing. Otherwise list only those two
    subfolders.
    """
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")

    opp_children = client.list_files(opp_folder.id)
    scorecards_folder = _find_child_folder(opp_children, "scorecards")
    verdicts_folder = _find_child_folder(opp_children, "verdicts")

    if scorecards_folder is None and verdicts_folder is None:
        # Fast path: no opp-eval artifacts at the opp root. Don't recurse
        # the rest of the tree (which can be hundreds of files under runs/).
        return _EMPTY_SCORECARD

    # Build a path-prefixed listing of only the scorecard + verdict folders,
    # mirroring the path shape the regex patterns expect ("scorecards/..."
    # and "verdicts/...").
    tree: list[DriveFile] = []
    if verdicts_folder is not None:
        for f in client.list_files(verdicts_folder.id, recursive=True):
            tree.append(_with_path_prefix(f, "verdicts/"))
    if scorecards_folder is not None:
        for f in client.list_files(scorecards_folder.id, recursive=True):
            tree.append(_with_path_prefix(f, "scorecards/"))

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


def _with_path_prefix(f: DriveFile, prefix: str) -> DriveFile:
    """Return a copy of ``f`` with ``prefix`` prepended to its path."""
    return DriveFile(
        id=f.id,
        name=f.name,
        mime_type=f.mime_type,
        web_view_link=f.web_view_link,
        path=f"{prefix}{f.path}" if f.path else prefix.rstrip("/"),
        size_bytes=f.size_bytes,
        modified_time=f.modified_time,
        parent_id=f.parent_id,
        drive_id=f.drive_id,
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
