"""Filesystem reader for the ACE plugin repo.

Skill/phase metadata is driven by the ACE plugin's **agent frontmatter**,
not a hardcoded Python registry. Each phase agent declares its phase name,
its position in the lifecycle, and the ordered list of skills it orchestrates.
This makes the ACE plugin the single source of truth — adding a skill or
phase is a one-file edit in the plugin, no ace-web change required.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from apps.system.parsers import parse_artifact_manifest, parse_frontmatter

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
        for entry in meta.get("skills") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
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
            "phases": [],
            "warning": f"ACE plugin not found at {plugin_path}",
        }

    skill_files = _load_skill_files(pp)
    agent_files = _load_agent_files(pp)
    artifacts = _load_artifacts(pp)

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
