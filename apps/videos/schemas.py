"""Pydantic schemas for the /api/w/<slug>/videos surface.

The data model mirrors opps/runs: a Program is a top-level folder
(``programs/<slug>/``) and Runs are subfolders (``runs/run-001/``,
``runs/run-002/``, …) each containing a ``spec.yaml`` and an
``output.mp4``. Editing mutates a specific run's spec.yaml; forking
copies it into a new run dir.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from apps.common.schemas import StrictModel

# ---------------------------------------------------------------------------
# Read-side
# ---------------------------------------------------------------------------


class ProgramCardOut(StrictModel):
    """One program in the list view — surfaces the *latest* run's metadata."""

    slug: str
    name: str
    tagline: str | None = None
    country_focus: str | None = None
    status: str | None = None
    program_url: str | None = None
    manifest_count: int = Field(ge=0)
    has_explorer_build: bool
    latest_run_id: str | None = None
    run_count: int = Field(ge=0)


class RunSummaryOut(StrictModel):
    """One run inside a program."""

    run_id: str
    has_output: bool
    has_explorer_build: bool


class ProgramDetailOut(StrictModel):
    slug: str
    name: str
    tagline: str | None = None
    country_focus: str | None = None
    status: str | None = None
    program_url: str | None = None
    runs: list[RunSummaryOut]


class RunDetailOut(StrictModel):
    """One run's full payload — spec metadata + URLs for the embedded media."""

    program_slug: str
    run_id: str
    name: str
    manifest_count: int = Field(ge=0)
    has_output: bool
    has_explorer_build: bool
    explorer_url: str  # /api/w/<ws>/videos/programs/<slug>/runs/<run>/explorer.html
    yaml_path: str  # repo-relative for surfacing in the UI
    spec: dict[str, Any] | None = None  # full parsed spec.yaml — feeds the beat editor


class LibraryEntryOut(StrictModel):
    alias: str
    source_path: str | None = None
    duration_seconds: float | None = None
    resolution: str | None = None
    used_in: list[str] = Field(default_factory=list)


class LibraryOut(StrictModel):
    entries: list[LibraryEntryOut]


class RenderStatusOut(StrictModel):
    program_slug: str
    run_id: str
    busy: bool
    started_at: str | None = None


class FeedbackLogOut(StrictModel):
    program_slug: str
    run_id: str
    markdown: str


# ---------------------------------------------------------------------------
# Write-side
# ---------------------------------------------------------------------------


class ClipEditIn(StrictModel):
    op: Literal[
        "set-clip-start",
        "set-clip-trim",
        "set-clip-asset",
        "set-narration",
        "set-stat",
    ]
    # set-clip-*
    kind: Literal["scene-clip", "product-beat"] | None = None
    index: int | None = None
    start_seconds: float | None = None
    duration_seconds: float | None = None
    alias: str | None = None
    # set-narration
    beatId: str | None = None
    text: str | None = None
    # set-stat
    path: str | None = None        # "problem" | "impact[N]"
    big: str | None = None
    caption: str | None = None
    source: str | None = None      # explicit "" clears; absence is no-op


class ClipEditOut(StrictModel):
    ok: bool
    message: str
    rerender_triggered: bool


class EditBatchIn(StrictModel):
    ops: list[ClipEditIn] = Field(min_length=1, max_length=200)


class EditBatchOut(StrictModel):
    ok: bool
    applied: int
    message: str


class FeedbackPostIn(StrictModel):
    scope: Literal["global", "beat"] = "global"
    beatId: str | None = None
    timestampSec: float | None = None
    note: str


class FeedbackPostOut(StrictModel):
    ok: bool
    timestamp: str


class BuildTriggerIn(StrictModel):
    mode: Literal["render", "build-only"] = "render"


class BuildTriggerOut(StrictModel):
    ok: bool
    triggered: bool
    mode: Literal["render", "build-only"]
    message: str


class CopyRunOut(StrictModel):
    """POST /programs/<slug>/runs → new run id."""

    program_slug: str
    new_run_id: str
    copied_from: str


# ---------------------------------------------------------------------------
# Templates — MCP-callable surface used by an agent in a Claude session
# to discover available templates + post a generated spec back.
# ---------------------------------------------------------------------------


class TemplateMetaOut(StrictModel):
    id: str
    name: str
    description: str
    expected_duration_seconds: int
    intended_audience: str
    when_to_use: str


class TemplateBundleOut(StrictModel):
    """Full template payload — agent reads `prompt_md` and follows it,
    fills the `skeleton_yaml` placeholders, and posts the result back
    via POST /programs.
    """

    meta: TemplateMetaOut
    skeleton_yaml: str
    prompt_md: str


class CreateProgramIn(StrictModel):
    """POST /programs body. The agent generates the full spec.yaml
    (string) by following the template's prompt and posts it here. The
    server only validates structure + slug uniqueness; the agent owns
    content quality.
    """

    slug: str
    spec_yaml: str  # complete YAML body for spec.yaml


class CreateProgramOut(StrictModel):
    program_slug: str
    run_id: str  # always "run-001" — programs start at one run
    spec_path: str  # repo-relative path that was written
    message: str
