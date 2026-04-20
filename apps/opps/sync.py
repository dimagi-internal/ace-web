"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns an OppSnapshot suitable for JSON serialization.

Folder shape (the one the ACE plugin writes today):

    ACE/<slug>/idea.md                           (required)
    ACE/<slug>/pdd.md  or  idd.md                (optional; legacy name accepted)
    ACE/<slug>/state.yaml                        (written by /ace:run)
    ACE/<slug>/<subfolder>/*                     (per skill, per manifest)
    ACE/<slug>/verdicts/<skill>-*.yaml           (LLM-as-Judge verdicts)
    ACE/<slug>/gate-briefs/<skill>.md            (review-mode gate briefs)

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
from dataclasses import dataclass
from typing import Any

import yaml
from django.conf import settings

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.parsers import GateDecision, JudgeVerdict, OppManifest, StepManifest

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


def _is_folder(f: DriveFile) -> bool:
    return f.mime_type == "application/vnd.google-apps.folder"


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


def _attribute_files_to_skills(
    files: list[DriveFile], matchers: list[tuple[re.Pattern[str], str]]
) -> dict[str, list[DriveFile]]:
    """Group Drive files by the skill that produces them (per manifest).

    Files with no matching manifest entry are attributed to ``""`` so
    callers can surface them as "unclassified" if desired.
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
        key = matched or ""
        by_skill.setdefault(key, []).append(f)
    return by_skill


def _drive_file_to_artifact_ref(f: DriveFile) -> ArtifactRef:
    return ArtifactRef(
        name=f.name,
        drive_file_id=f.id,
        drive_web_link=f.web_view_link,
        size_bytes=f.size_bytes,
        mime_type=f.mime_type,
        path=f.path,
    )


# --- Verdict + gate extraction ---


_VERDICT_PATH_RE = re.compile(r"^verdicts/(?P<stem>[^/]+)\.ya?ml$")


def _skill_from_verdict_stem(stem: str) -> str:
    """Derive skill name from a verdict filename stem.

    Examples:
      - "ocs-chatbot-eval-quick"   -> "ocs-chatbot-eval"
      - "ocs-chatbot-eval-deep"    -> "ocs-chatbot-eval"
      - "ocs-chatbot-eval-monitor" -> "ocs-chatbot-eval"
      - "opp-eval-deep"            -> "opp-eval"
      - "opp-eval-monitor"         -> "opp-eval"
      - "idea-to-pdd"              -> "idea-to-pdd"
    """
    for suffix in ("-quick", "-deep", "-monitor"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _parse_verdict_yaml(body: str) -> JudgeVerdict | None:
    """Parse a verdict YAML body into a JudgeVerdict.

    Tolerant of both the old short shape ({score, passed, ...}) and the
    plugin's current eval shape ({overall_score, verdict, dimensions, ...}).
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
    client: DriveClient, opp_files: list[DriveFile]
) -> dict[str, JudgeVerdict]:
    """Read every ``verdicts/*.yaml`` and return {skill_name: JudgeVerdict}.

    When multiple verdicts exist for one skill (e.g. quick + deep + monitor
    for ocs-chatbot-eval), keep the latest by evaluated_at, with deep
    preferred over monitor preferred over quick as tiebreakers.
    """
    ranking = {"-deep": 3, "-monitor": 2, "-quick": 1}

    def _variant_rank(path: str) -> int:
        for suffix, score in ranking.items():
            if suffix in path:
                return score
        return 0

    candidates: dict[str, tuple[int, str, JudgeVerdict]] = {}
    for f in opp_files:
        if _is_folder(f):
            continue
        m = _VERDICT_PATH_RE.match(f.path)
        if not m:
            continue
        stem = m.group("stem")
        skill = _skill_from_verdict_stem(stem)
        try:
            body = _read_text(client, f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to read %s: %s", f.path, exc)
            continue
        verdict = _parse_verdict_yaml(body)
        if verdict is None:
            continue
        rank = _variant_rank(f.path)
        ts = verdict.evaluated_at or ""
        existing = candidates.get(skill)
        if existing is None or (rank, ts) > (existing[0], existing[1]):
            candidates[skill] = (rank, ts, verdict)

    return {skill: v for skill, (_, _, v) in candidates.items()}


def _gates_from_state(state_data: dict) -> dict[str, list[GateDecision]]:
    """Derive per-skill gate history from ``state.yaml``'s ``gates:`` map.

    Plugin 0.3.3+ writes::

        gates:
          idea-to-pdd:
            decision: approved|pending|rejected
            decided_by: <email>
            decided_at: <ISO-8601>
            note: <string>

    Older opps may just have ``gates: {idea-to-pdd: approved}``. Both
    shapes are accepted.
    """
    out: dict[str, list[GateDecision]] = {}
    raw = state_data.get("gates") or {}
    if not isinstance(raw, dict):
        return out
    for skill, entry in raw.items():
        if isinstance(entry, str):
            out[skill] = [
                GateDecision(
                    ts=state_data.get("last_actor_at") or "",
                    decision=entry,
                    decided_by=state_data.get("last_actor") or "",
                    note="",
                )
            ]
        elif isinstance(entry, dict):
            out[skill] = [
                GateDecision(
                    ts=entry.get("decided_at") or "",
                    decision=entry.get("decision") or "pending",
                    decided_by=entry.get("decided_by") or "",
                    note=entry.get("note") or "",
                )
            ]
    return out


# --- Main entry point ---


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
    from apps.system.reader import load_system_overview

    # Locate the opp folder
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")

    # Single flat recursive listing of the opp folder — one round-trip
    # regardless of nesting depth. All downstream attribution works off
    # this list.
    opp_tree = client.list_files(opp_folder.id, recursive=True)
    opp_children = client.list_files(opp_folder.id)  # non-recursive for root-level hits

    # state.yaml lives at root (new shape) or runs/run-001/ (legacy).
    state_file = _find_child(opp_children, "state.yaml")
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

    # Attribute files to skills via the artifact manifest. The plugin's
    # ``lib/artifact-manifest.ts`` is the source of truth for which skill
    # produces which path.
    plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "") or ""
    overview = load_system_overview(plugin_path)
    matchers = _artifact_matchers(overview.get("artifacts") or [])
    files_by_skill = _attribute_files_to_skills(opp_tree, matchers)

    artifacts_by_skill: dict[str, list[ArtifactRef]] = {
        skill: [_drive_file_to_artifact_ref(f) for f in files]
        for skill, files in files_by_skill.items()
        if skill  # drop the "" unclassified bucket
    }

    # pdd.md / idd.md are mapped to idea-to-pdd via the manifest (``pdd.md``
    # entry). But if the opp uses the legacy ``idd.md`` filename, the
    # manifest regex won't match it — fall back to explicit attribution.
    if pdd_file is not None and not any(
        a.name == pdd_file.name for a in artifacts_by_skill.get("idea-to-pdd", [])
    ):
        artifacts_by_skill.setdefault("idea-to-pdd", []).append(
            _drive_file_to_artifact_ref(pdd_file)
        )

    # Verdicts + gates
    verdicts_by_skill = _load_verdicts(client, opp_tree)
    gates_by_skill = _gates_from_state(state_data)

    # Synthesize step rows from the dynamic skill registry.
    steps: list[StepSnapshot] = []
    for skill_meta in SKILL_REGISTRY:
        artifacts = artifacts_by_skill.get(skill_meta.name, [])
        # Derive status: a gate decision dominates; else artifact presence.
        gate_entries = gates_by_skill.get(skill_meta.name, [])
        if gate_entries and gate_entries[-1].decision == "rejected":
            status = "gate-rejected"
        elif gate_entries and gate_entries[-1].decision == "pending":
            status = "gate-pending"
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
                gates=gate_entries,
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
