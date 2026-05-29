"""Dataclasses for the ACE opp snapshot payload.

Used by ``apps.opps.sync`` (to build ``OppSnapshot`` from Drive folder
state) and ``apps.opps.serializers`` (to emit the frontend JSON envelope).

Before the drop-multi-run refactor, this module also housed YAML/JSONL
parsers for the structured Drive layout (opp.yaml, run.yaml, step.yaml,
judge.yaml, gates.jsonl). That layout was retired then revived in
0.11.0 (multi-run-per-opp). The current canonical layout is
``ACE/<slug>/opp.yaml`` + ``ACE/<slug>/runs/<run-id>/run_state.yaml``
(plus artifact subfolders). Older opps still carry ``state.yaml`` at
the opp root or inside ``runs/<id>/``; sync.py reads either via
``_find_state_file``. The parsers went with the original retirement;
the dataclasses stay because the snapshot envelope shape is unchanged.

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
    tags: list[str] = field(default_factory=list)
    current_run_id: str | None = None


@dataclass
class StepManifest:
    skill_name: str
    phase: str
    ordinal: int
    # pending | running | complete | judge-fail | qa-failed | error | skipped
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
class QAFailure:
    """One failed structural QA check.

    Mirrors the shape declared in ACE's ``lib/qa-types.ts`` (PR #146):
    every QA failure is severity=blocker and carries an ``auto_fix_hint``
    the orchestrator passes to the producer for regeneration.
    """

    check: str
    type: str  # static | llm
    detail: str
    auto_fix_hint: str


@dataclass
class QAResult:
    """Structural QA verdict on a producer artifact.

    Distinct from ``JudgeVerdict``: QA is binary (pass / fail / incomplete)
    and gates eval. If QA fails irrecoverably, the corresponding eval is
    skipped and JudgeVerdict.passed will be None / verdict 'incomplete'.

    See ACE PR #146 (``skills/_qa-template.md``) for the canonical
    contract; ``lib/qa-types.ts`` is the source-of-truth schema.
    """

    skill: str  # the QA skill that produced this (e.g. "idea-to-pdd-qa")
    target_skill: str  # the producer skill being checked (e.g. "idea-to-pdd")
    verdict: str  # pass | fail | incomplete
    ran_at: str | None = None
    capture_path: str | None = None
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    failures: list[QAFailure] = field(default_factory=list)
    auto_fix_attempted: bool | None = None
    auto_fix_attempts: int | None = None
    auto_fix_succeeded: bool | None = None


@dataclass
class Decision:
    """One row from the per-run decisions log.

    Mirrors the schema in ACE's ``lib/decisions-schema.ts`` (decisions-log
    framework, May 2026). Each row records a load-bearing default a phase
    skill applied — what was asked, what was picked, what alternatives
    were on the table, and whether the human reviewer overrode the default.

    See ACE ``docs/superpowers/specs/2026-05-08-decisions-log-design.md``
    for canonical field semantics. Lives at the run-folder root in
    ``decisions.yaml``, alongside ``run_state.yaml``.
    """

    id: str
    phase: str
    skill: str
    question: str
    ai_default: str
    override: str = ""
    options_considered: list[str] = field(default_factory=list)
    source: str = ""
    status: str = "ai-default"  # ai-default | overridden
    notes: str = ""
    # Human's rationale when status=overridden. Mirrors the AI's ``notes``
    # (which carries the AI's ``reasoning``) but for the override side.
    # Surfaces in the Workbench so the next human can see why the prior
    # human picked a different option than the AI default.
    override_reasoning: str = ""
    # v4 (ACE PRs #554/#555/#556, May 2026). ``evidence_basis`` records how
    # the AI grounded its default: ``stated`` (directly in the source),
    # ``inferred`` (extrapolated beyond it), or ``conflicting`` (resolves
    # disagreeing source signals). ``conflict_signals`` lists each competing
    # source reading; populated (≥2 entries) only when
    # ``evidence_basis == "conflicting"``. Legacy v3 rows have neither — the
    # reader defaults ``evidence_basis`` to ``stated`` so they render unchanged.
    # Canonical schema: ACE ``lib/decisions-schema.ts`` (v4 block).
    evidence_basis: str = "stated"
    conflict_signals: list[str] = field(default_factory=list)
