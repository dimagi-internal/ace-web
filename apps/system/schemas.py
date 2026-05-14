"""Pydantic v2 schemas for the System Overview surface.

The System Overview tab reads from the bundled ACE plugin at
``ACE_PLUGIN_PATH`` via ``apps.system.reader.load_system_overview``.
Shapes are derived directly from the dicts that reader.py returns.

``CliDiagOut`` is complex and its shape evolves (the diagnostic response
embeds raw subprocess output, plugin probes, etc.) — it uses
``extra="allow"`` so future additions don't break existing callers.
Same for ``ArtifactOut`` and ``McpToolOut`` whose inner shapes can grow
as the plugin expands.
"""
from __future__ import annotations

from typing import Any

from pydantic import ConfigDict

from apps.common.schemas import StrictModel

# ── Artifact manifest ────────────────────────────────────────────────────────


class ArtifactOut(StrictModel):
    """One entry in the plugin's artifact-manifest.ts."""

    path: str
    description: str = ""
    required: bool = False
    produced_by: str | None = None
    consumed_by: list[str] = []


# ── Skill summary ────────────────────────────────────────────────────────────


class SkillArtifactRowOut(StrictModel):
    """Minimal artifact reference embedded in a skill summary."""

    path: str
    description: str = ""
    required: bool = False


class SkillSummaryOut(StrictModel):
    """One skill in the bundled ACE plugin — list-level shape.

    Returned as elements of ``SystemOverviewOut.skills``.
    """

    name: str
    display_name: str
    description: str = ""
    ordinal: int | None = None
    phase: str | None = None
    has_judge: bool = False
    is_recurring: bool = False
    primary_output: str | None = None
    artifacts_produced: list[SkillArtifactRowOut] = []
    artifacts_consumed: list[SkillArtifactRowOut] = []


class SkillDetailOut(SkillSummaryOut):
    """Single-skill detail — adds full markdown body.

    Returned by GET /api/system/skills/<name>.
    """

    body_markdown: str = ""


# ── Agent summary ────────────────────────────────────────────────────────────


class AgentSummaryOut(StrictModel):
    """One agent declared in the plugin's agents/ directory."""

    name: str
    description: str = ""
    model: str = ""


class AgentDetailOut(AgentSummaryOut):
    """Single-agent detail — adds full markdown body.

    Returned by GET /api/system/agents/<name>.
    """

    body_markdown: str = ""


# ── Phase summary ────────────────────────────────────────────────────────────


class PhaseSummaryOut(StrictModel):
    """One phase declared across the plugin's agent frontmatter."""

    name: str
    display_name: str
    ordinal: int
    agent: str


# ── MCP tool ────────────────────────────────────────────────────────────────


class McpToolOut(StrictModel):
    """One tool exposed by a plugin MCP server.

    ``used_by`` lists skill slugs whose body text mentions this tool name.
    Uses ``extra="allow"`` because the parser may add more metadata fields.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, str_strip_whitespace=True)

    name: str
    description: str = ""
    used_by: list[str] = []


class McpServerOut(StrictModel):
    """One MCP server declared in the plugin's plugin.json."""

    name: str
    source_file: str | None = None
    tools: list[McpToolOut] = []
    warning: str | None = None


# ── Version ──────────────────────────────────────────────────────────────────


class VersionOut(StrictModel):
    """Plugin version + remote comparison.

    Returned by GET /api/system/version and embedded in SystemOverviewOut.
    ``update_available`` is null when the remote check failed (network error
    or rate limit).
    """

    plugin_found: bool
    plugin_version: str | None = None
    remote_version: str | None = None
    update_available: bool | None = None
    plugin_path: str = ""


# ── Top-level overview ───────────────────────────────────────────────────────


class SystemOverviewOut(StrictModel):
    """Full system snapshot returned by GET /api/system/overview."""

    skills: list[SkillSummaryOut]
    agents: list[AgentSummaryOut]
    artifacts: list[ArtifactOut]
    phases: list[PhaseSummaryOut]
    mcps: list[McpServerOut]
    plugin_version: str | None = None
    remote_version: str | None = None
    update_available: bool | None = None
    warning: str | None = None


# ── CLI diagnostic ───────────────────────────────────────────────────────────


class CliDiagOut(StrictModel):
    """Response from POST /api/system/cli-diag.

    The shape is intentionally open (``extra="allow"``) because the
    diagnostic response embeds raw subprocess output, plugin probes, and
    environment snapshots whose exact keys evolve with the CLI version.
    Consumers should access known top-level keys (elapsed_seconds,
    returncode, init_summary) and treat the rest as opaque diagnostic data.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, str_strip_whitespace=True)

    elapsed_seconds: float
    returncode: int
    stream_event_count: int = 0
    stderr_tail: str = ""
    init_summary: dict[str, Any] | None = None
    tool_uses: list[dict[str, Any]] = []
