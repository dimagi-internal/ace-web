# ACE System Overview — Design Spec

**Date:** 2026-04-14
**Status:** Draft — awaiting review.
**Scope:** New "System" tab in ace-web that visualizes the full ACE/CRISPR-Connect
system blueprint — skills, agents, phases, judges, gates, artifacts, and archetypes —
from runtime inspection of the ACE plugin repo.

## 1. Overview

The System Overview tab is a read-only, interactive visualization of the entire
CRISPR-Connect system. Where the Opp Workbench shows a *specific run's* execution
state, the System tab shows the *blueprint* — the 19 skills, 5 agents, 4 phases,
4 gates, 10 judges, 3 archetypes, and 30+ artifacts that define the system itself.

Everything is generated from the ACE plugin repo at runtime. If a 20th skill is
added to the plugin, the System tab picks it up on next load. Nothing is hardcoded
in the UI except rendering logic.

## 2. Goals

1. **System legibility.** Anyone on the team can open the System tab and understand
   what ACE does, in what order, with what checks, without reading 21 markdown files.
2. **Skill deep-dive.** Click any skill to read its full SKILL.md rendered as
   markdown with structured metadata (judge rubric, artifacts, MCP tools, mode
   behavior) pulled out into scannable sections.
3. **Agent orchestration.** See how the 5 agents compose the 19 skills — sequential
   vs. parallel execution, gate checkpoints, recurring schedules.
4. **Shared markdown renderer.** A production-quality markdown rendering component
   that also benefits the Opp Workbench (render Drive artifacts inline instead of
   linking to Drive).

## 3. Data sources

All data comes from the ACE plugin repo on the local filesystem. The backend reads
files at the path configured by `ACE_PLUGIN_PATH` (new setting, defaults to
`../ace/` relative to the repo root). No Drive access. No ORM models.

| Source | Location | Format | What it provides |
|--------|----------|--------|------------------|
| Skill metadata | `apps/opps/skills.py` | Python registry | ordinal, phase, has_judge, is_gate, is_recurring, primary_output |
| Skill definitions | `{ACE_PLUGIN_PATH}/skills/*/SKILL.md` | YAML frontmatter + markdown | name, description, full body (process, rubric, archetypes, MCP tools, mode behavior) |
| Agent definitions | `{ACE_PLUGIN_PATH}/agents/*.md` | YAML frontmatter + markdown | name, description, model, full body (workflow steps, parallel groups, gates) |
| Artifact manifest | `{ACE_PLUGIN_PATH}/lib/artifact-manifest.ts` | TypeScript const array | path, producedBy, consumedBy, phase, required, description |
| Skills README | `{ACE_PLUGIN_PATH}/skills/README.md` | Markdown | Skill contract: required sections, conventions |

### 3.1 Parsing the artifact manifest

The artifact manifest is a TypeScript file (`lib/artifact-manifest.ts`) containing a
`const ARTIFACT_MANIFEST` array of object literals. The format is stable and
well-structured — effectively JSON with TypeScript type annotations.

The backend parses this file with a lightweight approach:
1. Read the file as text.
2. Extract the array literal between `ARTIFACT_MANIFEST: readonly ArtifactEntry[] = [`
   and the closing `] as const;`.
3. Strip TypeScript-only syntax (trailing `as const`, type annotations) and normalize
   to valid JSON (trailing commas, single-line comments).
4. Parse as JSON.

This is pragmatic and zero-coordination-cost. If the format changes significantly,
the parser fails loudly on the next request. No build step required in the ACE repo.

### 3.2 Parsing SKILL.md and agent .md files

Standard YAML frontmatter parsing: split on `---` delimiters, parse the YAML block,
return the rest as the markdown body. Python's `yaml.safe_load` handles the
frontmatter. The body is returned as-is for the frontend markdown renderer.

### 3.3 Merging skill metadata

The API response for each skill merges two sources:
- **Python registry** (`skills.py`): ordinal, phase, has_judge, is_gate, is_recurring,
  primary_output — these are the structured, typed fields.
- **SKILL.md frontmatter**: name, description — the canonical display text.
- **SKILL.md body**: full markdown for the detail pane.
- **Artifact manifest**: artifacts where `producedBy == skill_name` (produces) and
  artifacts where `skill_name in consumedBy` (consumes).

The join key is the skill name (e.g., `idea-to-idd`). If a SKILL.md exists without
a corresponding entry in skills.py (e.g., the `email-communicator` utility skill),
it appears in a separate "Utility Skills" section with no ordinal/phase.

**Display name derivation:** The `display_name` field (e.g., "Idea to IDD") is
extracted from the h1 heading in the SKILL.md body (`# Idea to IDD`). If no SKILL.md
exists, title-case the kebab name (`idea-to-idd` → `Idea To Idd`).

**Phase name normalization:** The artifact manifest uses short phase names
(`build`, `setup`, `operate`, `closeout`) while skills.py uses full names
(`app-building`, `connect-setup`, `llo-management`, `closeout`). The backend
normalizes manifest phases to match skills.py via a mapping dict. The API always
returns the skills.py convention.

## 4. Backend API

New Django app: `apps/system/`. No models. Read-through to the filesystem.

### 4.1 Plugin version check

On every load of the System tab, the frontend fetches the overview endpoint which
includes a version check. The backend:

1. Reads the local `VERSION` file from `ACE_PLUGIN_PATH/VERSION`.
2. Fetches the remote `VERSION` from GitHub
   (`https://raw.githubusercontent.com/jjackson/ace/main/VERSION`) via `httpx`.
3. Compares the two. If they differ, `update_available` is `true`.

The remote fetch is **cached for 60 minutes** (in-process, module-level). If the
fetch fails (network down, rate-limited), the response still succeeds — it just
omits `remote_version` and sets `update_available` to `null` (unknown).

The frontend shows a banner at the top of the System page when an update is
available: "ACE plugin v0.1.11 is available (you have v0.1.10). Run /ace:update
in Claude Code to upgrade." The banner is dismissible for the session.

### 4.2 Endpoints

**`GET /api/system/overview`** — Returns the full system snapshot.

Response shape:
```json
{
  "data": {
    "plugin_version": "0.1.10",
    "remote_version": "0.1.11",
    "update_available": true,
    "skills": [
      {
        "name": "idea-to-idd",
        "display_name": "Idea to IDD",
        "description": "Iterate on an idea to produce a well-specified IDD...",
        "ordinal": 1,
        "phase": "app-building",
        "has_judge": true,
        "is_gate": true,
        "is_recurring": false,
        "primary_output": "idd.md",
        "artifacts_produced": [
          {"path": "idd.md", "description": "Intervention Design Document...", "required": true}
        ],
        "artifacts_consumed": [
          {"path": "idea.md", "description": "Initial opportunity idea...", "required": true}
        ]
      }
    ],
    "agents": [
      {
        "name": "app-builder",
        "description": "Orchestrates the app building phase...",
        "model": "inherit"
      }
    ],
    "artifacts": [
      {
        "path": "idd.md",
        "produced_by": "idea-to-idd",
        "consumed_by": ["idd-to-learn-app", "idd-to-deliver-app", "..."],
        "phase": "build",
        "required": true,
        "description": "Intervention Design Document..."
      }
    ],
    "phases": ["app-building", "connect-setup", "llo-management", "closeout"]
  },
  "error": null
}
```

**`GET /api/system/skills/<name>`** — Returns a single skill with full markdown body.

Response shape:
```json
{
  "data": {
    "name": "idea-to-idd",
    "display_name": "Idea to IDD",
    "description": "...",
    "ordinal": 1,
    "phase": "app-building",
    "has_judge": true,
    "is_gate": true,
    "is_recurring": false,
    "primary_output": "idd.md",
    "artifacts_produced": [...],
    "artifacts_consumed": [...],
    "body_markdown": "# Idea to IDD\n\nTake an initial idea and..."
  },
  "error": null
}
```

**`GET /api/system/agents/<name>`** — Returns a single agent with full markdown body.

Response shape:
```json
{
  "data": {
    "name": "app-builder",
    "description": "Orchestrates the app building phase...",
    "model": "inherit",
    "body_markdown": "# App Builder Agent\n\nYou orchestrate..."
  },
  "error": null
}
```

### 4.3 Version check endpoint

**`GET /api/system/version`** — Lightweight version-only check (no full system load).

Response shape:
```json
{
  "data": {
    "plugin_version": "0.1.10",
    "remote_version": "0.1.11",
    "update_available": true,
    "plugin_path": "/path/to/ace",
    "plugin_found": true
  },
  "error": null
}
```

This endpoint is useful for a quick status check without loading the full skill/agent
data. The overview endpoint includes the same version fields.

### 4.4 Design decisions

- **No caching in v1.** The ACE plugin path is local filesystem — reads are fast
  (~5ms for all 21 SKILL.md files). Add caching later if needed.
- **Authentication required.** Use `@permission_classes([IsAuthenticated])` like the
  opps endpoints. Unauthenticated requests get a 401 with the standard envelope.
- **Envelope pattern.** All responses use `success_response()` / `error_response()`.
- **Graceful degradation.** If `ACE_PLUGIN_PATH` doesn't exist or a file is
  unreadable, return partial data with warnings rather than a 500. Skills without
  SKILL.md files still appear (from the Python registry) — they just lack the
  markdown body.

### 4.5 File organization

```
apps/system/
├── __init__.py
├── apps.py          # SystemConfig
├── urls.py          # 4 endpoints
├── views.py         # DRF function-based views
├── reader.py        # Filesystem reader: load skills, agents, artifacts
├── parsers.py       # Frontmatter parser, artifact-manifest.ts parser
├── serializers.py   # Pure functions: dataclass → dict
├── version.py       # Remote VERSION fetch + 60min cache
└── tests/
    ├── __init__.py
    ├── test_parsers.py
    ├── test_reader.py
    ├── test_version.py
    └── test_views.py
```

## 5. Frontend

### 5.1 New route and nav

Add `/system` route to `router.tsx`. Add "System" to `NAV_ITEMS` in `TopNav.tsx`.

### 5.2 Page structure

`SystemPage.tsx` follows the `OppWorkbenchPage` pattern:
- Discriminated union load state: `loading | error | loaded`
- Three-pane layout: sidebar + center + detail pane
- View toggle in the subheader: **Pipeline** (default) and **Agents**

**Update banner:** When `update_available` is `true`, a dismissible banner appears
between the subheader and the three-pane layout:

> ACE plugin **v0.1.11** is available (you have **v0.1.10**).
> Run `/ace:update` in Claude Code to upgrade.

The banner uses `--status-info` color (blue tint). Dismissing it sets a session-level
flag so it doesn't reappear on re-navigation within the same browser session.

When `update_available` is `null` (fetch failed), no banner is shown — silent
degradation. When `plugin_found` is `false`, the entire page shows an empty state
explaining that the ACE plugin was not found at the configured path.

### 5.3 Pipeline view (by phase)

The default view. Shows all 19 skills as the linear execution pipeline.

**Left sidebar (200px):**
- Phase filter: "All Skills" (default), then each of the 4 phases with skill counts
- Badge filters: "Has Judge" (10), "Has Gate" (4), "Recurring" (2)
- Archetypes section: Atomic Visit, Focus Group, Multi-Stage (links to archetype
  docs within the skill detail pane)

**Center panel (flex-1):**
- Skills listed in ordinal order, grouped under sticky phase headers
- Each skill row shows: ordinal number (circle), skill name, primary output filename
  (monospace), and badges (Judge / Gate / Recurring)
- Click a row to select it and load the detail pane

**Right detail pane (420px):**
- Skill metadata grid: phase, ordinal, judge, gate, agent, recurring
- Artifacts section: what this skill produces and what consumes it (from the artifact
  manifest)
- Judge rubric: extracted from the "LLM-as-Judge Rubric" section of SKILL.md (only
  shown for skills with `has_judge`)
- Process steps: the "Process" section from SKILL.md, rendered as markdown
- MCP tools: from the "MCP Tools Used" section
- Mode behavior: Auto vs. Review behavior
- Full SKILL.md: collapsible section with the complete rendered markdown

### 5.4 Agents view (by agent)

Shows how the 5 agents compose and execute skills. Answers "how does the system
run?" vs the Pipeline view's "what does the system have?"

**Left sidebar (200px):**
- Agent list: All Agents (default), then each of the 6 agents (5 phase agents +
  orchestrator)

**Center panel (flex-1):**
- Each agent rendered as an expandable card:
  - Header: agent name (color-coded by phase), description, phase badge
  - Body: workflow steps in execution order
    - Sequential steps: numbered with connector lines
    - Parallel groups: visually grouped in a dashed border with a "runs in parallel"
      label (e.g., steps 2-3 of app-builder)
    - Recurring groups: labeled "runs recurring (weekly)" for timeline-monitor and
      flw-data-review
    - Gate steps: amber-colored step number
    - Judge steps: purple-colored step number
    - Each step shows produced artifacts as small green tags

**Right detail pane (420px):**
- Click an agent card header to load agent detail
- Agent metadata: phase, skill count, gate count, judge count
- Execution pattern description
- Produced artifacts list
- Full agent definition markdown

### 5.5 Markdown renderer component

New shared component: `MarkdownRenderer.tsx`

Dependencies to add:
- `react-markdown` — core renderer
- `remark-gfm` — GitHub Flavored Markdown (tables, strikethrough, task lists)
- `rehype-highlight` — syntax highlighting for code blocks

This component renders markdown content with:
- Proper heading hierarchy with the ace-web typography
- Code blocks with syntax highlighting (YAML, Python, TypeScript, Markdown)
- Tables with the shadcn/tailwind table styling
- Inline code with the monospace font
- Links that open in new tabs

The component is shared — it's used in the System tab detail panes and will also
be used in the Opp Workbench to render Drive artifact content inline.

Location: `frontend/src/components/MarkdownRenderer.tsx`

### 5.6 Component organization

```
frontend/src/
├── api/
│   └── system.ts                    # API client for /api/system/*
├── pages/
│   └── SystemPage.tsx               # Page shell with view toggle
├── components/
│   ├── MarkdownRenderer.tsx         # Shared markdown renderer
│   └── system/
│       ├── SystemHeader.tsx         # Subheader with stats and view toggle
│       ├── PipelineSidebar.tsx      # Phase/filter sidebar
│       ├── SkillList.tsx            # Center panel skill rows
│       ├── SkillRow.tsx             # Individual skill row
│       ├── SkillDetailPane.tsx      # Right pane for skill detail
│       ├── AgentSidebar.tsx         # Agent list sidebar
│       ├── AgentList.tsx            # Center panel agent cards
│       ├── AgentCard.tsx            # Individual agent workflow card
│       ├── AgentDetailPane.tsx      # Right pane for agent detail
│       ├── ArtifactList.tsx         # Artifact display (used in both panes)
│       └── types.ts                 # SystemSnapshot, SkillDetail, AgentDetail types
```

### 5.7 TypeScript types

```typescript
interface SystemSnapshot {
  plugin_version: string;
  remote_version: string | null;
  update_available: boolean | null;  // null = couldn't check
  skills: SkillSummary[];
  agents: AgentSummary[];
  artifacts: ArtifactEntry[];
  phases: string[];
}

interface SkillSummary {
  name: string;
  display_name: string;
  description: string;
  ordinal: number;
  phase: string;
  has_judge: boolean;
  is_gate: boolean;
  is_recurring: boolean;
  primary_output: string;
  artifacts_produced: ArtifactRef[];
  artifacts_consumed: ArtifactRef[];
}

interface SkillDetail extends SkillSummary {
  body_markdown: string;
}

interface AgentSummary {
  name: string;
  description: string;
  model: string;
}

interface AgentDetail extends AgentSummary {
  body_markdown: string;
}

interface ArtifactEntry {
  path: string;
  produced_by: string;
  consumed_by: string[];
  phase: string;
  required: boolean;
  description: string;
}

interface ArtifactRef {
  path: string;
  description: string;
  required: boolean;
}
```

## 6. Design constraints

- **Dark mode default.** Matches ace-web: Geist font, shadcn components, CSS custom
  property color tokens. The mockup at `docs/mockups/system-overview-mockup.html`
  shows the visual design.
- **Three-pane layout.** Same layout pattern as OppWorkbenchPage: left sidebar
  (200px), center (flex-1), right detail pane (420px).
- **No ORM models.** All data is read from the filesystem. The ACE plugin repo is the
  source of truth. ace-web reads through.
- **Phase colors.** App Building = blue, Connect Setup = green, LLO Management =
  amber, Closeout = purple. Same palette already used in the Opp Workbench.
- **Badge colors.** Judge = purple, Gate = amber, Recurring = cyan.

## 7. Settings

One new setting in `config/settings/base.py`:

```python
ACE_PLUGIN_PATH = env.str("ACE_PLUGIN_PATH", default=str(BASE_DIR.parent / "ace"))
```

This is the absolute path to the ACE plugin repo root. The backend reads
`skills/*/SKILL.md`, `agents/*.md`, `lib/artifact-manifest.ts`, and
`.claude-plugin/plugin.json` from this path.

## 8. Error handling

- **Plugin path not found:** Return 200 with empty data and a warning message
  (`"ACE plugin not found at <path>"`). The UI shows an empty state with the
  warning.
- **Individual file parse failure:** Log the error, skip the file, return partial
  data. A broken SKILL.md doesn't prevent the rest of the system from rendering.
- **Artifact manifest parse failure:** Log the error, return skills/agents without
  artifact relationships. The UI hides the artifacts sections.

## 9. Testing

- **`test_parsers.py`**: Unit tests for frontmatter parsing, artifact manifest
  parsing. Use inline fixtures (small YAML/TS snippets), not the actual ACE repo.
- **`test_reader.py`**: Unit tests for the filesystem reader. Create a temp directory
  with mock skill/agent files.
- **`test_views.py`**: Integration tests for the API endpoints. Mock the reader to
  return fixture data.
- **Frontend**: No dedicated test files for v1. Manual verification against the
  actual ACE plugin data.

## 10. Out of scope

- **Drive artifact viewer in the Opp Workbench.** The shared MarkdownRenderer
  component lands as part of this work, but wiring it into the Opp Workbench step
  detail to render Drive artifacts inline is a separate task. The component is ready
  for it.
- **Caching.** No caching in v1. Filesystem reads are fast enough.
- **Search.** No full-text search across skills/agents. Browse-only for v1.
- **Skill dependency graph visualization.** The artifact data supports it, but a
  visual graph (nodes + edges) is not in scope. The produces/consumes lists in the
  detail pane are sufficient for v1.
- **Live editing.** The System tab is read-only. Editing skills requires changing
  the ACE plugin repo directly.

## 11. Mockup

Interactive HTML mockup: `docs/mockups/system-overview-mockup.html`

Open in a browser to see both the Pipeline and Agents views with the three-pane
layout, skill rows, agent workflow cards, and detail panes. The mockup uses
representative data from the actual ACE plugin.
