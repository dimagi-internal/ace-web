"""Filesystem reader for the ACE plugin repo."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from apps.opps.skills import ALL_PHASES, SKILL_REGISTRY
from apps.system.parsers import parse_artifact_manifest, parse_frontmatter

log = logging.getLogger(__name__)

# Pre-index the registry for O(1) lookups
_REGISTRY_BY_NAME = {s.name: s for s in SKILL_REGISTRY}


def _extract_h1(body: str) -> str | None:
    """Extract the first h1 heading from markdown body."""
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def _titlecase_kebab(name: str) -> str:
    """Convert kebab-case to Title Case: 'idea-to-idd' -> 'Idea To Idd'."""
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


def _build_skill_summary(
    name: str,
    meta: dict[str, Any] | None,
    body: str | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a skill summary dict by merging the registry with SKILL.md data."""
    reg = _REGISTRY_BY_NAME.get(name)

    # Display name: h1 from body, else title-case of kebab name
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
