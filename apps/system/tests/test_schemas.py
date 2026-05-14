"""Round-trip tests for apps.system.schemas."""
from __future__ import annotations

from apps.system.schemas import (
    AgentDetailOut,
    CliDiagOut,
    McpServerOut,
    McpToolOut,
    SkillDetailOut,
    SkillSummaryOut,
    SystemOverviewOut,
    VersionOut,
)


def test_skill_summary_out_minimal():
    skill = SkillSummaryOut(name="idea-to-pdd", display_name="Idea To Pdd")
    assert skill.has_judge is False
    assert skill.phase is None
    assert skill.artifacts_produced == []


def test_skill_detail_out_inherits_summary():
    detail = SkillDetailOut(
        name="app-build",
        display_name="App Build",
        phase="build",
        ordinal=3,
        has_judge=True,
        body_markdown="# App Build\n\nSome content",
    )
    d = detail.model_dump()
    assert d["body_markdown"].startswith("# App Build")
    assert d["has_judge"] is True


def test_system_overview_out_empty_plugin():
    """Shape returned when ACE plugin is absent."""
    overview = SystemOverviewOut(
        skills=[],
        agents=[],
        artifacts=[],
        phases=[],
        mcps=[],
        warning="ACE plugin not found at /app/vendor/ace",
    )
    assert overview.warning is not None
    assert overview.skills == []


def test_version_out_round_trip():
    v = VersionOut(
        plugin_found=True,
        plugin_version="2.1.0",
        remote_version="2.2.0",
        update_available=True,
        plugin_path="/app/vendor/ace",
    )
    assert v.update_available is True
    assert v.plugin_version == "2.1.0"


def test_cli_diag_out_extra_fields_allowed():
    """CliDiagOut accepts extra keys from the subprocess diagnostic."""
    diag = CliDiagOut(
        elapsed_seconds=4.2,
        returncode=0,
        stream_event_count=12,
        some_extra_field="should be allowed",  # type: ignore[call-arg]
    )
    assert diag.elapsed_seconds == 4.2
    # extra fields preserved via extra="allow"
    assert diag.model_extra.get("some_extra_field") == "should be allowed"  # type: ignore[union-attr]


def test_mcp_server_out():
    tool = McpToolOut(name="my_tool", description="does stuff", used_by=["skill-a"])
    server = McpServerOut(name="nova", source_file="mcp/nova.ts", tools=[tool])
    d = server.model_dump()
    assert d["tools"][0]["name"] == "my_tool"
    assert d["warning"] is None


def test_agent_detail_out():
    agent = AgentDetailOut(
        name="ace:design-review",
        description="Reviews designs",
        model="claude-opus-4-7",
        body_markdown="# Design Review\n\nBody here",
    )
    assert agent.body_markdown.startswith("# Design Review")
