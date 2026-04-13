"""Tests for pure parsing functions — frontmatter and artifact manifest."""

from apps.system.parsers import parse_artifact_manifest, parse_frontmatter

# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_basic_frontmatter(self):
        text = "---\nname: My Skill\ndescription: Does things\n---\nBody text here."
        meta, body = parse_frontmatter(text)
        assert meta == {"name": "My Skill", "description": "Does things"}
        assert body == "Body text here."

    def test_no_frontmatter(self):
        text = "Just a regular markdown file.\nWith two lines."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_string(self):
        meta, body = parse_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_agent_frontmatter_with_model_field(self):
        text = (
            "---\nname: CodeReviewer\nmodel: claude-sonnet-4-20250514\n"
            "role: reviewer\n---\n\nAgent body."
        )
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "CodeReviewer"
        assert meta["model"] == "claude-sonnet-4-20250514"
        assert meta["role"] == "reviewer"
        assert body == "\nAgent body."

    def test_frontmatter_with_list_values(self):
        text = "---\nname: Skill\ntags:\n  - alpha\n  - beta\n---\nContent."
        meta, body = parse_frontmatter(text)
        assert meta["tags"] == ["alpha", "beta"]
        assert body == "Content."

    def test_only_frontmatter_no_body(self):
        text = "---\nname: Lonely\n---\n"
        meta, body = parse_frontmatter(text)
        assert meta == {"name": "Lonely"}
        assert body == ""

    def test_triple_dashes_in_body_not_confused(self):
        """A `---` inside the body (after the closing delimiter) should not
        trigger a second parse."""
        text = "---\ntitle: Doc\n---\nSome text\n---\nMore text"
        meta, body = parse_frontmatter(text)
        assert meta == {"title": "Doc"}
        assert "---" in body  # the body's own dashes are preserved


# ---------------------------------------------------------------------------
# parse_artifact_manifest
# ---------------------------------------------------------------------------

SAMPLE_TS = """\
import { ArtifactManifest } from './types';

export const ARTIFACT_MANIFEST = [
  {
    skillSlug: 'idea-to-idd',
    producedBy: 'idea-to-idd',
    consumedBy: ['idd-to-learn-app', 'idd-to-deliver-app'],
    phase: 'setup',
    artifactType: 'idd',
    label: 'Intervention Design Doc',
  },
  {
    skillSlug: 'idd-to-learn-app',
    producedBy: 'idd-to-learn-app',
    consumedBy: ['app-deploy'],
    phase: 'build',
    artifactType: 'learn-app',
    label: 'Learn App',
  },
] as const;
"""


class TestParseArtifactManifest:
    def test_parse_two_entry_sample(self):
        entries = parse_artifact_manifest(SAMPLE_TS)
        assert len(entries) == 2

        first = entries[0]
        assert first["skill_slug"] == "idea-to-idd"
        assert first["produced_by"] == "idea-to-idd"
        assert first["consumed_by"] == ["idd-to-learn-app", "idd-to-deliver-app"]
        assert first["artifact_type"] == "idd"
        assert first["label"] == "Intervention Design Doc"

        second = entries[1]
        assert second["skill_slug"] == "idd-to-learn-app"
        assert second["produced_by"] == "idd-to-learn-app"
        assert second["consumed_by"] == ["app-deploy"]
        assert second["artifact_type"] == "learn-app"

    def test_phase_normalization(self):
        entries = parse_artifact_manifest(SAMPLE_TS)
        assert entries[0]["phase"] == "connect-setup"  # setup → connect-setup
        assert entries[1]["phase"] == "app-building"    # build → app-building

    def test_all_phase_mappings(self):
        """Verify each short phase name normalizes correctly."""
        template = (
            "export const ARTIFACT_MANIFEST = [\n"
            "  {{ skillSlug: 'a', phase: '{phase}', producedBy: 'a',"
            " consumedBy: [], artifactType: 'x', label: 'X' }},\n"
            "] as const;\n"
        )
        mappings = {
            "build": "app-building",
            "setup": "connect-setup",
            "operate": "llo-management",
            "closeout": "closeout",
        }
        for short, expected in mappings.items():
            entries = parse_artifact_manifest(template.format(phase=short))
            assert entries[0]["phase"] == expected, f"{short} should map to {expected}"

    def test_empty_manifest(self):
        ts = "export const ARTIFACT_MANIFEST = [] as const;"
        assert parse_artifact_manifest(ts) == []

    def test_bad_input_returns_empty(self):
        assert parse_artifact_manifest("not typescript at all") == []
        assert parse_artifact_manifest("") == []

    def test_single_quotes_handled(self):
        """The parser must handle single-quoted TS strings."""
        ts = (
            "export const ARTIFACT_MANIFEST = [\n"
            "  { skillSlug: 'test', producedBy: 'test', consumedBy: [],"
            " phase: 'closeout', artifactType: 'report', label: 'Report' },\n"
            "] as const;\n"
        )
        entries = parse_artifact_manifest(ts)
        assert len(entries) == 1
        assert entries[0]["skill_slug"] == "test"
        assert entries[0]["phase"] == "closeout"

    def test_comments_stripped(self):
        ts = (
            "export const ARTIFACT_MANIFEST = [\n"
            "  // This is a comment\n"
            "  { skillSlug: 'a', producedBy: 'a', consumedBy: [],"
            " phase: 'build', artifactType: 'x', label: 'X' },\n"
            "] as const;\n"
        )
        entries = parse_artifact_manifest(ts)
        assert len(entries) == 1
        assert entries[0]["skill_slug"] == "a"
