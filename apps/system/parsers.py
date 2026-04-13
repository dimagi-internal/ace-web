"""Pure parsing functions for ACE system files.

No Django dependencies — testable in isolation.
"""

from __future__ import annotations

import json
import logging
import re

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter delimited by ``---`` from a markdown file.

    Returns ``(metadata_dict, body_string)``.  When no frontmatter is found,
    returns ``({}, full_text)``.
    """
    if not text:
        return {}, ""

    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw_yaml, body = m.group(1), m.group(2)
    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        logger.warning("Invalid YAML in frontmatter, treating as no frontmatter")
        return {}, text

    if not isinstance(meta, dict):
        return {}, text

    return meta, body


# ---------------------------------------------------------------------------
# Artifact manifest (TypeScript → Python)
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[str, str] = {
    "build": "app-building",
    "setup": "connect-setup",
    "operate": "llo-management",
    "closeout": "closeout",
}

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _normalize_keys(obj: dict) -> dict:
    """Convert camelCase keys to snake_case and normalize phase values."""
    out: dict = {}
    for k, v in obj.items():
        snake = _camel_to_snake(k)
        if snake == "phase" and isinstance(v, str):
            v = _PHASE_MAP.get(v, v)
        out[snake] = v
    return out


def parse_artifact_manifest(ts_source: str) -> list[dict]:
    """Parse the ``ARTIFACT_MANIFEST`` array from a TypeScript source string.

    Steps:
    1. Extract the array body between ``ARTIFACT_MANIFEST...= [`` and ``] as const;``
    2. Normalize TS syntax to JSON (strip comments, quote keys, etc.)
    3. Parse as JSON
    4. Normalize keys to snake_case and phase values to canonical names

    Returns ``[]`` on any parse failure.
    """
    try:
        return _parse_artifact_manifest_inner(ts_source)
    except Exception:
        logger.debug("Failed to parse artifact manifest", exc_info=True)
        return []


def _parse_artifact_manifest_inner(ts_source: str) -> list[dict]:
    # 1. Extract the array body. Allow an optional TS type annotation between
    # the identifier and ``=``, e.g. ``ARTIFACT_MANIFEST: readonly Entry[] = [``.
    m = re.search(r"ARTIFACT_MANIFEST\b[^=]*=\s*\[", ts_source)
    if not m:
        return []
    start = m.end()

    # Find the matching `] as const;` (or just `]`)
    end_match = re.search(r"]\s*(?:as\s+const\s*)?;", ts_source[start:])
    if not end_match:
        return []
    array_body = ts_source[start : start + end_match.start()]

    # 2. Normalize TS → JSON
    text = _ts_to_json_array(array_body)

    # 3. Parse
    entries = json.loads(f"[{text}]")

    # 4. Normalize
    return [_normalize_keys(e) for e in entries]


def _ts_to_json_array(text: str) -> str:
    """Best-effort transform of TypeScript object-literal array body to JSON."""
    # Strip single-line comments
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)

    # Strip multi-line comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # Single quotes → double quotes
    text = text.replace("'", '"')

    # Add quotes to bare keys: `  skillSlug:` → `  "skillSlug":`
    text = re.sub(r"(\s)(\w+)\s*:", r'\1"\2":', text)

    # Remove trailing commas before } or ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # Remove a trailing comma at the very end (before the wrapping `]` we add)
    text = re.sub(r",\s*$", "", text)

    return text
