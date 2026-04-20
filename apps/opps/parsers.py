"""Dataclasses for the ACE opp snapshot payload.

Used by ``apps.opps.sync`` (to build ``OppSnapshot`` from Drive folder
state) and ``apps.opps.serializers`` (to emit the frontend JSON envelope).

Before the drop-multi-run refactor, this module also housed YAML/JSONL
parsers for the structured Drive layout (opp.yaml, run.yaml, step.yaml,
judge.yaml, gates.jsonl). That layout is retired — the current flat
layout stores only idea.md + state.yaml + artifact subfolders per opp.
The parsers went with it; the dataclasses stay because the snapshot
envelope shape is still the same.

Format reference: docs/plans/2026-04-20-drop-multi-run-simplify.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
