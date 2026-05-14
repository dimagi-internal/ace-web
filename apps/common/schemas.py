"""Cross-cutting Pydantic schemas reused across apps.

Conventions:
- Output schemas end in `Out`, input in `In`, patches in `Patch`.
- IDs that are slugs use `str`; numeric PKs use `int`.
- All datetimes are timezone-aware ISO-8601 (Pydantic v2 default).
- Optional fields use `T | None = None`; required fields have no default.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # request bodies reject unknown fields
        from_attributes=True,  # allow ORM-instance hydration
        str_strip_whitespace=True,
    )


class TimestampMixin(BaseModel):
    created_at: dt.datetime
    updated_at: dt.datetime


class UserRefOut(StrictModel):
    """Minimal user reference for embedding in other responses."""

    id: int
    email: EmailStr
    display_name: str | None = None


class WorkspaceRefOut(StrictModel):
    """Minimal workspace reference for embedding.

    Note: the public field name is `name` (not `display_name`).
    The view layer maps workspace.display_name -> name when populating.
    """

    slug: str
    name: str


class HealthCheckOut(StrictModel):
    """One subsystem check result."""

    ok: bool
    error: str | None = None


class HealthOut(StrictModel):
    """GET /api/health response.

    ``healthy`` is True when all subsystem checks pass.
    ``status`` is ``"ok"`` or ``"unhealthy"`` for human readability.
    """

    status: str
    healthy: bool
    checks: dict[str, HealthCheckOut]
