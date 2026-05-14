"""Pydantic v2 schemas for the sessions surface.

Conventions (matches apps.common.schemas, apps.workspaces.schemas, etc.):
- ``Out`` suffixed shapes: read-only API responses.
- ``In`` suffixed shapes: POST / creation request bodies.
- ``Patch`` suffixed shapes: PATCH request bodies (all fields optional;
  use ``model_dump(exclude_unset=True)`` to get only provided fields).
- ``str`` for slugs / text identifiers; ``int`` for numeric PKs.
- Timestamps use ``dt.datetime``; Pydantic v2 coerces ISO-8601 strings.

For the recursive ``StructureNodeOut``, ``from __future__ import annotations``
is mandatory so Pydantic can resolve the forward reference on the ``children``
field. ``StructureNodeOut.model_rebuild()`` is called at module bottom to
trigger the deferred forward-reference resolution.

``CostBreakdownOut`` mirrors the exact JSON shape produced by
``apps/ingest/cost_aggregator.py::aggregate()``.  ``totals`` is nullable
so that the "empty breakdown" sentinel (schema_version=0, totals=None) is
valid without a special-case branch.  The model uses ``extra="allow"`` on
``CostInvocationOut`` to remain tolerant of extra keys that the aggregator
may add in future schema versions without a breaking change here.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import ConfigDict, Field

from apps.common.schemas import StrictModel

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

SessionStatus = Literal["active", "archived", "imported"]
BackendKind = Literal["cli", "api", "mcp"]
SessionSource = Literal["web", "upload"]
MessageRole = Literal["user", "assistant", "system", "tool_use", "tool_result"]
MessageStatus = Literal["pending", "streaming", "complete", "error"]
ParticipantRole = Literal["owner", "editor", "viewer"]
StructureStatus = Literal["ok", "error", "incomplete"]
StructureKind = Literal["phase", "skill", "tool", "parallel_group"]


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class MessageOut(StrictModel):
    """Single message in a session transcript."""

    id: int
    turn_index: int
    role: MessageRole
    content: Any  # JSON blob — shape varies by role / CLI event type
    plaintext: str
    status: MessageStatus
    error_detail: str | None = None
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    created_at: dt.datetime


# ---------------------------------------------------------------------------
# Participant
# ---------------------------------------------------------------------------


class ParticipantOut(StrictModel):
    """A user who can see / interact with a session."""

    user_id: int
    email: str
    display_name: str
    role: ParticipantRole
    joined_at: dt.datetime
    last_seen_at: dt.datetime | None = None


# ---------------------------------------------------------------------------
# Session list + detail
# ---------------------------------------------------------------------------


class SessionListOut(StrictModel):
    """Lighter shape returned by GET /api/sessions (list view).

    Includes computed fields (message_count, preview) but omits the inline
    message list to keep list payloads small.
    """

    slug: str
    title: str
    status: SessionStatus
    backend_kind: BackendKind
    source: SessionSource
    cli_session_id: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    message_count: int = Field(ge=0)
    preview: str = ""

    # Opp linkage — non-empty when session was launched via "Discuss in chat"
    # or imported via /ace:run --ace-web-url.  Empty strings on plain chats.
    opp_slug: str = ""
    opp_run_id: str = ""
    opp_step_skill: str = ""
    # Human-readable display names resolved server-side
    opp_display_name: str = ""
    opp_step_skill_display: str = ""


class SessionOut(SessionListOut):
    """Full session detail — includes inline message list.

    Returned by GET /api/sessions/<slug>.
    """

    messages: list[MessageOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Input / patch schemas
# ---------------------------------------------------------------------------


class SessionCreateIn(StrictModel):
    """POST /api/sessions — create a new session."""

    title: str = ""


class SessionPatchIn(StrictModel):
    """PATCH /api/sessions/<slug> — partial update.

    Only ``title`` and ``status`` are mutable by the owner.
    Use ``model_dump(exclude_unset=True)`` to get only the fields supplied.
    """

    title: str | None = None
    status: SessionStatus | None = None


# ---------------------------------------------------------------------------
# Turn state  (GET /api/sessions/<slug>/turn-state)
# ---------------------------------------------------------------------------


class TurnStateCliOut(StrictModel):
    """CLIBackend introspection state for a single session subprocess."""

    alive: bool
    pid: int | None = None
    elapsed_s: float
    last_active_age_s: float
    credential_source: str | None = None
    cli_session_id: str | None = None
    spawned_with_resume: bool


class TurnStateOut(StrictModel):
    """Cheap polling shape: is a turn currently running on the server?

    ``running`` reflects THIS worker process only (see view docstring for
    multi-worker caveat).  ``cli`` is null when no long-lived SessionProcess
    has been spawned for this slug yet.
    """

    running: bool
    last_message_at: dt.datetime | None = None
    cli: TurnStateCliOut | None = None


# ---------------------------------------------------------------------------
# Cost breakdown  (GET /api/sessions/<slug>/cost)
# ---------------------------------------------------------------------------


class TokensOut(StrictModel):
    """Token usage counts — shared by cost and structure schemas."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


class CostTotalsOut(StrictModel):
    """Session-level totals produced by cost_aggregator."""

    wall_time_seconds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_is_partial: bool = False
    cache_hit_ratio: float = 0.0


class CostInvocationOut(StrictModel):
    """Single skill invocation within the breakdown.

    Uses ``extra="allow"`` so future aggregator fields (e.g. tool-call counts,
    retry metadata) don't invalidate existing saved breakdowns.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, str_strip_whitespace=True)

    start_ts: dt.datetime | None = None
    wall_time_seconds: int = 0
    estimated_cost_usd: float = 0.0
    cost_is_partial: bool = False
    incomplete: bool = False
    tokens: TokensOut = Field(default_factory=TokensOut)


class CostSkillOut(StrictModel):
    """Per-skill summary within a phase."""

    skill_name: str
    skill_display: str = ""
    invocation_count: int = 0
    wall_time_seconds: int = 0
    estimated_cost_usd: float = 0.0
    cost_is_partial: bool = False
    tokens: TokensOut = Field(default_factory=TokensOut)
    invocations: list[CostInvocationOut] = Field(default_factory=list)


class CostPhaseOut(StrictModel):
    """Per-phase summary within a cost breakdown."""

    phase_name: str
    phase_display: str = ""
    phase_ordinal: int = 0
    wall_time_seconds: int = 0
    estimated_cost_usd: float = 0.0
    cost_is_partial: bool = False
    tokens: TokensOut = Field(default_factory=TokensOut)
    skills: list[CostSkillOut] = Field(default_factory=list)


class CostBreakdownOut(StrictModel):
    """Full cost breakdown — mirrors Session.cost_breakdown JSONField shape.

    ``totals`` is nullable: the view returns ``totals=None, phases=[]`` for
    sessions with no cost data (schema_version=0 legacy uploads).
    ``computed_at`` is absent on the v0 empty sentinel.
    """

    schema_version: int
    computed_at: dt.datetime | None = None
    totals: CostTotalsOut | None = None
    phases: list[CostPhaseOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Structure tree  (GET /api/sessions/<slug>/structure)
# ---------------------------------------------------------------------------


class StructureNodeOut(StrictModel):
    """Recursive node in the session structure tree.

    The ``kind`` discriminator determines which optional fields are populated:
    - ``phase``        : name, display, ordinal, wall_time_seconds,
                         estimated_cost_usd, cost_is_partial, tokens, status,
                         children
    - ``skill``        : name, display, is_subagent, started_at,
                         wall_time_seconds, estimated_cost_usd, cost_is_partial,
                         tokens, status, children
    - ``tool``         : tool_use_id, tool_name, label, started_at,
                         wall_time_seconds, status, content_preview, children=[]
    - ``parallel_group``: started_at, wall_time_seconds, children

    A single polymorphic model is used (rather than separate models) so the
    recursive ``children`` list can hold any of the four node types without
    requiring a Union discriminator throughout the tree.  Fields not relevant
    to a given ``kind`` are left as None.

    ``StructureNodeOut.model_rebuild()`` at module bottom is required because
    the forward reference ``list["StructureNodeOut"]`` is resolved lazily.
    """

    kind: StructureKind

    # Phase / skill / parallel_group metadata
    name: str | None = None          # phase name or skill slug
    display: str | None = None       # human display label
    ordinal: int | None = None       # phase ordinal (phase nodes only)

    # Skill-specific
    is_subagent: bool | None = None

    # Tool-specific
    tool_use_id: str | None = None
    tool_name: str | None = None
    label: str | None = None         # short human label for the tool call
    content_preview: str | None = None

    # Timing / cost (phase, skill, parallel_group, tool)
    started_at: dt.datetime | None = None
    wall_time_seconds: int = 0
    estimated_cost_usd: float | None = None
    cost_is_partial: bool | None = None
    tokens: TokensOut | None = None

    # Status (phase, skill, tool)
    status: StructureStatus | None = None

    # Children — recursive (any node type)
    children: list[StructureNodeOut] = Field(default_factory=list)


# Resolve the forward reference on ``children``.
StructureNodeOut.model_rebuild()


# ---------------------------------------------------------------------------
# Share tokens
# ---------------------------------------------------------------------------


class ShareTokenOut(StrictModel):
    """Public view of a ShareToken.

    ``url`` is only present in POST /api/sessions/<slug>/share-tokens
    responses (where the server builds the full URL); GET list responses
    omit it.  ``revoked_at`` is null for active tokens.
    """

    token: str
    created_at: dt.datetime
    revoked_at: dt.datetime | None = None
    url: str | None = None
