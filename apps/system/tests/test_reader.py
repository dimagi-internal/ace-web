"""Tests for the ACE plugin filesystem reader."""

import pytest

from apps.system.reader import load_agent_detail, load_skill_detail, load_system_overview


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a minimal ACE plugin file tree."""
    # VERSION
    (tmp_path / "VERSION").write_text("0.1.11\n")

    # skills/idea-to-idd/SKILL.md
    skill_dir = tmp_path / "skills" / "idea-to-idd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: idea-to-idd\n"
        "description: Iterate on an idea to produce a well-specified IDD.\n"
        "---\n"
        "\n"
        "# Idea to IDD\n"
        "\n"
        "## Process\n"
        "\n"
        "1. Read the initial idea.\n"
        "2. Draft the IDD.\n"
    )

    # skills/email-communicator/SKILL.md  (utility, not in registry)
    util_dir = tmp_path / "skills" / "email-communicator"
    util_dir.mkdir(parents=True)
    (util_dir / "SKILL.md").write_text(
        "---\n"
        "name: email-communicator\n"
        "description: Send and receive email.\n"
        "---\n"
        "\n"
        "# Email Communicator\n"
    )

    # agents/app-builder.md
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "app-builder.md").write_text(
        "---\n"
        "name: app-builder\n"
        "description: Orchestrates the app building phase.\n"
        "model: inherit\n"
        "---\n"
        "\n"
        "# App Builder Agent\n"
        "\n"
        "## Workflow\n"
    )

    # lib/artifact-manifest.ts
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "artifact-manifest.ts").write_text(
        "export const ARTIFACT_MANIFEST: readonly ArtifactEntry[] = [\n"
        "  {\n"
        "    path: 'idd.md',\n"
        "    producedBy: 'idea-to-idd',\n"
        "    consumedBy: ['idd-to-learn-app'],\n"
        "    phase: 'build',\n"
        "    required: true,\n"
        "    description: 'IDD',\n"
        "  },\n"
        "] as const;\n"
    )

    return tmp_path


class TestLoadSystemOverview:
    def test_loads_registered_skill(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        skill_names = [s["name"] for s in overview["skills"]]
        assert "idea-to-idd" in skill_names

    def test_registered_skill_has_ordinal(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        idd = next(s for s in overview["skills"] if s["name"] == "idea-to-idd")
        assert idd["ordinal"] == 1
        assert idd["phase"] == "app-building"
        assert idd["has_judge"] is True
        assert idd["is_gate"] is True

    def test_display_name_from_h1(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        idd = next(s for s in overview["skills"] if s["name"] == "idea-to-idd")
        assert idd["display_name"] == "Idea to IDD"

    def test_utility_skill_included(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        names = [s["name"] for s in overview["skills"]]
        assert "email-communicator" in names

    def test_utility_skill_has_no_ordinal(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        ec = next(s for s in overview["skills"] if s["name"] == "email-communicator")
        assert ec["ordinal"] is None
        assert ec["phase"] is None

    def test_agents_loaded(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        assert len(overview["agents"]) == 1
        assert overview["agents"][0]["name"] == "app-builder"

    def test_artifacts_loaded(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        assert len(overview["artifacts"]) == 1
        assert overview["artifacts"][0]["path"] == "idd.md"

    def test_skill_has_artifacts(self, plugin_dir):
        overview = load_system_overview(str(plugin_dir))
        idd = next(s for s in overview["skills"] if s["name"] == "idea-to-idd")
        assert len(idd["artifacts_produced"]) == 1
        assert idd["artifacts_produced"][0]["path"] == "idd.md"

    def test_missing_plugin_dir(self, tmp_path):
        overview = load_system_overview(str(tmp_path / "nonexistent"))
        assert overview["skills"] == []
        assert overview["agents"] == []
        assert overview["artifacts"] == []
        assert overview["warning"] is not None


class TestLoadSkillDetail:
    def test_includes_body_markdown(self, plugin_dir):
        detail = load_skill_detail(str(plugin_dir), "idea-to-idd")
        assert detail is not None
        assert "## Process" in detail["body_markdown"]
        assert detail["name"] == "idea-to-idd"

    def test_unknown_skill_returns_none(self, plugin_dir):
        detail = load_skill_detail(str(plugin_dir), "nonexistent")
        assert detail is None


class TestLoadAgentDetail:
    def test_includes_body_markdown(self, plugin_dir):
        detail = load_agent_detail(str(plugin_dir), "app-builder")
        assert detail is not None
        assert "## Workflow" in detail["body_markdown"]

    def test_unknown_agent_returns_none(self, plugin_dir):
        detail = load_agent_detail(str(plugin_dir), "nonexistent")
        assert detail is None
