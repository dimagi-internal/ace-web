"""Filesystem reader for the ACE plugin repo.

Skill/phase metadata is driven by the ACE plugin's **agent frontmatter**,
not a hardcoded Python registry. Each phase agent declares its phase name,
its position in the lifecycle, and the ordered list of skills it orchestrates.
This makes the ACE plugin the single source of truth — adding a skill or
phase is a one-file edit in the plugin, no ace-web change required.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from pathlib import Path
from typing import Any

from apps.system.parsers import parse_artifact_manifest, parse_frontmatter, parse_mcp_tools

log = logging.getLogger(__name__)


def _extract_h1(body: str) -> str | None:
    """Extract the first h1 heading from markdown body."""
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def _titlecase_kebab(name: str) -> str:
    """Convert kebab-case to Title Case: 'idea-to-pdd' -> 'Idea To Idd'."""
    return " ".join(w.capitalize() for w in name.split("-"))


def _load_skill_files(plugin_path: Path) -> dict[str, tuple[dict, str]]:
    """Load all SKILL.md files. Returns {name: (frontmatter, body)}."""
    skills_dir = plugin_path / "skills"
    result: dict[str, tuple[dict, str]] = {}
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
    result: dict[str, tuple[dict, str]] = {}
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


_TOOL_NAME_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")


def _resolve_server_path(plugin_path: Path, server_args: list[Any]) -> Path | None:
    """Resolve the .ts file path from a plugin.json mcpServers[X].args entry.

    The args list looks like ``["tsx", "${CLAUDE_PLUGIN_ROOT}/mcp/foo.ts"]``.
    Strip the placeholder and join with plugin_path.
    """
    for arg in server_args or []:
        if not isinstance(arg, str):
            continue
        if arg.endswith(".ts"):
            relative = arg.replace("${CLAUDE_PLUGIN_ROOT}", "").lstrip("/")
            candidate = plugin_path / relative
            if candidate.is_file():
                return candidate
    return None


def _load_mcps(
    plugin_path: Path, skill_files: dict[str, tuple[dict, str]]
) -> list[dict[str, Any]]:
    """Load MCP servers and their tools from the plugin's plugin.json.

    For each server declared in plugin.json#mcpServers, locate the .ts source,
    parse ``server.tool('name', ...)`` registrations, and cross-reference each
    tool name against skill bodies to produce ``used_by``.
    """
    plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return []
    try:
        manifest = json.loads(plugin_json.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to parse %s: %s", plugin_json, exc)
        return []

    mcp_servers = manifest.get("mcpServers") or {}
    if not isinstance(mcp_servers, dict):
        return []

    # Build an index of which skills mention each tool name. We scan every
    # skill body once and collect the tool-shaped tokens.
    skill_mentions: dict[str, set[str]] = {}
    for skill_name, (_meta, body) in skill_files.items():
        if not body:
            continue
        for tok in _TOOL_NAME_RE.findall(body):
            skill_mentions.setdefault(tok, set()).add(skill_name)

    servers: list[dict[str, Any]] = []
    for server_name in sorted(mcp_servers.keys()):
        cfg = mcp_servers[server_name] or {}
        ts_path = _resolve_server_path(plugin_path, cfg.get("args") or [])
        if ts_path is None:
            servers.append(
                {
                    "name": server_name,
                    "source_file": None,
                    "tools": [],
                    "warning": "server file not found",
                }
            )
            continue
        try:
            ts_source = ts_path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("Failed to read %s: %s", ts_path, exc)
            continue
        tools = parse_mcp_tools(ts_source)
        for tool in tools:
            tool["used_by"] = sorted(skill_mentions.get(tool["name"], set()))
        servers.append(
            {
                "name": server_name,
                "source_file": str(ts_path.relative_to(plugin_path)),
                "tools": tools,
                "warning": None,
            }
        )
    return servers


def _phase_skill_entries(
    agent_files: dict[str, tuple[dict, str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Derive the ordered skill list and phase list from agent frontmatter.

    Returns (phases, skill_index_by_name). Phases come in phase_ordinal order.
    Skill ordinals are assigned globally across phases (1..N), with recurring
    skills placed immediately after their phase's non-recurring skills.
    """
    phase_agents: list[tuple[int, dict, str]] = []
    for name, (meta, _body) in agent_files.items():
        phase = meta.get("phase")
        ord_val = meta.get("phase_ordinal")
        if phase and isinstance(ord_val, int):
            phase_agents.append((ord_val, meta, name))
    phase_agents.sort(key=lambda x: x[0])

    phases: list[dict[str, Any]] = []
    skill_index: dict[str, dict[str, Any]] = {}
    global_ordinal = 0

    for phase_ord, meta, agent_name in phase_agents:
        phase_name = meta["phase"]
        phases.append({
            "name": phase_name,
            "display_name": meta.get("phase_display", phase_name),
            "ordinal": phase_ord,
            "agent": agent_name,
        })

        # Non-recurring skills first, then recurring — mirrors the visual
        # order and matches the historical ordinal convention.
        #
        # First-phase-wins for duplicates: a skill declared in multiple
        # agent frontmatters (e.g. ocs-chatbot-qa appears as non-recurring
        # in ocs-setup AND as recurring in llo-manager) keeps its first
        # (earliest phase) placement. Later declarations are informational
        # only — they don't create a second Workbench row.
        for entry in meta.get("skills") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            if entry["name"] in skill_index:
                continue
            global_ordinal += 1
            skill_index[entry["name"]] = {
                "phase": phase_name,
                "ordinal": global_ordinal,
                "has_judge": bool(entry.get("has_judge")),
                "is_recurring": False,
                "primary_output": entry.get("primary_output"),
                "agent_name": agent_name,
            }
        for entry in meta.get("recurring_skills") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            if entry["name"] in skill_index:
                continue
            global_ordinal += 1
            skill_index[entry["name"]] = {
                "phase": phase_name,
                "ordinal": global_ordinal,
                "has_judge": bool(entry.get("has_judge")),
                "is_recurring": True,
                "primary_output": entry.get("primary_output"),
                "agent_name": agent_name,
            }

    return phases, skill_index


def _build_skill_summary(
    name: str,
    phase_entry: dict[str, Any] | None,
    meta: dict[str, Any] | None,
    body: str | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a skill summary dict.

    ``phase_entry`` comes from the agent frontmatter (or None for utility
    skills not owned by any phase agent).
    """
    display_name: str | None = None
    if body:
        display_name = _extract_h1(body)
    if not display_name:
        display_name = _titlecase_kebab(name)

    produced = [a for a in artifacts if a.get("produced_by") == name]
    consumed = [a for a in artifacts if name in (a.get("consumed_by") or [])]

    def _artifact_row(a: dict[str, Any]) -> dict[str, Any]:
        return {
            "path": a.get("path", ""),
            "description": a.get("description", ""),
            "required": bool(a.get("required", False)),
        }

    # Primary output: prefer the frontmatter-declared value (optional
    # override) but fall back to the first produced artifact in the
    # manifest. This keeps the manifest as the source of truth for
    # what files a skill actually writes.
    primary_output = (phase_entry or {}).get("primary_output")
    if not primary_output and produced:
        primary_output = produced[0].get("path")

    return {
        "name": name,
        "display_name": display_name,
        "description": (meta or {}).get("description", ""),
        "ordinal": (phase_entry or {}).get("ordinal"),
        "phase": (phase_entry or {}).get("phase"),
        "has_judge": bool((phase_entry or {}).get("has_judge")),
        "is_recurring": bool((phase_entry or {}).get("is_recurring")),
        "primary_output": primary_output,
        "artifacts_produced": [_artifact_row(a) for a in produced],
        "artifacts_consumed": [_artifact_row(a) for a in consumed],
    }


@functools.cache
def load_system_overview(plugin_path: str) -> dict[str, Any]:
    """Load the full system overview from the ACE plugin directory.

    Returns a dict ready for serialization with keys: skills, agents,
    artifacts, phases, warning.

    Cached per process keyed on ``plugin_path`` — the plugin is read-only at
    runtime (it changes only on container rebuild), and this function does
    ~60 file reads + a regex pass over every skill body, so callers on hot
    paths (per-opp loops, per-session serializers) used to bottleneck on it.
    Tests that swap ``ACE_PLUGIN_PATH`` mid-process must call
    ``clear_caches()``; ``apps.opps.skills.reset_cache`` and
    ``apps.opps.serializers.reset_system_overview_cache`` already do so.
    """
    pp = Path(plugin_path)
    if not pp.is_dir():
        return {
            "skills": [],
            "agents": [],
            "artifacts": [],
            "phases": [],
            "mcps": [],
            "warning": f"ACE plugin not found at {plugin_path}",
        }

    skill_files = _load_skill_files(pp)
    agent_files = _load_agent_files(pp)
    artifacts = _load_artifacts(pp)
    mcps = _load_mcps(pp, skill_files)

    phases, skill_index = _phase_skill_entries(agent_files)

    # Assemble skills: phase-owned skills in ordinal order, then utility
    # skills (SKILL.md files not owned by any phase agent) at the end.
    skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill_name, entry in sorted(skill_index.items(), key=lambda kv: kv[1]["ordinal"]):
        fm = skill_files.get(skill_name)
        meta, body = fm if fm else (None, None)
        skills.append(_build_skill_summary(skill_name, entry, meta, body, artifacts))
        seen.add(skill_name)
    for name, (meta, body) in skill_files.items():
        if name not in seen:
            skills.append(_build_skill_summary(name, None, meta, body, artifacts))

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
        "phases": [
            {
                "name": p["name"],
                "display_name": p["display_name"],
                "ordinal": p["ordinal"],
                "agent": p["agent"],
            }
            for p in phases
        ],
        "mcps": mcps,
        "warning": None,
    }


def load_skill_detail(plugin_path: str, skill_name: str) -> dict[str, Any] | None:
    """Load a single skill with full markdown body."""
    pp = Path(plugin_path)
    skill_md = pp / "skills" / skill_name / "SKILL.md"

    # Phase/ordinal data always comes from agent frontmatter — load it once.
    agent_files = _load_agent_files(pp)
    _, skill_index = _phase_skill_entries(agent_files)
    phase_entry = skill_index.get(skill_name)
    artifacts = _load_artifacts(pp)

    if not skill_md.is_file():
        # Skill is agent-declared but missing a SKILL.md file — still
        # return metadata with an empty body. Unknown skills return None.
        if phase_entry is None:
            return None
        summary = _build_skill_summary(skill_name, phase_entry, None, None, artifacts)
        summary["body_markdown"] = ""
        return summary

    text = skill_md.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    summary = _build_skill_summary(skill_name, phase_entry, meta, body, artifacts)
    summary["body_markdown"] = body
    return summary


def get_skill_phase_index(plugin_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Return a mapping of skill_name → {phase, phase_display, phase_ordinal}.

    Reads the ACE plugin's agent frontmatter to derive which phase each skill
    belongs to. Falls back to an empty dict if the plugin path is unset or
    invalid so callers can degrade gracefully.

    ``plugin_path`` defaults to ``settings.ACE_PLUGIN_PATH`` when not provided.
    The settings import is deferred to function-call time to avoid module
    load-order issues (this module is imported by opps/skills.py which may
    load before Django is fully configured in some test contexts).

    Cached per process via ``_get_skill_phase_index_cached`` — the cost
    aggregator and a few serializers call this on hot paths.
    """
    if plugin_path is None:
        # Lazy import to avoid load-order issues at module import time.
        from django.conf import settings  # noqa: PLC0415

        plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "") or ""

    if not plugin_path:
        return {}

    return _get_skill_phase_index_cached(plugin_path)


@functools.cache
def _get_skill_phase_index_cached(plugin_path: str) -> dict[str, dict[str, Any]]:
    pp = Path(plugin_path)
    if not pp.is_dir():
        return {}

    try:
        agent_files = _load_agent_files(pp)
        phases, skill_index = _phase_skill_entries(agent_files)
    except Exception as exc:
        log.warning("get_skill_phase_index: failed to read plugin at %s: %s", plugin_path, exc)
        return {}

    # Build a display_name + ordinal index from the phases list.
    phase_meta: dict[str, tuple[str, int]] = {
        p["name"]: (p["display_name"], p["ordinal"]) for p in phases
    }

    # Skill display names from the System Overview reader (the authoritative
    # human-readable label — same one the System tab shows).
    skill_display_by_name: dict[str, str] = {}
    for s in load_system_overview(str(pp)).get("skills", []):
        if s.get("name"):
            skill_display_by_name[s["name"]] = s.get("display_name") or s["name"]

    def _entry(phase_name: str, skill_name: str) -> dict[str, Any]:
        phase_display, phase_ordinal = phase_meta.get(phase_name, (phase_name, 999))
        return {
            "phase": phase_name,
            "phase_display": phase_display,
            "phase_ordinal": phase_ordinal,
            "skill_display": skill_display_by_name.get(skill_name, skill_name),
        }

    result: dict[str, dict[str, Any]] = {}
    for skill_name, entry in skill_index.items():
        result[skill_name] = _entry(entry["phase"], skill_name)

    # Also index each phase's orchestrator agent by name. An Agent dispatch's
    # subagent_type is the agent name (e.g. "ace:design-review"), not a skill,
    # so it would otherwise miss the lookup. An agent IS its phase, so use the
    # phase_display as the skill_display — preserves canonical capitalization
    # like "OCS Setup" that title-casing the kebab name would lose.
    for p in phases:
        agent_name = p.get("agent")
        if not agent_name or agent_name in result:
            continue
        entry = _entry(p["name"], agent_name)
        entry["skill_display"] = p["display_name"]
        result[agent_name] = entry

    # Also index each skill's eval_skill child (e.g. "idea-to-pdd-eval"
    # declared as eval_skill: of "idea-to-pdd"). They run as part of the same
    # phase as their parent skill and should attribute to it.
    for agent_meta, _body in agent_files.values():
        phase_name = agent_meta.get("phase")
        if not phase_name:
            continue
        for entries in (agent_meta.get("skills") or [], agent_meta.get("recurring_skills") or []):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                eval_name = entry.get("eval_skill")
                if not eval_name or eval_name in result:
                    continue
                result[eval_name] = _entry(phase_name, eval_name)

    return result


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


@functools.cache
def skill_display_names(plugin_path: str) -> dict[str, str]:
    """``{skill_name: display_name}`` derived from ``load_system_overview``.

    Cached per process. Use this from any hot loop or per-row serializer
    that needs to render a skill's friendly name from its slug; the older
    inline pattern (``for s in overview['skills']: if s['name'] == ...``)
    became a bottleneck once it was added to ``SessionSerializer`` and the
    opp-list loop.
    """
    return {
        s["name"]: s.get("display_name") or s["name"]
        for s in (load_system_overview(plugin_path).get("skills") or [])
        if s.get("name")
    }


@functools.cache
def phase_display_names(plugin_path: str) -> dict[str, str]:
    """``{phase_name: display_name}`` derived from ``load_system_overview``.
    Cached per process. Same rationale as ``skill_display_names``."""
    return {
        p["name"]: p.get("display_name") or p["name"]
        for p in (load_system_overview(plugin_path).get("phases") or [])
        if p.get("name")
    }


def clear_caches() -> None:
    """Clear all per-process caches in this module. Tests that swap
    ``ACE_PLUGIN_PATH`` between cases must call this so the next read
    reloads from the new directory."""
    load_system_overview.cache_clear()
    _get_skill_phase_index_cached.cache_clear()
    skill_display_names.cache_clear()
    phase_display_names.cache_clear()
