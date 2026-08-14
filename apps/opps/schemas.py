"""Pydantic schemas for the /api/opps surface.

Mirrors the existing payload shape produced by `apps/opps/sync.py`
and consumed by `frontend/src/api/opps.ts` + `types.ts`. Field names
match what the frontend expects so the schema can be introduced
without a frontend rewrite in this phase.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, model_validator

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


class StepArtifactOut(StrictModel):
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
    artifacts: list[StepArtifactOut]
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
    ``decisions.yaml``, sets its ``override`` to ``new_answer``, and
    marks ``status: overridden`` — matching the schema-v2 contract that
    ``decisions-sync`` uses. The original AI value remains in
    ``ai-default`` for audit trail; downstream phases on re-run see the
    effective value (``override`` if present else ``ai-default``).

    ``new_answer`` MAY be a string not already present in the row's
    ``options`` array; the forker appends it before setting ``override``,
    keeping the ACE strict-write invariant (``override ∈ options``)
    intact. ``override_reasoning`` is the human's free-text rationale,
    persisted alongside.
    """

    row_id: str = Field(min_length=1)
    new_answer: str
    override_reasoning: str = ""


class OppForkIn(StrictModel):
    """Fork request. The fork POINT is one concept with two spellings.

    Name a **phase** (``fork_at_phase``) to re-run it whole, or a **skill**
    (``fork_at_skill``) to keep that phase's earlier artifacts and re-run
    from that skill onward. Exactly one is required.

    Skill-granular forking existed on the old run-fork endpoint and was lost
    when ``apps/opps/fork.py`` was deleted in the multi-run simplification
    (2026-04-20). It depended on a ``steps/<NN>-<skill>/`` folder layout that
    no longer exists — the current layout is ``<N>-<phase>/<skill>_<role>.ext``
    — so it's re-implemented here against the artifact manifest's
    ``produced_by`` map rather than against folder names.
    """

    fork_at_phase: str | None = Field(default=None, min_length=1)
    fork_at_skill: str | None = Field(default=None, min_length=1)
    source_run_id: RunId | None = None
    edits: list[OppForkEditIn] = Field(default_factory=list)
    mode: Literal["keep-overrides-only", "keep-all"] = "keep-all"
    feedback: str | None = Field(default=None, max_length=8000)
    """Why this fork exists. Seeded as the first user-turn of the new run's
    working session, so the agent picking it up reads the intent instead of
    inferring it. Optional — an empty fork is legitimate."""

    @model_validator(mode="after")
    def _exactly_one_fork_point(self) -> OppForkIn:
        named = [
            n
            for n, v in (
                ("fork_at_phase", self.fork_at_phase),
                ("fork_at_skill", self.fork_at_skill),
            )
            if v
        ]
        if len(named) != 1:
            raise ValueError(
                "provide exactly one of fork_at_phase / fork_at_skill "
                f"(got {named or 'neither'})"
            )
        return self


class OppForkOut(StrictModel):
    slug: str
    run_id: RunId
    working_session_slug: str


class DecisionOverridesSaveIn(StrictModel):
    """Body for POST /{slug}/decision-overrides. Carries NO edits — the
    server reads the Redis shared buffer as the authoritative set, so a
    stale tab can't clobber another reviewer's concurrent edits."""

    source_run_id: RunId = Field(min_length=1)


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


# --- Public decision reactions -----------------------------------------


class DecisionReactionIn(StrictModel):
    """Body for POST /opps/public/{ws}/{slug}/runs/{run}/decisions/{id}/reactions.

    ``reviewer`` is REQUIRED and self-reported. The page has no login and
    a partner cannot self-serve one, so the only honest options were a
    required free-text name or anonymous reactions — and an anonymous
    reaction defeats the store it lands in: the feedback ledger's whole
    value is being able to tell a reviewer where THEIR comment went, and
    to tell a future reader whose judgement drove a change. An unsigned
    comment is unanswerable and uncreditable. So: required name, optional
    email (the reply path), and the record says the name is self-reported
    rather than pretending it is verified.

    Length ceilings live in ``apps.opps.reactions`` and are enforced
    there too — these are the cheap first pass, so an oversized body is
    rejected before any Drive round-trip.
    """

    reviewer: Annotated[str, Field(min_length=1, max_length=120)]
    comment: Annotated[str, Field(min_length=1, max_length=4000)]
    reviewer_email: Annotated[str, Field(max_length=254)] | None = None


class DecisionReactionOut(StrictModel):
    """What the page needs to render the reaction it just submitted."""

    feedback_ref: str
    record_slug: str
    item_id: str
    decision_id: str
    reviewer: str
    comment: str
    received_at: str


class DecisionEditIn(StrictModel):
    """Body for POST /opps/public/{ws}/{slug}/runs/{run}/decisions/{id}/edit.

    Anyone with the link can change a decision's value in place — no
    proposal state, no promotion step, no member-only privilege, and
    reviewer 2 changing reviewer 1's answer is the same act as Dimagi
    changing either. Safety is visibility and reversibility (attribution
    on every row, full history, undo from the UI), not permission — the
    same way it is in a Google Doc, which is exactly what the PDD these
    decisions summarize already is.

    Identity resolves per caller and NOT from this body when we already
    know who it is: **signed in ⇒ never anonymous**, so ``reviewer`` and
    ``reviewer_email`` are ignored for an authenticated request and
    REQUIRED for an anonymous one. See ``apps.opps.public_input``.

    Length ceilings are enforced again in ``apps.opps.decision_overrides``
    — these are the cheap first pass, before any Drive round-trip.
    """

    value: Annotated[str, Field(min_length=1, max_length=800)]
    reasoning: Annotated[str, Field(max_length=4000)] | None = None
    reviewer: Annotated[str, Field(max_length=120)] | None = None
    reviewer_email: Annotated[str, Field(max_length=254)] | None = None


class DecisionEditHistoryOut(StrictModel):
    """One superseded state of a decision row. Newest first."""

    override: str
    reasoning: str = ""
    decided_by_name: str = ""
    decided_by_verified: bool = False
    decided_at: str = ""


class DecisionEditOut(StrictModel):
    """A decision's current human-set answer, as any reader sees it.

    Emails are not projected on the public payload; the NAME always is —
    attribution is the safety mechanism, so hiding it would defeat the
    model.
    """

    decision_id: str
    override: str
    reasoning: str = ""
    decided_by_name: str = ""
    decided_by_verified: bool = False
    decided_at: str = ""
    source_run_id: str = ""
    is_revert: bool = False
    history: list[DecisionEditHistoryOut] = []


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


# --- Seeded run --------------------------------------------------------


class SeededRunIn(StrictModel):
    """Request body for POST /w/{workspace_slug}/opps/{slug}/actions/seeded-run.

    Launches a first-class seeded run via **fork-then-resume** (ace#672): the
    action forks ``golden_run_id`` into a fresh run shaped so the phases below
    ``min(only)`` are ``done``/``verdict: seeded``, the listed ordinals are
    ``pending``, and every other phase from the fork point onward is
    ``skipped`` — then drives a plain ``/ace:run <slug>/<new_run_id>`` resume.
    The run is loop-blind; the ``/ace:iterate`` client observes its run_state.
    (The old ``--seed-from``/``--only`` flags were dropped — the headless runner
    ignored them.)
    """

    golden_run_id: RunId = Field(min_length=1)
    # Comma-separated phase ordinals to run, e.g. "3,4,6". The lowest is the
    # fork point; the ACE orchestrator's resume path enforces input deps. We
    # only enforce the shape here.
    #
    # "3,4,6" is the STANDARD spot-check shape — do not drop Phase 4. Phase 3
    # builds FRESH apps (new cc_app_id); Phase 6's device walk needs a LIVE
    # opportunity wired to those fresh app IDs, which only Phase 4
    # (connect-setup) mints. A "3,6" shape skips Phase 4, so Phase 6 has no
    # live opp for the fresh apps — it can only fall back to cached screenshots
    # and reports `incomplete` (and wastes ~20 min attempting a doomed AVD walk
    # first). 3,4,6 is the minimal shape that exercises Phase 6 live.
    only: str = Field(default="3,4,6", pattern=r"^\d+(,\d+)*$")
    # Seeded runs are the test/iteration harness, where the per-step LLM evals
    # (~7 min in Phase 3) are pure overhead: a `verdict: fail` doesn't gate or
    # halt the run — evals only produce a quality score + a pause summary, and
    # `--no-evals` cleanly yields `verdict: partial-evals-skipped`. So default
    # to skipping them; set false to force inline grading.
    skip_evals: bool = True


class SeededRunOut(StrictModel):
    """Response for POST /w/{workspace_slug}/opps/{slug}/actions/seeded-run.

    The run executes asynchronously (202); `assistant_message_id` is the turn
    the headless driver fills in. `run_id` is the new forked run the action
    minted (the `/ace:iterate` client observes `runs/<run_id>/run_state.yaml`
    directly — no post-launch folder-listing race).
    """

    session_slug: str
    assistant_message_id: int
    run_id: str
