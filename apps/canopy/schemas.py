"""Pydantic schemas for the apps.canopy identity-brokering surface."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CanopyStatusOut(StrictModel):
    """GET /api/canopy/status response — drives the frontend feature flag."""

    enabled: bool
    base_url: str
    workspace: str
    agent: str


class CanopyTokenOut(StrictModel):
    """POST /api/canopy/token response — a short-lived delegated token.

    ``expires_at`` is passed through opaquely from canopy-web (an ISO-8601
    string in practice); typed as ``str`` rather than ``datetime`` since this
    surface never parses it, only forwards it to the browser.
    """

    token: str
    expires_at: str


class CanopySessionCreateIn(StrictModel):
    """POST /api/canopy/sessions request body."""

    title: str = ""
    opp_slug: str = ""
    opp_run_id: str = ""
    opp_step_skill: str = ""


class CanopySessionCreateOut(StrictModel):
    """POST /api/canopy/sessions response."""

    id: str
