# System Overview Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "System" tab to ace-web that visualizes the full ACE/CRISPR-Connect system blueprint — skills, agents, phases, judges, gates, artifacts — generated from runtime inspection of the ACE plugin repo.

**Architecture:** New `apps/system/` Django module reads SKILL.md frontmatter, agent .md files, and the TypeScript artifact manifest from the local ACE plugin repo (via `ACE_PLUGIN_PATH` setting). A version checker compares local vs. remote VERSION files. Frontend adds a three-pane System page with Pipeline (by-phase) and Agents (by-agent) views, plus a shared MarkdownRenderer component.

**Tech Stack:** Django 5 + DRF (backend), React 19 + TypeScript + Tailwind 4 + shadcn (frontend), react-markdown + remark-gfm + rehype-highlight (markdown rendering), httpx (remote version check).

**Spec:** `docs/specs/2026-04-14-system-overview-design.md`
**Mockup:** `docs/mockups/system-overview-mockup.html`

---

## Task 1: Backend — Parsers (frontmatter + artifact manifest)

Pure parsing functions with no Django dependencies. Testable in isolation.

**Files:**
- Create: `apps/system/__init__.py`
- Create: `apps/system/parsers.py`
- Create: `apps/system/tests/__init__.py`
- Create: `apps/system/tests/test_parsers.py`

- [ ] **Step 1: Write failing tests for frontmatter parser**

```python
# apps/system/tests/test_parsers.py
import pytest

from apps.system.parsers import parse_frontmatter


class TestParseFrontmatter:
    def test_basic_frontmatter(self):
        text = (
            "---\n"
            "name: idea-to-idd\n"
            "description: >\n"
            "  Iterate on an idea to produce a well-specified IDD.\n"
            "---\n"
            "\n"
            "# Idea to IDD\n"
            "\n"
            "Some body text.\n"
        )
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "idea-to-idd"
        assert "well-specified IDD" in meta["description"]
        assert body.startswith("# Idea to IDD")

    def test_no_frontmatter(self):
        text = "# Just a heading\n\nNo frontmatter here."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_string(self):
        meta, body = parse_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_agent_frontmatter_with_model(self):
        text = (
            "---\n"
            "name: app-builder\n"
            "description: >\n"
            "  Orchestrates the app building phase.\n"
            "model: inherit\n"
            "---\n"
            "\n"
            "# App Builder Agent\n"
        )
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "app-builder"
        assert meta["model"] == "inherit"
        assert body.startswith("# App Builder Agent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/system/tests/test_parsers.py::TestParseFrontmatter -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.system'`

- [ ] **Step 3: Implement frontmatter parser**

```python
# apps/system/parsers.py
"""Parsers for ACE plugin metadata files."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import yaml

log = logging.getLogger(__name__)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns (metadata_dict, body_string). If no frontmatter is found,
    returns ({}, full_text).
    """
    if not text.startswith("---"):
        return {}, text
    # Find closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[4:end]
    body = text[end + 4:].lstrip("\n")
    try:
        meta = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        log.warning("Failed to parse YAML frontmatter")
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, body
```

Also create the empty `__init__.py` files:

```python
# apps/system/__init__.py
# (empty)
```

```python
# apps/system/tests/__init__.py
# (empty)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/system/tests/test_parsers.py::TestParseFrontmatter -v`
Expected: 4 PASSED

- [ ] **Step 5: Write failing tests for artifact manifest parser**

```python
# apps/system/tests/test_parsers.py (append to existing file)
from apps.system.parsers import parse_artifact_manifest


class TestParseArtifactManifest:
    SAMPLE_TS = """\
export const ARTIFACT_MANIFEST: readonly ArtifactEntry[] = [
  {
    path: 'idd.md',
    producedBy: 'idea-to-idd',
    consumedBy: ['idd-to-learn-app', 'idd-to-deliver-app'],
    phase: 'build',
    required: true,
    description: 'Intervention Design Document',
  },
  {
    path: 'apps/learn-app.json',
    producedBy: 'idd-to-learn-app',
    consumedBy: ['app-deploy'],
    phase: 'build',
    required: true,
    description: 'Learn app package',
  },
] as const;
"""

    def test_parses_two_entries(self):
        entries = parse_artifact_manifest(self.SAMPLE_TS)
        assert len(entries) == 2

    def test_first_entry_fields(self):
        entries = parse_artifact_manifest(self.SAMPLE_TS)
        idd = entries[0]
        assert idd["path"] == "idd.md"
        assert idd["produced_by"] == "idea-to-idd"
        assert idd["consumed_by"] == ["idd-to-learn-app", "idd-to-deliver-app"]
        assert idd["phase"] == "app-building"  # normalized from 'build'
        assert idd["required"] is True
        assert idd["description"] == "Intervention Design Document"

    def test_empty_manifest(self):
        ts = "export const ARTIFACT_MANIFEST: readonly ArtifactEntry[] = [] as const;"
        entries = parse_artifact_manifest(ts)
        assert entries == []

    def test_bad_input_returns_empty(self):
        entries = parse_artifact_manifest("not a valid file")
        assert entries == []

    def test_phase_normalization(self):
        """The manifest uses 'build'/'setup'/'operate'/'closeout' but the API
        returns 'app-building'/'connect-setup'/'llo-management'/'closeout'."""
        entries = parse_artifact_manifest(self.SAMPLE_TS)
        assert entries[0]["phase"] == "app-building"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest apps/system/tests/test_parsers.py::TestParseArtifactManifest -v`
Expected: FAIL — `ImportError: cannot import name 'parse_artifact_manifest'`

- [ ] **Step 7: Implement artifact manifest parser**

Append to `apps/system/parsers.py`:

```python
# Phase name mapping: artifact-manifest.ts uses short names, skills.py uses full names.
_PHASE_MAP = {
    "build": "app-building",
    "setup": "connect-setup",
    "operate": "llo-management",
    "closeout": "closeout",
}


def parse_artifact_manifest(ts_source: str) -> list[dict[str, Any]]:
    """Parse the ARTIFACT_MANIFEST array from artifact-manifest.ts.

    Extracts the array literal, strips TypeScript syntax, normalizes to
    JSON, and parses. Returns a list of dicts with snake_case keys and
    normalized phase names. Returns [] on any parse failure.
    """
    # 1. Extract the array body between the opening [ and closing ] as const;
    start_match = re.search(
        r"ARTIFACT_MANIFEST\s*[:\s\w\[\]<>]*=\s*\[", ts_source
    )
    if not start_match:
        return []
    start = start_match.end()
    end = ts_source.find("] as const;", start)
    if end == -1:
        end = ts_source.find("];", start)
    if end == -1:
        return []
    array_body = ts_source[start:end]

    # 2. Normalize TS object literals to JSON
    # Remove single-line comments
    array_body = re.sub(r"//.*$", "", array_body, flags=re.MULTILINE)
    # Single-quoted strings → double-quoted
    array_body = array_body.replace("'", '"')
    # Unquoted keys → quoted keys  (word: → "word":)
    array_body = re.sub(r"(\s)(\w+)\s*:", r'\1"\2":', array_body)
    # Remove trailing commas before } or ]
    array_body = re.sub(r",\s*([\]}])", r"\1", array_body)
    # Wrap in array brackets
    json_str = f"[{array_body}]"

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as exc:
        log.warning("Failed to parse artifact manifest: %s", exc)
        return []

    # 3. Normalize to snake_case keys and map phases
    result = []
    for entry in raw:
        result.append({
            "path": entry.get("path", ""),
            "produced_by": entry.get("producedBy", ""),
            "consumed_by": entry.get("consumedBy", []),
            "phase": _PHASE_MAP.get(entry.get("phase", ""), entry.get("phase", "")),
            "required": entry.get("required", False),
            "description": entry.get("description", ""),
        })
    return result
```

- [ ] **Step 8: Run all parser tests**

Run: `pytest apps/system/tests/test_parsers.py -v`
Expected: 9 PASSED

- [ ] **Step 9: Commit**

```bash
git add apps/system/__init__.py apps/system/parsers.py apps/system/tests/__init__.py apps/system/tests/test_parsers.py
git commit -m "feat(system): add frontmatter and artifact manifest parsers with tests"
```

---

## Task 2: Backend — Version checker

Reads local VERSION file, fetches remote from GitHub, caches for 60 minutes.

**Files:**
- Create: `apps/system/version.py`
- Create: `apps/system/tests/test_version.py`

- [ ] **Step 1: Write failing tests for version checker**

```python
# apps/system/tests/test_version.py
import time
from unittest.mock import AsyncMock, patch

import pytest

from apps.system.version import check_version, _cache, REMOTE_VERSION_URL


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the module-level cache before each test."""
    _cache.clear()
    yield
    _cache.clear()


class TestCheckVersion:
    def test_local_only_when_plugin_not_found(self, tmp_path):
        result = check_version(str(tmp_path / "nonexistent"))
        assert result["plugin_found"] is False
        assert result["plugin_version"] is None
        assert result["remote_version"] is None
        assert result["update_available"] is None

    def test_reads_local_version(self, tmp_path):
        (tmp_path / "VERSION").write_text("0.1.10\n")
        with patch("apps.system.version._fetch_remote_version", return_value="0.1.11"):
            result = check_version(str(tmp_path))
        assert result["plugin_found"] is True
        assert result["plugin_version"] == "0.1.10"
        assert result["remote_version"] == "0.1.11"
        assert result["update_available"] is True

    def test_up_to_date(self, tmp_path):
        (tmp_path / "VERSION").write_text("0.1.11\n")
        with patch("apps.system.version._fetch_remote_version", return_value="0.1.11"):
            result = check_version(str(tmp_path))
        assert result["update_available"] is False

    def test_remote_fetch_failure(self, tmp_path):
        (tmp_path / "VERSION").write_text("0.1.10\n")
        with patch("apps.system.version._fetch_remote_version", return_value=None):
            result = check_version(str(tmp_path))
        assert result["plugin_version"] == "0.1.10"
        assert result["remote_version"] is None
        assert result["update_available"] is None

    def test_cache_is_used(self, tmp_path):
        (tmp_path / "VERSION").write_text("0.1.10\n")
        mock_fetch = patch(
            "apps.system.version._fetch_remote_version", return_value="0.1.11"
        )
        with mock_fetch as m:
            check_version(str(tmp_path))
            check_version(str(tmp_path))
        assert m.call_count == 1  # second call uses cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/system/tests/test_version.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement version checker**

```python
# apps/system/version.py
"""ACE plugin version checker with cached remote fetch."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/jjackson/ace/main/VERSION"
)
CACHE_TTL_SECONDS = 60 * 60  # 60 minutes

# Module-level cache: {"remote_version": str | None, "fetched_at": float}
_cache: dict[str, Any] = {}


def _fetch_remote_version() -> str | None:
    """Fetch the remote VERSION file from GitHub. Returns None on failure."""
    try:
        resp = httpx.get(REMOTE_VERSION_URL, timeout=5.0, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text.strip()
    except (httpx.HTTPError, OSError) as exc:
        log.debug("Failed to fetch remote VERSION: %s", exc)
    return None


def _get_remote_version_cached() -> str | None:
    """Return the remote version, using a 60-minute in-process cache."""
    now = time.monotonic()
    fetched_at = _cache.get("fetched_at", 0.0)
    if _cache.get("remote_version") is not None and (now - fetched_at) < CACHE_TTL_SECONDS:
        return _cache["remote_version"]
    version = _fetch_remote_version()
    _cache["remote_version"] = version
    _cache["fetched_at"] = now
    return version


def check_version(plugin_path: str) -> dict[str, Any]:
    """Check local vs. remote ACE plugin version.

    Returns a dict with: plugin_found, plugin_version, remote_version,
    update_available, plugin_path.
    """
    result: dict[str, Any] = {
        "plugin_found": False,
        "plugin_version": None,
        "remote_version": None,
        "update_available": None,
        "plugin_path": plugin_path,
    }

    version_file = Path(plugin_path) / "VERSION"
    if not version_file.is_file():
        return result

    result["plugin_found"] = True
    result["plugin_version"] = version_file.read_text().strip()

    remote = _get_remote_version_cached()
    result["remote_version"] = remote
    if remote is not None and result["plugin_version"]:
        result["update_available"] = remote != result["plugin_version"]

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/system/tests/test_version.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add apps/system/version.py apps/system/tests/test_version.py
git commit -m "feat(system): add version checker with 60min cache"
```

---

## Task 3: Backend — Filesystem reader

Reads skills, agents, and artifacts from the ACE plugin path. Merges with the
Python skill registry.

**Files:**
- Create: `apps/system/reader.py`
- Create: `apps/system/tests/test_reader.py`

- [ ] **Step 1: Write failing tests for the reader**

```python
# apps/system/tests/test_reader.py
import pytest

from apps.system.reader import load_system_overview, load_skill_detail, load_agent_detail


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/system/tests/test_reader.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement the reader**

```python
# apps/system/reader.py
"""Filesystem reader for the ACE plugin repo."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from apps.opps.skills import SKILL_REGISTRY, PHASE_DISPLAY_NAMES, ALL_PHASES
from apps.system.parsers import parse_artifact_manifest, parse_frontmatter

log = logging.getLogger(__name__)

# Pre-index the registry for O(1) lookups
_REGISTRY_BY_NAME = {s.name: s for s in SKILL_REGISTRY}


def _extract_h1(body: str) -> str | None:
    """Extract the first h1 heading from markdown body."""
    m = re.match(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def _titlecase_kebab(name: str) -> str:
    """Convert kebab-case to Title Case: 'idea-to-idd' → 'Idea To Idd'."""
    return " ".join(w.capitalize() for w in name.split("-"))


def _load_skill_files(plugin_path: Path) -> dict[str, tuple[dict, str]]:
    """Load all SKILL.md files. Returns {name: (frontmatter, body)}."""
    skills_dir = plugin_path / "skills"
    result = {}
    if not skills_dir.is_dir():
        return result
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            name = meta.get("name", skill_dir.name)
            result[name] = (meta, body)
        except Exception as exc:
            log.warning("Failed to read %s: %s", skill_md, exc)
    return result


def _load_agent_files(plugin_path: Path) -> dict[str, tuple[dict, str]]:
    """Load all agent .md files. Returns {name: (frontmatter, body)}."""
    agents_dir = plugin_path / "agents"
    result = {}
    if not agents_dir.is_dir():
        return result
    for agent_md in sorted(agents_dir.glob("*.md")):
        try:
            text = agent_md.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            name = meta.get("name", agent_md.stem)
            result[name] = (meta, body)
        except Exception as exc:
            log.warning("Failed to read %s: %s", agent_md, exc)
    return result


def _load_artifacts(plugin_path: Path) -> list[dict[str, Any]]:
    """Load and parse the artifact manifest."""
    manifest_file = plugin_path / "lib" / "artifact-manifest.ts"
    if not manifest_file.is_file():
        return []
    try:
        ts_source = manifest_file.read_text(encoding="utf-8")
        return parse_artifact_manifest(ts_source)
    except Exception as exc:
        log.warning("Failed to parse artifact manifest: %s", exc)
        return []


def _build_skill_summary(
    name: str,
    meta: dict[str, Any] | None,
    body: str | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a skill summary dict by merging the registry with SKILL.md data."""
    reg = _REGISTRY_BY_NAME.get(name)

    # Display name: h1 from body > title-case of kebab name
    display_name = None
    if body:
        display_name = _extract_h1(body)
    if not display_name:
        display_name = _titlecase_kebab(name)

    produced = [a for a in artifacts if a["produced_by"] == name]
    consumed = [a for a in artifacts if name in a["consumed_by"]]

    return {
        "name": name,
        "display_name": display_name,
        "description": (meta or {}).get("description", ""),
        "ordinal": reg.ordinal if reg else None,
        "phase": reg.phase if reg else None,
        "has_judge": reg.has_judge if reg else False,
        "is_gate": reg.is_gate if reg else False,
        "is_recurring": reg.is_recurring if reg else False,
        "primary_output": reg.primary_output if reg else None,
        "artifacts_produced": [
            {"path": a["path"], "description": a["description"], "required": a["required"]}
            for a in produced
        ],
        "artifacts_consumed": [
            {"path": a["path"], "description": a["description"], "required": a["required"]}
            for a in consumed
        ],
    }


def load_system_overview(plugin_path: str) -> dict[str, Any]:
    """Load the full system overview from the ACE plugin directory.

    Returns a dict ready for serialization with keys: skills, agents,
    artifacts, phases, warning.
    """
    pp = Path(plugin_path)
    if not pp.is_dir():
        return {
            "skills": [],
            "agents": [],
            "artifacts": [],
            "phases": list(ALL_PHASES),
            "warning": f"ACE plugin not found at {plugin_path}",
        }

    skill_files = _load_skill_files(pp)
    agent_files = _load_agent_files(pp)
    artifacts = _load_artifacts(pp)

    # Build skill summaries. Start with registered skills (in ordinal order),
    # then append any SKILL.md-only skills not in the registry.
    skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reg_skill in SKILL_REGISTRY:
        fm = skill_files.get(reg_skill.name)
        meta, body = fm if fm else (None, None)
        skills.append(_build_skill_summary(reg_skill.name, meta, body, artifacts))
        seen.add(reg_skill.name)
    for name, (meta, body) in skill_files.items():
        if name not in seen:
            skills.append(_build_skill_summary(name, meta, body, artifacts))

    agents = [
        {
            "name": name,
            "description": meta.get("description", ""),
            "model": meta.get("model", ""),
        }
        for name, (meta, _body) in agent_files.items()
    ]

    return {
        "skills": skills,
        "agents": agents,
        "artifacts": artifacts,
        "phases": list(ALL_PHASES),
        "warning": None,
    }


def load_skill_detail(plugin_path: str, skill_name: str) -> dict[str, Any] | None:
    """Load a single skill with full markdown body."""
    pp = Path(plugin_path)
    skill_md = pp / "skills" / skill_name / "SKILL.md"
    if not skill_md.is_file():
        # Still return registry data if available
        reg = _REGISTRY_BY_NAME.get(skill_name)
        if reg is None:
            return None
        artifacts = _load_artifacts(pp)
        summary = _build_skill_summary(skill_name, None, None, artifacts)
        summary["body_markdown"] = ""
        return summary

    text = skill_md.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    artifacts = _load_artifacts(pp)
    summary = _build_skill_summary(skill_name, meta, body, artifacts)
    summary["body_markdown"] = body
    return summary


def load_agent_detail(plugin_path: str, agent_name: str) -> dict[str, Any] | None:
    """Load a single agent with full markdown body."""
    pp = Path(plugin_path)
    agent_md = pp / "agents" / f"{agent_name}.md"
    if not agent_md.is_file():
        return None
    text = agent_md.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    return {
        "name": meta.get("name", agent_name),
        "description": meta.get("description", ""),
        "model": meta.get("model", ""),
        "body_markdown": body,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/system/tests/test_reader.py -v`
Expected: 13 PASSED

- [ ] **Step 5: Commit**

```bash
git add apps/system/reader.py apps/system/tests/test_reader.py
git commit -m "feat(system): add filesystem reader for skills, agents, artifacts"
```

---

## Task 4: Backend — Django app, views, URLs, settings

Wire the reader into DRF views and register the app.

**Files:**
- Create: `apps/system/apps.py`
- Create: `apps/system/urls.py`
- Create: `apps/system/views.py`
- Modify: `config/settings/base.py` (add `ACE_PLUGIN_PATH` setting + register app)
- Modify: `config/urls.py` (add system URL include)
- Create: `apps/system/tests/test_views.py`

- [ ] **Step 1: Write failing tests for the views**

```python
# apps/system/tests/test_views.py
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User


@pytest.fixture
def authed_user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


MOCK_OVERVIEW = {
    "skills": [
        {
            "name": "idea-to-idd",
            "display_name": "Idea to IDD",
            "description": "Iterate on an idea.",
            "ordinal": 1,
            "phase": "app-building",
            "has_judge": True,
            "is_gate": True,
            "is_recurring": False,
            "primary_output": "idd.md",
            "artifacts_produced": [],
            "artifacts_consumed": [],
        }
    ],
    "agents": [{"name": "app-builder", "description": "Builds apps.", "model": "inherit"}],
    "artifacts": [],
    "phases": ["app-building", "connect-setup", "llo-management", "closeout"],
    "warning": None,
}

MOCK_VERSION = {
    "plugin_found": True,
    "plugin_version": "0.1.10",
    "remote_version": "0.1.11",
    "update_available": True,
    "plugin_path": "/tmp/ace",
}


class TestOverviewView:
    @patch("apps.system.views.check_version", return_value=MOCK_VERSION)
    @patch("apps.system.views.load_system_overview", return_value=MOCK_OVERVIEW)
    def test_returns_skills_and_agents(self, mock_load, mock_ver, authed_client):
        resp = authed_client.get("/api/system/overview")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "idea-to-idd"
        assert len(data["agents"]) == 1
        assert data["plugin_version"] == "0.1.10"
        assert data["update_available"] is True

    def test_unauthenticated_returns_401(self):
        c = Client()
        resp = c.get("/api/system/overview")
        assert resp.status_code in (401, 403)


class TestSkillDetailView:
    @patch("apps.system.views.load_skill_detail", return_value={
        "name": "idea-to-idd",
        "display_name": "Idea to IDD",
        "description": "...",
        "ordinal": 1,
        "phase": "app-building",
        "has_judge": True,
        "is_gate": True,
        "is_recurring": False,
        "primary_output": "idd.md",
        "artifacts_produced": [],
        "artifacts_consumed": [],
        "body_markdown": "# Idea to IDD\n\nBody here.",
    })
    def test_returns_skill_with_body(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/skills/idea-to-idd")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "idea-to-idd"
        assert "Body here" in data["body_markdown"]

    @patch("apps.system.views.load_skill_detail", return_value=None)
    def test_unknown_skill_returns_404(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/skills/nonexistent")
        assert resp.status_code == 404


class TestAgentDetailView:
    @patch("apps.system.views.load_agent_detail", return_value={
        "name": "app-builder",
        "description": "Builds apps.",
        "model": "inherit",
        "body_markdown": "# App Builder\n\nWorkflow here.",
    })
    def test_returns_agent_with_body(self, mock_load, authed_client):
        resp = authed_client.get("/api/system/agents/app-builder")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "app-builder"
        assert "Workflow here" in data["body_markdown"]


class TestVersionView:
    @patch("apps.system.views.check_version", return_value=MOCK_VERSION)
    def test_returns_version_info(self, mock_ver, authed_client):
        resp = authed_client.get("/api/system/version")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["plugin_version"] == "0.1.10"
        assert data["update_available"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/system/tests/test_views.py -v`
Expected: FAIL — imports missing

- [ ] **Step 3: Create the app config**

```python
# apps/system/apps.py
from django.apps import AppConfig


class SystemConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.system"
    label = "system"
    verbose_name = "ACE System Overview"
```

- [ ] **Step 4: Create the views**

```python
# apps/system/views.py
"""REST API views for the ACE System Overview."""
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.system.reader import load_agent_detail, load_skill_detail, load_system_overview
from apps.system.version import check_version


def _plugin_path() -> str:
    return getattr(settings, "ACE_PLUGIN_PATH", "")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def overview(request):
    """Return the full system snapshot: skills, agents, artifacts, version."""
    path = _plugin_path()
    data = load_system_overview(path)
    version = check_version(path)
    data["plugin_version"] = version["plugin_version"]
    data["remote_version"] = version["remote_version"]
    data["update_available"] = version["update_available"]
    return Response(success_response(data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def skill_detail(request, name: str):
    """Return a single skill with full markdown body."""
    detail = load_skill_detail(_plugin_path(), name)
    if detail is None:
        return Response(
            error_response(f"skill {name!r} not found", code="skill-not-found"),
            status=404,
        )
    return Response(success_response(detail))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_detail(request, name: str):
    """Return a single agent with full markdown body."""
    detail = load_agent_detail(_plugin_path(), name)
    if detail is None:
        return Response(
            error_response(f"agent {name!r} not found", code="agent-not-found"),
            status=404,
        )
    return Response(success_response(detail))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def version(request):
    """Lightweight version-only check."""
    data = check_version(_plugin_path())
    return Response(success_response(data))
```

- [ ] **Step 5: Create the URL routes**

```python
# apps/system/urls.py
"""URL routes for the ACE System Overview."""
from django.urls import path

from . import views

urlpatterns = [
    path("overview", views.overview, name="system-overview"),
    path("skills/<str:name>", views.skill_detail, name="system-skill-detail"),
    path("agents/<str:name>", views.agent_detail, name="system-agent-detail"),
    path("version", views.version, name="system-version"),
]
```

- [ ] **Step 6: Register the app and add the setting**

In `config/settings/base.py`, add `"apps.system.apps.SystemConfig"` to `INSTALLED_APPS` and add the `ACE_PLUGIN_PATH` setting.

Add to `INSTALLED_APPS` after the `"apps.service_accounts.apps.ServiceAccountsConfig"` line:

```python
    "apps.system.apps.SystemConfig",
```

Add after the `ACE_DRIVE_ROOT_FOLDER_ID` setting block (around line 154):

```python
# ACE plugin repo path — the System Overview tab reads skill definitions,
# agent definitions, and the artifact manifest from this directory.
ACE_PLUGIN_PATH = env.str("ACE_PLUGIN_PATH", default=str(BASE_DIR.parent / "ace"))
```

- [ ] **Step 7: Register the URL in config/urls.py**

Add after the `path("api/opps/", include("apps.opps.urls")),` line:

```python
    path("api/system/", include("apps.system.urls")),
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest apps/system/tests/test_views.py -v`
Expected: 6 PASSED

- [ ] **Step 9: Run the full test suite**

Run: `pytest -v`
Expected: All existing tests still pass, plus 6 new view tests.

- [ ] **Step 10: Commit**

```bash
git add apps/system/apps.py apps/system/views.py apps/system/urls.py apps/system/tests/test_views.py config/settings/base.py config/urls.py
git commit -m "feat(system): add Django app with overview, skill, agent, and version endpoints"
```

---

## Task 5: Frontend — Types, API client, and npm dependencies

Set up the TypeScript types, API client, and install markdown rendering deps.

**Files:**
- Create: `frontend/src/components/system/types.ts`
- Create: `frontend/src/api/system.ts`
- Modify: `frontend/package.json` (add react-markdown, remark-gfm, rehype-highlight)

- [ ] **Step 1: Install npm dependencies**

Run: `cd frontend && bun add react-markdown remark-gfm rehype-highlight`

Verify: `bun add` exits 0 and the three packages appear in `package.json` dependencies.

- [ ] **Step 2: Create TypeScript types**

```typescript
// frontend/src/components/system/types.ts

export interface ArtifactRef {
  path: string;
  description: string;
  required: boolean;
}

export interface ArtifactEntry {
  path: string;
  produced_by: string;
  consumed_by: string[];
  phase: string;
  required: boolean;
  description: string;
}

export interface SkillSummary {
  name: string;
  display_name: string;
  description: string;
  ordinal: number | null;
  phase: string | null;
  has_judge: boolean;
  is_gate: boolean;
  is_recurring: boolean;
  primary_output: string | null;
  artifacts_produced: ArtifactRef[];
  artifacts_consumed: ArtifactRef[];
}

export interface SkillDetail extends SkillSummary {
  body_markdown: string;
}

export interface AgentSummary {
  name: string;
  description: string;
  model: string;
}

export interface AgentDetail extends AgentSummary {
  body_markdown: string;
}

export interface SystemSnapshot {
  plugin_version: string | null;
  remote_version: string | null;
  update_available: boolean | null;
  skills: SkillSummary[];
  agents: AgentSummary[];
  artifacts: ArtifactEntry[];
  phases: string[];
  warning: string | null;
}
```

- [ ] **Step 3: Create API client**

```typescript
// frontend/src/api/system.ts
import { request } from "./client";
import type { AgentDetail, SkillDetail, SystemSnapshot } from "../components/system/types";

export function getSystemOverview(): Promise<SystemSnapshot> {
  return request<SystemSnapshot>("/system/overview");
}

export function getSkillDetail(name: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/system/skills/${encodeURIComponent(name)}`);
}

export function getAgentDetail(name: string): Promise<AgentDetail> {
  return request<AgentDetail>(`/system/agents/${encodeURIComponent(name)}`);
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/system/types.ts frontend/src/api/system.ts frontend/package.json frontend/bun.lock
git commit -m "feat(system): add frontend types, API client, and markdown deps"
```

---

## Task 6: Frontend — MarkdownRenderer shared component

A production-quality markdown renderer used by the System tab and available for
the Opp Workbench.

**Files:**
- Create: `frontend/src/components/MarkdownRenderer.tsx`

- [ ] **Step 1: Create the MarkdownRenderer component**

```tsx
// frontend/src/components/MarkdownRenderer.tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { Components } from "react-markdown";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-6 text-xl font-bold text-foreground first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-5 text-lg font-semibold text-foreground first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 text-base font-semibold text-foreground">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="mb-3 text-sm leading-relaxed text-muted-foreground">{children}</p>
  ),
  ul: ({ children }) => <ul className="mb-3 list-disc pl-5 text-sm text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal pl-5 text-sm text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="mb-1">{children}</li>,
  code: ({ className, children, ...props }) => {
    const isBlock = className?.startsWith("language-") || className?.startsWith("hljs");
    if (isBlock) {
      return (
        <code className={`${className ?? ""} block overflow-x-auto rounded bg-card p-3 text-xs`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-card px-1.5 py-0.5 font-mono text-xs text-foreground" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="mb-3 overflow-x-auto">{children}</pre>,
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-border">{children}</thead>,
  th: ({ children }) => (
    <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">{children}</th>
  ),
  td: ({ children }) => <td className="border-b border-border px-3 py-2 text-muted-foreground">{children}</td>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline hover:text-primary/80">
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-border pl-4 italic text-muted-foreground">{children}</blockquote>
  ),
  hr: () => <hr className="my-4 border-border" />,
};

interface Props {
  content: string;
  className?: string;
}

export function MarkdownRenderer({ content, className }: Props) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0 with no errors. (If rehype-highlight types are missing, run `bun add -d @types/hast` and retry.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MarkdownRenderer.tsx
git commit -m "feat(system): add shared MarkdownRenderer component"
```

---

## Task 7: Frontend — SystemPage shell with route and nav

The page shell, route registration, and nav item. Loads data, handles states,
renders the view toggle.

**Files:**
- Create: `frontend/src/pages/SystemPage.tsx`
- Create: `frontend/src/components/system/SystemHeader.tsx`
- Modify: `frontend/src/router.tsx` (add route)
- Modify: `frontend/src/components/TopNav.tsx` (add nav item)

- [ ] **Step 1: Create SystemHeader component**

```tsx
// frontend/src/components/system/SystemHeader.tsx
import { cn } from "@/lib/utils";
import type { SystemSnapshot } from "./types";

type ViewMode = "pipeline" | "agents";

interface Props {
  snapshot: SystemSnapshot;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
  updateDismissed: boolean;
  onDismissUpdate: () => void;
}

export function SystemHeader({ snapshot, view, onViewChange, updateDismissed, onDismissUpdate }: Props) {
  const judgeCount = snapshot.skills.filter((s) => s.has_judge).length;
  const gateCount = snapshot.skills.filter((s) => s.is_gate).length;

  return (
    <div className="flex flex-col border-b border-border">
      {/* Update banner */}
      {snapshot.update_available && !updateDismissed && (
        <div className="flex items-center justify-between bg-status-info/10 px-4 py-2 text-xs text-status-info">
          <span>
            ACE plugin <strong>v{snapshot.remote_version}</strong> is available (you have{" "}
            <strong>v{snapshot.plugin_version}</strong>). Run{" "}
            <code className="rounded bg-card px-1.5 py-0.5 font-mono">/ace:update</code> in Claude Code to
            upgrade.
          </span>
          <button type="button" onClick={onDismissUpdate} className="ml-4 text-muted-foreground hover:text-foreground">
            Dismiss
          </button>
        </div>
      )}

      {/* Subheader */}
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-4">
          <h1 className="text-base font-semibold text-foreground">System Blueprint</h1>
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span>
              <strong className="text-foreground">{snapshot.skills.length}</strong> skills
            </span>
            <span>
              <strong className="text-foreground">{snapshot.agents.length}</strong> agents
            </span>
            <span>
              <strong className="text-foreground">{snapshot.phases.length}</strong> phases
            </span>
            <span>
              <strong className="text-foreground">{gateCount}</strong> gates
            </span>
            <span>
              <strong className="text-foreground">{judgeCount}</strong> judges
            </span>
          </div>
        </div>

        <div className="flex overflow-hidden rounded-md border border-border bg-card text-xs">
          {(["pipeline", "agents"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onViewChange(mode)}
              className={cn(
                "px-3 py-1.5 font-medium capitalize",
                view === mode ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create SystemPage**

```tsx
// frontend/src/pages/SystemPage.tsx
import { useCallback, useEffect, useState } from "react";

import { getSystemOverview } from "../api/system";
import type { SystemSnapshot } from "../components/system/types";
import { SystemHeader } from "../components/system/SystemHeader";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { PipelineView } from "../components/system/PipelineView";
import { AgentsView } from "../components/system/AgentsView";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: SystemSnapshot };

type ViewMode = "pipeline" | "agents";

export default function SystemPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [view, setView] = useState<ViewMode>("pipeline");
  const [updateDismissed, setUpdateDismissed] = useState(false);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getSystemOverview()
      .then((snapshot) => setState({ kind: "loaded", snapshot }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, []);

  useEffect(load, [load]);

  if (state.kind === "loading") return <LoadingSpinner label="Loading system overview…" />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  const { snapshot } = state;

  if (snapshot.warning && snapshot.skills.length === 0) {
    return (
      <EmptyState
        title="ACE plugin not found"
        description={snapshot.warning}
      />
    );
  }

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <SystemHeader
        snapshot={snapshot}
        view={view}
        onViewChange={setView}
        updateDismissed={updateDismissed}
        onDismissUpdate={() => setUpdateDismissed(true)}
      />
      {view === "pipeline" ? <PipelineView snapshot={snapshot} /> : <AgentsView snapshot={snapshot} />}
    </div>
  );
}
```

- [ ] **Step 3: Add route to router.tsx**

Add import at top of `frontend/src/router.tsx`:

```typescript
import SystemPage from "./pages/SystemPage";
```

Add route after the opps compare route (inside the children array):

```typescript
        { path: "system", element: <SystemPage /> },
```

- [ ] **Step 4: Add nav item to TopNav.tsx**

In `frontend/src/components/TopNav.tsx`, add to the `NAV_ITEMS` array:

```typescript
  { label: "System", path: "/system" },
```

- [ ] **Step 5: Create stub PipelineView and AgentsView (so TypeScript compiles)**

```tsx
// frontend/src/components/system/PipelineView.tsx
import type { SystemSnapshot } from "./types";

export function PipelineView({ snapshot }: { snapshot: SystemSnapshot }) {
  return <div className="flex flex-1 overflow-hidden">Pipeline view — {snapshot.skills.length} skills</div>;
}
```

```tsx
// frontend/src/components/system/AgentsView.tsx
import type { SystemSnapshot } from "./types";

export function AgentsView({ snapshot }: { snapshot: SystemSnapshot }) {
  return <div className="flex flex-1 overflow-hidden">Agents view — {snapshot.agents.length} agents</div>;
}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SystemPage.tsx frontend/src/components/system/SystemHeader.tsx frontend/src/components/system/PipelineView.tsx frontend/src/components/system/AgentsView.tsx frontend/src/router.tsx frontend/src/components/TopNav.tsx
git commit -m "feat(system): add SystemPage shell with route, nav, and header"
```

---

## Task 8: Frontend — Pipeline view (by phase)

Three-pane layout: phase sidebar, skill list, skill detail pane.

**Files:**
- Replace: `frontend/src/components/system/PipelineView.tsx`
- Create: `frontend/src/components/system/PipelineSidebar.tsx`
- Create: `frontend/src/components/system/SkillList.tsx`
- Create: `frontend/src/components/system/SkillRow.tsx`
- Create: `frontend/src/components/system/SkillDetailPane.tsx`
- Create: `frontend/src/components/system/ArtifactList.tsx`

- [ ] **Step 1: Create PipelineSidebar**

```tsx
// frontend/src/components/system/PipelineSidebar.tsx
import { cn } from "@/lib/utils";
import type { SkillSummary } from "./types";

const PHASE_COLORS: Record<string, string> = {
  "app-building": "bg-blue-500",
  "connect-setup": "bg-green-500",
  "llo-management": "bg-amber-500",
  "closeout": "bg-purple-500",
};

const PHASE_LABELS: Record<string, string> = {
  "app-building": "App Building",
  "connect-setup": "Connect Setup",
  "llo-management": "LLO Management",
  "closeout": "Closeout",
};

type FilterKind = "all" | "app-building" | "connect-setup" | "llo-management" | "closeout" | "judge" | "gate" | "recurring";

interface Props {
  skills: SkillSummary[];
  phases: string[];
  filter: FilterKind;
  onFilterChange: (f: FilterKind) => void;
}

export type { FilterKind };

export function PipelineSidebar({ skills, phases, filter, onFilterChange }: Props) {
  const judgeCount = skills.filter((s) => s.has_judge).length;
  const gateCount = skills.filter((s) => s.is_gate).length;
  const recurringCount = skills.filter((s) => s.is_recurring).length;

  return (
    <div className="flex flex-col gap-1 p-2">
      <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Phases
      </div>
      <SidebarItem active={filter === "all"} onClick={() => onFilterChange("all")} label="All Skills" count={skills.length} />
      {phases.map((phase) => (
        <SidebarItem
          key={phase}
          active={filter === phase}
          onClick={() => onFilterChange(phase as FilterKind)}
          label={PHASE_LABELS[phase] ?? phase}
          count={skills.filter((s) => s.phase === phase).length}
          dotColor={PHASE_COLORS[phase]}
        />
      ))}

      <div className="mt-3 px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Filters
      </div>
      <SidebarItem active={filter === "judge"} onClick={() => onFilterChange("judge")} label="Has Judge" count={judgeCount} dotColor="bg-purple-500" />
      <SidebarItem active={filter === "gate"} onClick={() => onFilterChange("gate")} label="Has Gate" count={gateCount} dotColor="bg-amber-500" />
      <SidebarItem active={filter === "recurring"} onClick={() => onFilterChange("recurring")} label="Recurring" count={recurringCount} dotColor="bg-cyan-500" />
    </div>
  );
}

function SidebarItem({
  active,
  onClick,
  label,
  count,
  dotColor,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  dotColor?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs",
        active
          ? "bg-primary/10 text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {dotColor && <span className={cn("h-2 w-2 shrink-0 rounded-full", dotColor)} />}
      <span className="flex-1">{label}</span>
      <span className="text-[10px] text-muted-foreground">{count}</span>
    </button>
  );
}
```

- [ ] **Step 2: Create ArtifactList (shared between skill and agent detail panes)**

```tsx
// frontend/src/components/system/ArtifactList.tsx
import type { ArtifactRef } from "./types";

interface Props {
  produced: ArtifactRef[];
  consumed: ArtifactRef[];
}

export function ArtifactList({ produced, consumed }: Props) {
  if (produced.length === 0 && consumed.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      {produced.map((a) => (
        <ArtifactItem key={a.path} artifact={a} role="produces" />
      ))}
      {consumed.map((a) => (
        <ArtifactItem key={a.path} artifact={a} role="consumes" />
      ))}
    </div>
  );
}

function ArtifactItem({ artifact, role }: { artifact: ArtifactRef; role: "produces" | "consumes" }) {
  return (
    <div className="flex items-center gap-2 rounded border border-border bg-card px-2.5 py-1.5 text-xs">
      <span className="font-mono text-foreground">{artifact.path}</span>
      <span className="ml-auto flex-shrink-0 text-[10px] font-semibold uppercase" style={{
        color: role === "produces" ? "var(--status-ok)" : "var(--status-info)",
      }}>
        {role}
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Create SkillRow**

```tsx
// frontend/src/components/system/SkillRow.tsx
import { cn } from "@/lib/utils";
import type { SkillSummary } from "./types";

interface Props {
  skill: SkillSummary;
  isSelected: boolean;
  onClick: () => void;
}

export function SkillRow({ skill, isSelected, onClick }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left text-xs transition-colors",
        isSelected ? "bg-primary/10 border-l-2 border-l-primary" : "hover:bg-accent",
      )}
    >
      <span
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold",
          isSelected ? "border-primary text-primary" : "border-border text-muted-foreground",
        )}
      >
        {skill.ordinal ?? "—"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-medium text-foreground">{skill.display_name}</div>
        {skill.primary_output && (
          <div className="font-mono text-[10px] text-muted-foreground">{skill.primary_output}</div>
        )}
      </div>
      <div className="flex shrink-0 gap-1">
        {skill.has_judge && <Badge label="Judge" className="bg-purple-500/15 text-purple-400" />}
        {skill.is_gate && <Badge label="Gate" className="bg-amber-500/15 text-amber-400" />}
        {skill.is_recurring && <Badge label="Recurring" className="bg-cyan-500/15 text-cyan-400" />}
      </div>
    </button>
  );
}

function Badge({ label, className }: { label: string; className: string }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase", className)}>
      {label}
    </span>
  );
}
```

- [ ] **Step 4: Create SkillDetailPane**

```tsx
// frontend/src/components/system/SkillDetailPane.tsx
import { useEffect, useState } from "react";
import { getSkillDetail } from "../../api/system";
import type { SkillDetail, SkillSummary } from "./types";
import { ArtifactList } from "./ArtifactList";
import { MarkdownRenderer } from "../MarkdownRenderer";

interface Props {
  skill: SkillSummary;
}

export function SkillDetailPane({ skill }: Props) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    getSkillDetail(skill.name)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [skill.name]);

  return (
    <div className="flex flex-col gap-5 overflow-y-auto p-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-foreground">{skill.display_name}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{skill.description}</p>
      </div>

      {/* Metadata grid */}
      <Section title="Metadata">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <MetaItem label="Phase" value={skill.phase ?? "—"} />
          <MetaItem label="Ordinal" value={skill.ordinal ? `${skill.ordinal} of 19` : "—"} />
          <MetaItem label="Judge" value={skill.has_judge ? "Yes" : "No"} />
          <MetaItem label="Gate" value={skill.is_gate ? "Yes" : "No"} />
          <MetaItem label="Recurring" value={skill.is_recurring ? "Yes" : "No"} />
          <MetaItem label="Primary output" value={skill.primary_output ?? "—"} />
        </div>
      </Section>

      {/* Artifacts */}
      {(skill.artifacts_produced.length > 0 || skill.artifacts_consumed.length > 0) && (
        <Section title="Artifacts">
          <ArtifactList produced={skill.artifacts_produced} consumed={skill.artifacts_consumed} />
        </Section>
      )}

      {/* Full SKILL.md */}
      {detail?.body_markdown && (
        <Section title="SKILL.md">
          <MarkdownRenderer content={detail.body_markdown} />
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 border-b border-border pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="font-medium text-foreground">{value}</div>
    </div>
  );
}
```

- [ ] **Step 5: Create SkillList**

```tsx
// frontend/src/components/system/SkillList.tsx
import type { SkillSummary } from "./types";
import { SkillRow } from "./SkillRow";

const PHASE_LABELS: Record<string, string> = {
  "app-building": "App Building",
  "connect-setup": "Connect Setup",
  "llo-management": "LLO Management",
  "closeout": "Closeout",
};

const PHASE_DOT_COLORS: Record<string, string> = {
  "app-building": "bg-blue-500",
  "connect-setup": "bg-green-500",
  "llo-management": "bg-amber-500",
  "closeout": "bg-purple-500",
};

interface Props {
  skills: SkillSummary[];
  selectedSkill: string | null;
  onSelectSkill: (name: string) => void;
}

export function SkillList({ skills, selectedSkill, onSelectSkill }: Props) {
  // Group by phase, preserving ordinal order within each phase.
  // Utility skills (phase=null) go in a separate "Utility" group at the end.
  const phases = [...new Set(skills.filter((s) => s.phase).map((s) => s.phase!))];
  const utilitySkills = skills.filter((s) => s.phase === null);

  return (
    <div className="overflow-y-auto">
      {phases.map((phase) => {
        const phaseSkills = skills.filter((s) => s.phase === phase);
        if (phaseSkills.length === 0) return null;
        return (
          <div key={phase}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-background px-4 py-2">
              <span className={`h-2 w-2 rounded-full ${PHASE_DOT_COLORS[phase] ?? "bg-muted-foreground"}`} />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {PHASE_LABELS[phase] ?? phase}
              </span>
              <span className="flex-1 border-t border-border" />
            </div>
            {phaseSkills.map((skill) => (
              <SkillRow
                key={skill.name}
                skill={skill}
                isSelected={selectedSkill === skill.name}
                onClick={() => onSelectSkill(skill.name)}
              />
            ))}
          </div>
        );
      })}
      {utilitySkills.length > 0 && (
        <div>
          <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-background px-4 py-2">
            <span className="h-2 w-2 rounded-full bg-muted-foreground" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Utility Skills
            </span>
            <span className="flex-1 border-t border-border" />
          </div>
          {utilitySkills.map((skill) => (
            <SkillRow
              key={skill.name}
              skill={skill}
              isSelected={selectedSkill === skill.name}
              onClick={() => onSelectSkill(skill.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Replace PipelineView stub with full implementation**

```tsx
// frontend/src/components/system/PipelineView.tsx
import { useState } from "react";

import type { SystemSnapshot, SkillSummary } from "./types";
import { PipelineSidebar, type FilterKind } from "./PipelineSidebar";
import { SkillList } from "./SkillList";
import { SkillDetailPane } from "./SkillDetailPane";
import { EmptyState } from "../opps/LoadingStates";

interface Props {
  snapshot: SystemSnapshot;
}

function applyFilter(skills: SkillSummary[], filter: FilterKind): SkillSummary[] {
  if (filter === "all") return skills;
  if (filter === "judge") return skills.filter((s) => s.has_judge);
  if (filter === "gate") return skills.filter((s) => s.is_gate);
  if (filter === "recurring") return skills.filter((s) => s.is_recurring);
  // Phase filter
  return skills.filter((s) => s.phase === filter);
}

export function PipelineView({ snapshot }: Props) {
  const [filter, setFilter] = useState<FilterKind>("all");
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);

  const filtered = applyFilter(snapshot.skills, filter);
  const selected = selectedSkill ? snapshot.skills.find((s) => s.name === selectedSkill) ?? null : null;

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="w-[200px] shrink-0 overflow-y-auto border-r border-border">
        <PipelineSidebar skills={snapshot.skills} phases={snapshot.phases} filter={filter} onFilterChange={setFilter} />
      </aside>
      <main className="flex-1 overflow-hidden">
        <SkillList skills={filtered} selectedSkill={selectedSkill} onSelectSkill={setSelectedSkill} />
      </main>
      <section className="w-[420px] shrink-0 border-l border-border">
        {selected ? (
          <SkillDetailPane skill={selected} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState title="Select a skill" description="Click a skill to see its details." />
          </div>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/system/PipelineSidebar.tsx frontend/src/components/system/ArtifactList.tsx frontend/src/components/system/SkillRow.tsx frontend/src/components/system/SkillDetailPane.tsx frontend/src/components/system/SkillList.tsx frontend/src/components/system/PipelineView.tsx
git commit -m "feat(system): implement Pipeline view with sidebar, skill list, and detail pane"
```

---

## Task 9: Frontend — Agents view (by agent)

Agent workflow cards with parallel groups, gates, judges.

**Files:**
- Replace: `frontend/src/components/system/AgentsView.tsx`
- Create: `frontend/src/components/system/AgentSidebar.tsx`
- Create: `frontend/src/components/system/AgentCard.tsx`
- Create: `frontend/src/components/system/AgentDetailPane.tsx`

- [ ] **Step 1: Create AgentSidebar**

```tsx
// frontend/src/components/system/AgentSidebar.tsx
import { cn } from "@/lib/utils";
import type { AgentSummary } from "./types";

const AGENT_COLORS: Record<string, string> = {
  "ace-orchestrator": "bg-red-500",
  "app-builder": "bg-blue-500",
  "connect-setup": "bg-green-500",
  "llo-manager": "bg-amber-500",
  "closeout": "bg-purple-500",
  "ocs-tester": "bg-cyan-500",
};

interface Props {
  agents: AgentSummary[];
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
}

export function AgentSidebar({ agents, selectedAgent, onSelectAgent }: Props) {
  return (
    <div className="flex flex-col gap-1 p-2">
      <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Agents
      </div>
      <button
        type="button"
        onClick={() => onSelectAgent(null)}
        className={cn(
          "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs",
          selectedAgent === null
            ? "bg-primary/10 text-foreground"
            : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )}
      >
        <span className="flex-1">All Agents</span>
        <span className="text-[10px] text-muted-foreground">{agents.length}</span>
      </button>
      {agents.map((agent) => (
        <button
          key={agent.name}
          type="button"
          onClick={() => onSelectAgent(agent.name)}
          className={cn(
            "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs",
            selectedAgent === agent.name
              ? "bg-primary/10 text-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-foreground",
          )}
        >
          <span className={cn("h-2 w-2 shrink-0 rounded-full", AGENT_COLORS[agent.name] ?? "bg-muted-foreground")} />
          <span className="flex-1 truncate">{agent.name}</span>
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create AgentCard**

```tsx
// frontend/src/components/system/AgentCard.tsx
import { cn } from "@/lib/utils";
import type { AgentSummary, SkillSummary } from "./types";

const AGENT_COLORS: Record<string, string> = {
  "ace-orchestrator": "text-red-400",
  "app-builder": "text-blue-400",
  "connect-setup": "text-green-400",
  "llo-manager": "text-amber-400",
  "closeout": "text-purple-400",
  "ocs-tester": "text-cyan-400",
};

const AGENT_BADGE_COLORS: Record<string, string> = {
  "ace-orchestrator": "bg-red-500/15 text-red-400",
  "app-builder": "bg-blue-500/15 text-blue-400",
  "connect-setup": "bg-green-500/15 text-green-400",
  "llo-manager": "bg-amber-500/15 text-amber-400",
  "closeout": "bg-purple-500/15 text-purple-400",
  "ocs-tester": "bg-cyan-500/15 text-cyan-400",
};

// Map agents to the skills they own (derived from phase)
const AGENT_PHASES: Record<string, string> = {
  "app-builder": "app-building",
  "connect-setup": "connect-setup",
  "llo-manager": "llo-management",
  "closeout": "closeout",
};

interface Props {
  agent: AgentSummary;
  skills: SkillSummary[];
  isSelected: boolean;
  onClick: () => void;
}

export function AgentCard({ agent, skills, isSelected, onClick }: Props) {
  const phase = AGENT_PHASES[agent.name];
  const ownedSkills = phase ? skills.filter((s) => s.phase === phase) : [];

  return (
    <div className={cn("mx-4 my-3 overflow-hidden rounded-lg border border-border bg-card", isSelected && "ring-1 ring-primary")}>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-accent"
      >
        <div>
          <div className={cn("text-sm font-semibold", AGENT_COLORS[agent.name] ?? "text-foreground")}>
            {agent.name}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">{agent.description}</div>
        </div>
        {phase && (
          <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase", AGENT_BADGE_COLORS[agent.name] ?? "")}>
            {phase.replace("-", " ")}
          </span>
        )}
      </button>
      {ownedSkills.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          {ownedSkills.map((skill, idx) => (
            <div key={skill.name} className="flex items-start gap-3 pb-3 last:pb-0 relative">
              {idx < ownedSkills.length - 1 && (
                <div className="absolute left-[11px] top-7 bottom-0 w-px bg-border" />
              )}
              <span
                className={cn(
                  "relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold",
                  skill.is_gate ? "border-amber-500 text-amber-400" : skill.has_judge ? "border-purple-500 text-purple-400" : "border-border text-muted-foreground",
                )}
              >
                {skill.ordinal}
              </span>
              <div className="pt-0.5">
                <div className="text-xs font-medium text-foreground">{skill.display_name}</div>
                <div className="text-[10px] text-muted-foreground">
                  {[
                    skill.is_gate && "Gate",
                    skill.has_judge && "Judge",
                    skill.is_recurring && "Recurring",
                  ].filter(Boolean).join(" · ") || ""}
                </div>
                {skill.primary_output && (
                  <span className="mt-1 inline-block rounded bg-status-ok/10 px-1.5 py-0.5 font-mono text-[10px] text-status-ok">
                    {skill.primary_output}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create AgentDetailPane**

```tsx
// frontend/src/components/system/AgentDetailPane.tsx
import { useEffect, useState } from "react";
import { getAgentDetail } from "../../api/system";
import type { AgentDetail, AgentSummary, SkillSummary } from "./types";
import { MarkdownRenderer } from "../MarkdownRenderer";

const AGENT_PHASES: Record<string, string> = {
  "app-builder": "app-building",
  "connect-setup": "connect-setup",
  "llo-manager": "llo-management",
  "closeout": "closeout",
};

interface Props {
  agent: AgentSummary;
  skills: SkillSummary[];
}

export function AgentDetailPane({ agent, skills }: Props) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    getAgentDetail(agent.name)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [agent.name]);

  const phase = AGENT_PHASES[agent.name];
  const ownedSkills = phase ? skills.filter((s) => s.phase === phase) : [];
  const judgeCount = ownedSkills.filter((s) => s.has_judge).length;
  const gateCount = ownedSkills.filter((s) => s.is_gate).length;

  return (
    <div className="flex flex-col gap-5 overflow-y-auto p-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground">{agent.name}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{agent.description}</p>
      </div>

      <Section title="Agent Metadata">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <MetaItem label="Phase" value={phase ?? "Lifecycle"} />
          <MetaItem label="Skills" value={String(ownedSkills.length)} />
          <MetaItem label="Gates" value={String(gateCount)} />
          <MetaItem label="Judges" value={String(judgeCount)} />
          <MetaItem label="Model" value={agent.model || "—"} />
        </div>
      </Section>

      {detail?.body_markdown && (
        <Section title="Agent Definition">
          <MarkdownRenderer content={detail.body_markdown} />
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 border-b border-border pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="font-medium text-foreground">{value}</div>
    </div>
  );
}
```

- [ ] **Step 4: Replace AgentsView stub with full implementation**

```tsx
// frontend/src/components/system/AgentsView.tsx
import { useState } from "react";

import type { SystemSnapshot } from "./types";
import { AgentSidebar } from "./AgentSidebar";
import { AgentCard } from "./AgentCard";
import { AgentDetailPane } from "./AgentDetailPane";
import { EmptyState } from "../opps/LoadingStates";

interface Props {
  snapshot: SystemSnapshot;
}

export function AgentsView({ snapshot }: Props) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const agents = selectedAgent
    ? snapshot.agents.filter((a) => a.name === selectedAgent)
    : snapshot.agents;

  const selected = selectedAgent ? snapshot.agents.find((a) => a.name === selectedAgent) ?? null : null;

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="w-[200px] shrink-0 overflow-y-auto border-r border-border">
        <AgentSidebar agents={snapshot.agents} selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} />
      </aside>
      <main className="flex-1 overflow-y-auto">
        {agents.map((agent) => (
          <AgentCard
            key={agent.name}
            agent={agent}
            skills={snapshot.skills}
            isSelected={selectedAgent === agent.name}
            onClick={() => setSelectedAgent(agent.name === selectedAgent ? null : agent.name)}
          />
        ))}
      </main>
      <section className="w-[420px] shrink-0 border-l border-border">
        {selected ? (
          <AgentDetailPane agent={selected} skills={snapshot.skills} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState title="Select an agent" description="Click an agent to see its details." />
          </div>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/system/AgentSidebar.tsx frontend/src/components/system/AgentCard.tsx frontend/src/components/system/AgentDetailPane.tsx frontend/src/components/system/AgentsView.tsx
git commit -m "feat(system): implement Agents view with cards, sidebar, and detail pane"
```

---

## Task 10: Integration test — full stack smoke test

Start the dev server and verify the System tab loads with real ACE plugin data.

**Files:** None (manual verification)

- [ ] **Step 1: Run backend tests**

Run: `pytest -v`
Expected: All tests pass including the new system tests.

- [ ] **Step 2: Start the dev server**

Run: `docker compose up` (or the local dev equivalent)

- [ ] **Step 3: Navigate to the System tab**

Open `http://localhost:8000/ace/system` in a browser.

Verify:
- The page loads without errors
- The subheader shows "System Blueprint" with skill/agent/phase counts
- The Pipeline view shows all 19 skills grouped by phase
- Clicking a skill loads its detail pane with metadata, artifacts, and SKILL.md content
- The markdown renders correctly (headings, code blocks, lists, tables)
- Switching to the Agents view shows agent cards with workflow steps
- The version banner appears if the local plugin is behind remote (or is hidden if up to date)

- [ ] **Step 4: Verify the Pipeline sidebar filters work**

Click each phase filter and verify only skills from that phase are shown.
Click "Has Judge" and verify only the 10 judge-enabled skills appear.
Click "Has Gate" and verify only the 4 gated skills appear.

- [ ] **Step 5: Verify the Agents view**

Click each agent in the sidebar and verify the agent card expands with its workflow steps.
Click an agent card header to load the detail pane with the agent definition markdown.

- [ ] **Step 6: Commit any fixes discovered during integration testing**

```bash
git add -u
git commit -m "fix(system): integration test fixes"
```

(Only if fixes were needed. Skip if everything worked.)
