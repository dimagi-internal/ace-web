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
    """Response wrapper for GET /api/v2/activity/."""

    items: list[ActivityEntryOut]
    total: int
