"""Tests for pure parsing functions — frontmatter and artifact manifest."""

from apps.system.parsers import parse_artifact_manifest, parse_frontmatter, parse_mcp_tools

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
    skillSlug: 'idea-to-pdd',
    producedBy: 'idea-to-pdd',
    consumedBy: ['pdd-to-learn-app', 'pdd-to-deliver-app'],
    phase: 'setup',
    artifactType: 'pdd',
    label: 'Intervention Design Doc',
  },
  {
    skillSlug: 'pdd-to-learn-app',
    producedBy: 'pdd-to-learn-app',
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
        assert first["skill_slug"] == "idea-to-pdd"
        assert first["produced_by"] == "idea-to-pdd"
        assert first["consumed_by"] == ["pdd-to-learn-app", "pdd-to-deliver-app"]
        assert first["artifact_type"] == "pdd"
        assert first["label"] == "Intervention Design Doc"

        second = entries[1]
        assert second["skill_slug"] == "pdd-to-learn-app"
        assert second["produced_by"] == "pdd-to-learn-app"
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

    def test_colon_inside_string_value(self):
        """Keys inside string values must not be confused with object keys."""
        sample = """
        export const ARTIFACT_MANIFEST: readonly ArtifactEntry[] = [
          {
            path: 'x.md',
            producedBy: 'skill-a',
            consumedBy: [],
            phase: 'build',
            required: true,
            description: 'Thing with colon: in the middle',
          },
        ] as const;
        """
        result = parse_artifact_manifest(sample)
        assert len(result) == 1
        assert result[0]["description"] == "Thing with colon: in the middle"

    def test_real_ace_plugin_manifest_parses(self):
        """Regression: the real artifact-manifest.ts from the ACE plugin must parse."""
        import os
        real_path = "/Users/jjackson/emdash-projects/ace/lib/artifact-manifest.ts"
        if not os.path.exists(real_path):
            import pytest
            pytest.skip("ACE plugin not available in this environment")
        text = open(real_path).read()
        result = parse_artifact_manifest(text)
        # Should parse many entries (30+ in current manifest)
        assert len(result) > 20
        # The entry that previously broke parsing: state.yaml with "state:" in description
        state_yaml = next((e for e in result if e["path"] == "state.yaml"), None)
        assert state_yaml is not None
        assert "state:" in state_yaml["description"]


# ---------------------------------------------------------------------------
# parse_mcp_tools
# ---------------------------------------------------------------------------


class TestParseMcpTools:
    def test_three_arg_shape_uses_preceding_comment(self):
        """server.tool(name, schema, handler) falls back to the // comment above."""
        src = """
const server = new McpServer({ name: 'demo' });

// Look up an opportunity by id
server.tool('get_opp',
  { organization_slug: z.string(), opportunity_id: z.string() },
  async (args) => runAtom(args)
);
""".strip()
        tools = parse_mcp_tools(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "get_opp"
        assert tools[0]["description"] == "Look up an opportunity by id"
        assert tools[0]["params"] == ["organization_slug", "opportunity_id"]

    def test_four_arg_shape_uses_inline_description(self):
        """server.tool(name, description, schema, handler) — gdrive shape."""
        src = """
server.tool(
  'sheets_read',
  'Read a range of cells from a Google Spreadsheet. Returns rows as arrays.',
  {
    spreadsheetId: z.string().describe('The spreadsheet ID'),
    range: z.string().describe('A1 notation range, e.g. "Sheet1!A1:D10"'),
  },
  async ({ spreadsheetId, range }) => result(null),
);
""".strip()
        tools = parse_mcp_tools(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "sheets_read"
        assert "Read a range of cells" in tools[0]["description"]
        assert tools[0]["params"] == ["spreadsheetId", "range"]

    def test_section_divider_comment_filtered(self):
        """`── Programs ──` style headers describe a group, not the tool."""
        src = """
// ── Programs ──────────────────────────────────────────────────────

server.tool('connect_list_programs',
  { organization_slug: z.string() },
  async (args) => null
);
""".strip()
        tools = parse_mcp_tools(src)
        assert tools[0]["description"] is None

    def test_nested_zod_object_does_not_leak_inner_keys(self):
        """A z.object({...}) param shouldn't surface its inner fields as top-level keys."""
        src = """
server.tool('connect_set_verification_flags',
  {
    organization_slug: z.string(),
    flags: z.object({ duplicate: z.boolean(), gps: z.boolean() }),
  },
  async (args) => null
);
""".strip()
        tools = parse_mcp_tools(src)
        assert tools[0]["params"] == ["organization_slug", "flags"]

    def test_concatenated_description_strings(self):
        """`'foo' + 'bar'` style descriptions are concatenated."""
        src = """
server.tool(
  'big_tool',
  'first part ' + 'second part',
  { x: z.string() },
  async (args) => null
);
""".strip()
        tools = parse_mcp_tools(src)
        assert tools[0]["description"] == "first part second part"

    def test_multiple_tools_with_line_numbers(self):
        src = """
server.tool('one', { a: z.string() }, async () => null);

server.tool('two', { b: z.string() }, async () => null);
""".strip()
        tools = parse_mcp_tools(src)
        assert [t["name"] for t in tools] == ["one", "two"]
        assert tools[0]["line"] < tools[1]["line"]

    def test_real_mcp_servers_parse(self):
        """Regression: the four real MCP server files must parse without errors."""
        from pathlib import Path
        mcp_dir = Path("/Users/jjackson/emdash-projects/ace/mcp")
        if not mcp_dir.is_dir():
            import pytest
            pytest.skip("ACE plugin not available in this environment")
        # Each known server should yield at least a handful of tools.
        expected_min = {
            "connect-server.ts": 20,
            "google-drive-server.ts": 15,
            "mobile-server.ts": 10,
            "ocs-server.ts": 20,
        }
        for fname, minimum in expected_min.items():
            f = mcp_dir / fname
            if not f.is_file():
                continue
            tools = parse_mcp_tools(f.read_text())
            assert len(tools) >= minimum, f"{fname}: only got {len(tools)} tools"
            # Every tool has a snake_case name and at least an empty params list
            for t in tools:
                assert "_" in t["name"]
                assert isinstance(t["params"], list)
