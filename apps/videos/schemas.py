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
    # ISO-8601 mtime of final.mp4 (None when has_output is False).
    # The header summary uses this to render "rendered Nm ago" so the
    # user knows whether the embedded player is showing a fresh render
    # vs. something from a week ago.
    output_rendered_at: str | None = None
    # ISO-8601 modifiedTime of spec.yaml in Drive. The frontend
    # compares this against output_rendered_at to flag stale renders
    # ("rendered 1h ago · stale (edited since)") so the user knows
    # the embedded player isn't showing their latest saves.
    spec_modified_at: str | None = None
    # Drive webViewLink for the published output.mp4. Null when the
    # run hasn't been published. The editor's kebab menu surfaces this
    # so users can grab a shareable Drive URL without going hunting
    # through the workspace folder.
    output_drive_url: str | None = None
    program_drive_folder_url: str | None = None


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
    """Set when the Redis busy flag is still set but the chain has been
    running longer than the longest-plausible render (8 min) AND no
    new explorer/index.html has been produced. Tells the UI to show
    "render failed — check /render-log" instead of spinning."""
    appears_failed: bool = False


class FeedbackLogOut(StrictModel):
    program_slug: str
    run_id: str
    markdown: str


class RenderLogOut(StrictModel):
    program_slug: str
    run_id: str
    """ISO 8601 of the most recent render-trigger; None if never rendered."""
    started_at: str | None = None
    """Full captured stdout+stderr of the most recent render chain.
    Empty when no render has been triggered (or the log file is missing)."""
    log: str
    size_bytes: int
    """True while the render chain is still running (Redis busy flag).
    Treat the log as a tail in that case — the chain may still be writing."""
    busy: bool


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
        "set-global-template",
        "set-program-name",
    ]
    # set-clip-*
    kind: Literal["scene-clip", "product-beat"] | None = None
    index: int | None = None
    start_seconds: float | None = None
    duration_seconds: float | None = None
    alias: str | None = None
    # set-clip-asset: alternative to `alias`. Looks like
    # "library:video/<subfolder>/<filename>". When the implied alias
    # isn't already in spec.manifest, the server resolves the gdrive
    # id from the workspace's VideoLibraryEntry, inserts a manifest
    # entry, then sets the slot to @alias. One op = swap to any
    # workspace-library clip without a separate "add to manifest"
    # round-trip from the frontend.
    ref: str | None = None
    # set-narration
    beatId: str | None = None
    text: str | None = None
    # set-stat
    path: str | None = None        # "problem" | "impact[N]"
    big: str | None = None
    caption: str | None = None
    source: str | None = None      # explicit "" clears; absence is no-op
    # set-global-template: per-program override of the global brand template.
    # Writes under spec.brand (creates the section if missing). Renderer
    # already prefers spec.brand over programs/_defaults.yaml > brand.
    # Either field is optional — absent means "no change to that field".
    tagline: str | None = None
    cycle_steps: list[str] | None = None  # exactly 4 entries when set
    # set-program-name: rename the program (writes spec.name). The handoff
    # beat ("Here's how that works for <name>") renders this directly and
    # the editor breadcrumb / program list also surface it. Empty string
    # is rejected — every program needs a display name.
    name: str | None = None


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
    intent: str = ""
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


class TemplateMetaPatch(StrictModel):
    name: str | None = None
    description: str | None = None
    intent: str | None = None
    expected_duration_seconds: int | None = None
    intended_audience: str | None = None
    when_to_use: str | None = None


class TemplatePatchIn(StrictModel):
    meta: TemplateMetaPatch | None = None
    skeleton_yaml: str | None = None
    prompt_md: str | None = None
    example_yaml: str | None = None
    example_spec: dict | None = None


class TemplateExampleOut(StrictModel):
    template_id: str
    example_yaml: str


class TemplateExampleSpecOut(StrictModel):
    template_id: str
    spec: dict


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


# ---------------------------------------------------------------------------
# Media library — workspace-scoped curated video + audio assets.
# Separate from LibraryEntryOut / LibraryOut above (which describe a
# per-program clip manifest); these are the cross-program asset pool the
# generator skill browses to pick clips for new specs.
# ---------------------------------------------------------------------------


class MediaLibraryVideoItemOut(StrictModel):
    ref: str
    drive_id: str
    drive_url: str
    filename: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str  # "ok" | "missing-sidecar" | "missing-media" | "malformed-sidecar"


class MediaLibraryVideoSubfolderOut(StrictModel):
    subfolder: str
    items: list[MediaLibraryVideoItemOut]


class MediaLibraryVideoOut(StrictModel):
    subfolders: list[MediaLibraryVideoSubfolderOut]


class MediaLibraryAudioItemOut(StrictModel):
    hash: str
    drive_id: str
    drive_url: str
    voice_id: str | None = None
    model: str | None = None
    text: str | None = None
    duration_sec: float | None = None
    generated_at: str | None = None
    status: str


class MediaLibraryAudioOut(StrictModel):
    items: list[MediaLibraryAudioItemOut]
