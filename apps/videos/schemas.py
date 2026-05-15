"""Pydantic schemas for the /api/w/<slug>/videos surface.

The clip-explorer is a Node tsx tool that lives outside Django at
``video-production/connect-videos/``. Programs are YAML files on disk
under that tree; ace-web reads through to them (analogous to opps
reading through to Drive). Each program declares its owning workspace
via a top-level ``workspace: <slug>`` field.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from apps.common.schemas import StrictModel

# ---------------------------------------------------------------------------
# Read-side
# ---------------------------------------------------------------------------


class ProgramCardOut(StrictModel):
    """One program in the list view."""

    slug: str
    name: str
    tagline: str | None = None
    country_focus: str | None = None
    status: str | None = None
    program_url: str | None = None
    manifest_count: int = Field(ge=0)
    has_explorer_build: bool


class ProgramDetailOut(StrictModel):
    slug: str
    name: str
    tagline: str | None = None
    country_focus: str | None = None
    status: str | None = None
    program_url: str | None = None
    manifest_count: int = Field(ge=0)
    has_explorer_build: bool
    explorer_url: str  # /api/w/<ws>/videos/programs/<slug>/explorer.html
    yaml_path: str  # relative to ACE_VIDEOS_ROOT, for surfacing in the UI


class LibraryEntryOut(StrictModel):
    """One entry in the clip library (used by the explorer drawer)."""

    alias: str
    source_path: str | None = None
    duration_seconds: float | None = None
    resolution: str | None = None
    used_in: list[str] = Field(default_factory=list)


class LibraryOut(StrictModel):
    entries: list[LibraryEntryOut]


class RenderStatusOut(StrictModel):
    """Background-render busy flag."""

    program_slug: str
    busy: bool
    started_at: str | None = None  # ISO-8601


class FeedbackLogOut(StrictModel):
    """Raw markdown contents of the per-program feedback log."""

    program_slug: str
    markdown: str


# ---------------------------------------------------------------------------
# Write-side
# ---------------------------------------------------------------------------


class ClipEditIn(StrictModel):
    """POST /edit body — one of four ops over a program's YAML.

    Mirrors the existing Node tsx server ops in
    ``video-production/connect-videos/scripts/explore.ts::applyEdit``.
    """

    op: Literal["set-clip-start", "set-clip-trim", "set-clip-asset", "set-narration"]
    kind: Literal["scene-clip", "product-beat"] | None = None
    index: int | None = None
    start_seconds: float | None = None
    duration_seconds: float | None = None
    beatId: str | None = None  # narration target
    text: str | None = None  # narration body
    alias: str | None = None  # asset swap (without the leading @)


class ClipEditOut(StrictModel):
    ok: bool
    message: str
    rerender_triggered: bool


class FeedbackPostIn(StrictModel):
    scope: Literal["global", "beat"] = "global"
    beatId: str | None = None
    timestampSec: float | None = None
    note: str


class FeedbackPostOut(StrictModel):
    ok: bool
    timestamp: str  # ISO-8601 truncated to seconds


class BuildTriggerIn(StrictModel):
    """POST /build body — opt into the full re-render or just rebuild the
    explorer HTML against the current YAML."""

    mode: Literal["render", "build-only"] = "render"


class BuildTriggerOut(StrictModel):
    ok: bool
    triggered: bool
    mode: Literal["render", "build-only"]
    message: str
