"""Pure parsers for the ACE opp Drive folder format.

Every function takes a file body (string) and returns a structured dataclass
or list of dataclasses. No Drive I/O. No Django model operations. Parsers
are strict about required fields (raise ValueError) and tolerant about
optional ones (default to None / empty).

Format reference: docs/specs/2026-04-08-ace-opp-visualization-design.md § 6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import yaml

# --- Dataclasses for parsed manifests ---


@dataclass
class OppManifest:
    slug: str
    display_name: str
    created_at: str | None = None
    created_by: str | None = None
    labels: list[str] = field(default_factory=list)
    current_run_id: str | None = None


@dataclass
class RunManifest:
    run_id: str
    mode: str  # auto | review | dry-run | sandbox
    status: str  # running | blocked | complete | failed | abandoned
    started_at: str | None = None
    completed_at: str | None = None
    current_phase: str | None = None
    current_step: str | None = None
    skill_versions: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass
class StepManifest:
    skill_name: str
    phase: str
    ordinal: int
    # pending | running | complete | judge-fail | gate-pending | gate-rejected | error | skipped
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    preview_stats: dict = field(default_factory=dict)


@dataclass
class JudgeVerdict:
    score: float | None
    passed: bool | None
    evaluated_at: str | None
    criteria: dict = field(default_factory=dict)
    rationale: str = ""


@dataclass
class GateDecision:
    ts: str
    decision: str  # pending | approved | rejected
    decided_by: str = ""
    note: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class RunEvent:
    ts: str
    kind: str
    step: str | None = None
    payload: dict = field(default_factory=dict)


# --- Validators ---

_VALID_MODES = frozenset({"auto", "review", "dry-run", "sandbox"})
_VALID_RUN_STATUSES = frozenset({"running", "blocked", "complete", "failed", "abandoned"})
_VALID_STEP_STATUSES = frozenset(
    {
        "pending",
        "running",
        "complete",
        "judge-fail",
        "gate-pending",
        "gate-rejected",
        "error",
        "skipped",
    }
)
_VALID_GATE_DECISIONS = frozenset({"pending", "approved", "rejected"})


# --- Internal helpers ---


def _load_yaml(body: str) -> dict:
    """Load a YAML document, returning an empty dict if blank."""
    result = yaml.safe_load(body) if body.strip() else {}
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise ValueError(f"expected a YAML mapping, got {type(result).__name__}")
    return result


# --- Parsers ---


def parse_opp_yaml(body: str) -> OppManifest:
    data = _load_yaml(body)
    slug = data.get("slug")
    if not slug:
        raise ValueError("opp.yaml missing required field 'slug'")
    return OppManifest(
        slug=str(slug),
        display_name=str(data.get("display_name", slug)),
        created_at=data.get("created_at"),
        created_by=data.get("created_by"),
        labels=list(data.get("labels") or []),
        current_run_id=data.get("current_run_id"),
    )


def parse_run_yaml(body: str) -> RunManifest:
    data = _load_yaml(body)
    run_id = data.get("run_id")
    if not run_id:
        raise ValueError("run.yaml missing required field 'run_id'")
    mode = data.get("mode", "review")
    if mode not in _VALID_MODES:
        raise ValueError(
            f"run.yaml invalid mode '{mode}' — expected one of {sorted(_VALID_MODES)}"
        )
    status = data.get("status", "running")
    if status not in _VALID_RUN_STATUSES:
        raise ValueError(
            f"run.yaml invalid status '{status}' — expected one of {sorted(_VALID_RUN_STATUSES)}"
        )
    return RunManifest(
        run_id=str(run_id),
        mode=mode,
        status=status,
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        current_phase=data.get("current_phase"),
        current_step=data.get("current_step"),
        skill_versions=dict(data.get("skill_versions") or {}),
        notes=str(data.get("notes") or ""),
    )


def parse_step_yaml(body: str) -> StepManifest:
    data = _load_yaml(body)
    if not data.get("skill_name"):
        raise ValueError("step.yaml missing required field 'skill_name'")
    status = data.get("status", "pending")
    if status not in _VALID_STEP_STATUSES:
        raise ValueError(
            f"step.yaml invalid status '{status}' — expected one of {sorted(_VALID_STEP_STATUSES)}"
        )
    return StepManifest(
        skill_name=str(data["skill_name"]),
        phase=str(data.get("phase", "")),
        ordinal=int(data.get("ordinal", 0)),
        status=status,
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        error=data.get("error"),
        preview_stats=dict(data.get("preview_stats") or {}),
    )


def parse_judge_yaml(body: str) -> JudgeVerdict:
    data = _load_yaml(body)
    return JudgeVerdict(
        score=(float(data["score"]) if "score" in data and data["score"] is not None else None),
        passed=data.get("passed"),
        evaluated_at=data.get("evaluated_at"),
        criteria=dict(data.get("criteria") or {}),
        rationale=str(data.get("rationale") or ""),
    )


def parse_gates_jsonl(body: str) -> list[GateDecision]:
    out: list[GateDecision] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # Tolerate malformed lines rather than fail the entire sync.
            continue
        decision = record.get("decision", "pending")
        if decision not in _VALID_GATE_DECISIONS:
            continue
        out.append(
            GateDecision(
                ts=str(record.get("ts", "")),
                decision=decision,
                decided_by=str(record.get("decided_by", "")),
                note=str(record.get("note", "")),
                payload=dict(record.get("payload") or {}),
            )
        )
    return out


def parse_events_jsonl(body: str) -> list[RunEvent]:
    out: list[RunEvent] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(
            RunEvent(
                ts=str(record.get("ts", "")),
                kind=str(record.get("kind", "")),
                step=record.get("step"),
                payload=dict(record.get("payload") or {}),
            )
        )
    return out
