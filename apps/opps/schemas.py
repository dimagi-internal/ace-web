"""Pydantic schemas for the /api/opps surface.

Mirrors the existing payload shape produced by `apps/opps/sync.py`
and consumed by `frontend/src/api/opps.ts` + `types.ts`. Field names
match what the frontend expects so the schema can be introduced
without a frontend rewrite in this phase.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field

from apps.common.schemas import StrictModel

# --- Identifiers -------------------------------------------------------

PhaseId = str  # e.g. "idea-to-design", "scenarios-and-acceptance"
SkillId = str  # plugin-declared skill slug
RunId = str  # e.g. "run-001"

# --- Cards / snapshots -------------------------------------------------


class OppCardOut(StrictModel):
    slug: str
    title: str
    current_phase: PhaseId | None = None
    current_skill: SkillId | None = None
    run_count: int = Field(ge=0)
    last_run_id: RunId | None = None
    # None when the opp has no completed run yet (idea-only / pre-run opps).
    # Previously serialised as the Unix epoch, which the frontend rendered
    # as "last 12/31/1969" on the workspace opps list (#466).
    updated_at: dt.datetime | None = None


class ArtifactOut(StrictModel):
    id: str  # Drive file_id
    name: str
    mime_type: str
    size_bytes: int | None = None
    url: str | None = None  # web view link, may be null for unshared files
    is_text: bool
    preview: str | None = None


class VerdictOut(StrictModel):
    skill: SkillId
    phase: PhaseId
    kind: Literal["quick", "deep", "monitor"]
    score: int = Field(ge=0, le=100)
    verdict: Literal["pass", "warn", "fail"]
    rationale: str
    decided_at: dt.datetime


class GateOut(StrictModel):
    skill: SkillId
    decision: Literal["approved", "rejected", "pending"]
    decided_by: str | None = None
    decided_at: dt.datetime | None = None
    note: str | None = None


class StepSnapshotOut(StrictModel):
    skill: SkillId
    phase: PhaseId
    status: Literal["pending", "in_progress", "complete", "skipped", "failed"]
    artifact_count: int = Field(ge=0)
    artifacts: list[ArtifactOut]
    verdicts: list[VerdictOut]
    gate: GateOut | None = None
    preview: str | None = None


class ScorecardOut(StrictModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["pass", "warn", "fail"]
    rationale: str
    trend: list[int]  # historical scores by run
    decided_at: dt.datetime


class OppRunOut(StrictModel):
    run_id: RunId
    label: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    is_active: bool
    scorecard: ScorecardOut | None = None


class OppSnapshotOut(StrictModel):
    slug: str
    title: str
    runs: list[OppRunOut]
    active_run_id: RunId | None = None
    steps: list[StepSnapshotOut]
    pending_gates: list[SkillId]
    scorecard: ScorecardOut | None = None
    updated_at: dt.datetime


# --- Create / Update ---------------------------------------------------


class OppCreateIn(StrictModel):
    """Request body for POST /w/{workspace_slug}/opps."""

    title: str = Field(min_length=1, max_length=128, description="Display name for the opp.")
    slug: str = Field(
        min_length=2,
        max_length=64,
        description=(
            "URL-safe identifier. Must match [a-z0-9][a-z0-9-]{0,62}[a-z0-9]. "
            "Validated against SLUG_RE in opp_creator."
        ),
    )
    idea: str = Field(default="", description="Initial idea text (idea.md content).")
    mode: str = Field(default="review", description="Opp mode: 'review' or 'auto'.")
    pdd: str = Field(default="", description="Optional pre-written PDD body.")


class OppPatchIn(StrictModel):
    """Request body for PATCH /w/{workspace_slug}/opps/{slug}.

    All fields are optional — only set fields are applied.
    """

    title: str | None = Field(default=None, min_length=1, max_length=128)


# --- Fork --------------------------------------------------------------


class OppForkEditIn(StrictModel):
    """A single answer override to apply during fork.

    The forker finds the row by ``row_id`` in the source run's
    ``decisions.yaml``, sets its ``default`` to ``new_answer``, and
    marks ``status: overridden`` — matching the contract that
    ``decisions-sync`` already uses, so downstream phases on re-run
    honor the human's value verbatim.
    """

    row_id: str = Field(min_length=1)
    new_answer: str


class OppForkIn(StrictModel):
    fork_at_phase: str = Field(min_length=1)
    source_run_id: RunId | None = None
    edits: list[OppForkEditIn] = Field(default_factory=list)


class OppForkOut(StrictModel):
    slug: str
    run_id: RunId
    working_session_slug: str


ForkStatus = Literal["unknown", "counting", "copying", "finalizing", "done", "error"]


class ForkProgress(StrictModel):
    status: ForkStatus
    progress: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    files_total: int | None = None
    files_copied: int | None = None
    error: str | None = None
    new_slug: str | None = None
    new_run_id: RunId | None = None


# --- Gate decision write -----------------------------------------------


class GateDecisionIn(StrictModel):
    """Request body for POST /w/{workspace_slug}/opps/{slug}/gates/{skill}."""

    decision: Literal["approved", "rejected"]
    note: str | None = None


# --- Multi-run compare -------------------------------------------------


class OppCompareOut(StrictModel):
    """Response for GET /w/{workspace_slug}/opps/{slug}/compare."""

    slug: str
    run_ids: list[RunId]
    snapshots: list[OppSnapshotOut]


# --- Health probe ------------------------------------------------------


class OppHealthOut(StrictModel):
    """Response for GET /w/{workspace_slug}/opps/{slug}/health."""

    reachable: bool
    last_checked_at: dt.datetime
    error: str | None = None


# --- Seed-chat ---------------------------------------------------------


class SeedChatIn(StrictModel):
    """Request body for POST /w/{workspace_slug}/opps/{slug}/actions/seed-chat."""

    step_skill: str = Field(min_length=1)
    run_id: RunId | None = None


class SeedChatOut(StrictModel):
    """Response for POST /w/{workspace_slug}/opps/{slug}/actions/seed-chat."""

    session_slug: str
