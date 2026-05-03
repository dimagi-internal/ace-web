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


def list_opp_runs(
    client: DriveClient,
    *,
    ace_root_folder_id: str,
    opp_slug: str,
) -> list[RunSummary]:
    """List runs under <opp>/runs/, newest-first by run-id (sorts as string).

    Returns empty list if the opp folder doesn't exist or has no runs/
    subfolder. Each RunSummary is loaded by reading state.yaml from the
    run folder.
    """
    opp_folder = _find_child_folder(client.list_folder(ace_root_folder_id), opp_slug)
    if opp_folder is None:
        return []
    runs_folder = _find_child_folder(client.list_folder(opp_folder.id), "runs")
    if runs_folder is None:
        return []

    out: list[RunSummary] = []
    for child in client.list_folder(runs_folder.id):
        if not _is_folder(child):
            continue
        state_file = _find_child(client.list_folder(child.id), "state.yaml")
        if state_file is None:
            continue
        try:
            body = _read_text(client, state_file)
            state = yaml.safe_load(body) or {}
        except (yaml.YAMLError, OSError) as exc:
            log.warning("list_opp_runs: failed to read %s: %s", state_file.id, exc)
            continue
        out.append(
            RunSummary(
                run_id=child.name,
                folder_id=child.id,
                current_phase=state.get("phase"),
                current_step=state.get("step"),
                mode=state.get("mode"),
                last_actor=state.get("last_actor"),
                last_actor_at=state.get("last_actor_at"),
            )
        )

    out.sort(key=lambda r: r.run_id, reverse=True)
    return out


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
    pending_gate_skills: list[str]      # skills with gate decision == "pending"
    eval_score: float | None            # latest opp-eval overall_score (0-100), if any
    eval_passed: bool | None            # latest opp-eval verdict pass/fail, if any
    last_activity_at: str | None        # state.yaml modifiedTime (ISO-8601), if present


def load_opp_card(
    client: DriveClient,
    *,
    opp_folder: DriveFile | None = None,
    opp_children: list[DriveFile] | None = None,
    ace_root_folder_id: str | None = None,
    opp_slug: str | None = None,
) -> "OppCard | dict":
    """Read the subset of ``ACE/<slug>/`` needed for a list card.

    Supports two calling conventions:

    **Legacy** (returns OppCard dataclass)::

        load_opp_card(client, opp_folder=<DriveFile>, opp_children=<list>)

    ``opp_children`` is the caller-provided listing of the opp folder
    (they already fetched it to decide whether this folder is an opp),
    so we don't re-list. We only fetch the body of ``state.yaml`` when
    it's present.

    **New multi-run** (returns dict)::

        load_opp_card(client, ace_root_folder_id=<str>, opp_slug=<str>)

    Reads ``opp.yaml`` for ``display_name``; if the opp has a ``runs/``
    subfolder, populates ``current_run_id``, ``current_phase``,
    ``current_step`` from the latest run's ``state.yaml``.

    Handles both flat (state.yaml at root) and legacy (runs/run-001/state.yaml)
    layouts — the latter requires one extra listing to descend into runs/,
    acceptable because it's rare and only triggered for pre-refactor opps.
    """
    # --- New multi-run path ---
    if ace_root_folder_id is not None and opp_slug is not None:
        return _load_opp_card_multi_run(client, ace_root_folder_id=ace_root_folder_id, opp_slug=opp_slug)

    # --- Legacy path (opp_folder + opp_children required) ---
    assert opp_folder is not None and opp_children is not None, (
        "load_opp_card requires either (opp_folder, opp_children) or "
        "(ace_root_folder_id, opp_slug)"
    )
    return _load_opp_card_legacy(client, opp_folder=opp_folder, opp_children=opp_children)


def _load_opp_card_legacy(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    opp_children: list[DriveFile],
) -> "OppCard":
    """Legacy load_opp_card implementation — flat layout, returns OppCard."""
    slug = opp_folder.name

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
        try:
            state_data = yaml.safe_load(_read_text(client, state_file)) or {}
        except yaml.YAMLError:
            log.warning("state.yaml for %s is not valid YAML", slug)

    opp_manifest = OppManifest(
        slug=slug,
        display_name=state_data.get("display_name", slug),
        created_at=state_data.get("started_at") or state_data.get("created"),
        created_by=state_data.get("created_by") or state_data.get("initiated_by"),
        labels=[],
        current_run_id="r1",
    )

    # Gates come for free from state.yaml — no extra Drive call.
    gates_by_skill = _gates_from_state(state_data)
    pending = sorted(
        skill
        for skill, history in gates_by_skill.items()
        if history and history[-1].decision == "pending"
    )

    # opp-eval verdict — only fetched when the opp has a verdicts/ subfolder
    # AND that folder contains an opp-eval-*.yaml. This is bounded by the
    # opp's existing artifact tree, so the marginal cost is zero for opps
    # that haven't been judged yet.
    eval_score, eval_passed = _load_opp_eval_summary(client, opp_children)

    return OppCard(
        opp=opp_manifest,
        current_phase=state_data.get("current_phase"),
        current_step=state_data.get("current_step"),
        status="ok" if state_file is not None else "no-state",
        pending_gate_skills=pending,
        eval_score=eval_score,
        eval_passed=eval_passed,
        last_activity_at=state_file.modified_time if state_file is not None else None,
    )


def _load_opp_card_multi_run(
    client: DriveClient,
    *,
    ace_root_folder_id: str,
    opp_slug: str,
) -> dict:
    """Multi-run-aware load_opp_card — returns a plain dict."""
    opp_folder = _find_child_folder(client.list_folder(ace_root_folder_id), opp_slug)
    if opp_folder is None:
        raise FileNotFoundError(f"opp {opp_slug!r} not found under {ace_root_folder_id!r}")

    opp_data = _read_opp_yaml(client, opp_folder.id)
    display_name = opp_data.get("display_name", opp_slug)

    # Check for multi-run layout (runs/ subfolder).
    opp_children = client.list_folder(opp_folder.id)
    runs_folder = _find_child_folder(opp_children, "runs")

    current_run_id: str | None = None
    current_phase: str | None = None
    current_step: str | None = None

    if runs_folder is not None:
        run_summaries = list_opp_runs(
            client, ace_root_folder_id=ace_root_folder_id, opp_slug=opp_slug
        )
        if run_summaries:
            latest = run_summaries[0]
            current_run_id = latest.run_id
            current_phase = latest.current_phase
            current_step = latest.current_step
    else:
        # Flat layout — read state.yaml from opp root.
        state_file = _find_child(opp_children, "state.yaml")
        if state_file is not None:
            try:
                state_data = yaml.safe_load(_read_text(client, state_file)) or {}
            except yaml.YAMLError:
                state_data = {}
            current_run_id = "r1"
            current_phase = state_data.get("current_phase")
            current_step = state_data.get("current_step")

    return {
        "slug": opp_slug,
        "display_name": display_name,
        "current_run_id": current_run_id,
        "current_phase": current_phase,
        "current_step": current_step,
    }


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
        run_summaries = list_opp_runs(
            client, ace_root_folder_id=_ace_folder_id, opp_slug=_slug
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

    matchers = _artifact_matchers(overview.get("artifacts") or [])
    files_by_skill = _attribute_files_to_skills(opp_tree, matchers)

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

    verdicts_by_skill = _load_verdicts(client, opp_tree)
    gates_by_skill = _gates_from_state(state_data)

    steps = _build_steps(skill_registry, artifacts_by_skill, verdicts_by_skill, gates_by_skill, opp_folder.id)

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

    # List the run folder for artifact attribution (non-recursive via list_folder).
    run_children = client.list_folder(run_folder_id)

    # state.yaml is already parsed into run_summary — just read for extra fields.
    state_file = _find_child(run_children, "state.yaml")
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
            pdd_file = _find_child(inputs_children, "pdd.md") or _find_child(inputs_children, "idea.md")
    pdd_body = _read_text(client, pdd_file) if pdd_file else ""

    # Attribute run-folder files to skills via artifact manifest.
    # Use a flat (non-recursive) listing for the run folder; the test's FakeDrive
    # only exposes list_folder. For richer artifact attribution in production,
    # the GoogleDriveClient's list_folder delegate to list_files(recursive=False).
    run_tree = run_children  # non-recursive listing is sufficient for top-level attribution
    matchers = _artifact_matchers(overview.get("artifacts") or [])
    files_by_skill = _attribute_files_to_skills(run_tree, matchers)

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

    verdicts_by_skill = _load_verdicts(client, run_tree)
    gates_by_skill = _gates_from_state(state_data)

    steps = _build_steps(skill_registry, artifacts_by_skill, verdicts_by_skill, gates_by_skill, run_folder_id)

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
    )


def _build_steps(
    skill_registry,
    artifacts_by_skill: dict[str, list[ArtifactRef]],
    verdicts_by_skill: dict[str, "JudgeVerdict"],
    gates_by_skill: dict[str, list["GateDecision"]],
    folder_id: str,
) -> list[StepSnapshot]:
    """Synthesize StepSnapshot rows from the skill registry + Drive data."""
    steps: list[StepSnapshot] = []
    for skill_meta in skill_registry:
        artifacts = artifacts_by_skill.get(skill_meta.name, [])
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
                folder_id=folder_id,
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
