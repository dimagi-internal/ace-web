"""Pydantic v2 schemas for the activity surface.

The activity feed returns two event kinds:

- ``"chat"``    — a Session creation event from Postgres.
- ``"verdict"`` — a judge verdict event from Google Drive.

The ``meta`` dict is heterogeneous per kind:
  chat    → {source, status, message_count}
  verdict → {score, passed}

Using ``dict[str, Any]`` for ``meta`` captures this cleanly without a
Union discriminator.  ``ActivityFeedOut`` wraps the list with a total
count (mirrors what the DRF view returns in ``{"items": [...], "total": N}``).
"""
from __future__ import annotations

from typing import Any, Literal

from apps.common.schemas import StrictModel

ActivityKind = Literal["chat", "verdict"]


class ActivityEntryOut(StrictModel):
    """One entry in the workspace activity feed."""

    kind: ActivityKind
    ts: str  # ISO-8601 string; source may be a datetime or a pre-formatted str
    opp_slug: str | None = None
    step_skill: str | None = None
    title: str
    # session_slug is only present on "chat" events
    session_slug: str | None = None
    # meta carries kind-specific fields; heterogeneous so typed as dict
    meta: dict[str, Any]


class ActivityFeedOut(StrictModel):
    """Response wrapper for GET /api/activity/."""

    items: list[ActivityEntryOut]
    total: int


class WorkspaceActivityRowOut(StrictModel):
    """One row in the 'what's running across the workspace' view.

    All fields are observable facts (Drive content, ORM rows, derived
    URLs). NO inferred liveness claims — the caller renders timestamps
    and lets the user decide what's actually alive. See the design doc
    `docs/specs/2026-05-16-workspace-activity-view-design.md`.
    """

    opp_slug: str
    opp_display_name: str
    run_id: str
    last_activity_at: str | None = None
    current_phase_name: str | None = None
    current_phase_display: str | None = None
    current_step_name: str | None = None
    current_step_display: str | None = None
    lifecycle_status: str
    last_actor: str | None = None
    source_hint: Literal["ace-web", "drive-only"]
    source_actor_email: str | None = None
    phase_url: str


class WorkspaceActivityOut(StrictModel):
    """Response wrapper for GET /api/w/{slug}/activity/runs."""

    rows: list[WorkspaceActivityRowOut]
    # server_now lets the frontend compute "Nm ago" deltas consistently
    # regardless of client-clock skew.
    server_now: str
