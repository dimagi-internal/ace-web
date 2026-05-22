"""Skill→products crosswalk derived from the ACE plugin artifact manifest.

The artifact manifest (``lib/artifact-manifest.ts`` in the ACE plugin)
declares which skill produces which file. This module turns that into
a lookup ``{skill_slug: [path, ...]}`` for the in-app decisions editor:
when the user edits a decision row, the editor needs to tell them which
files the forked re-run will regenerate, and that's the set of paths
the row's ``source`` skill produces.

Loaded once per process via ``functools.lru_cache``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from apps.system.reader import _load_artifacts

logger = logging.getLogger(__name__)


# Paths excluded from the skill→products map. These are paths that some
# skill technically "produces" but the in-app decisions editor should
# never list as "the fork will regenerate this":
#   - decisions.yaml / decisions.yml: the edit target itself; the forker
#     carries it forward with edits applied, not regenerated.
_EXCLUDED_PATHS = frozenset({"decisions.yaml", "decisions.yml"})


def build_skill_products_map(entries: list[dict]) -> dict[str, list[str]]:
    """Group manifest entries by ``produced_by`` skill slug.

    Entries without a ``produced_by`` or a ``path`` are skipped — they
    describe inputs, scratch files, or other non-product rows. Paths in
    ``_EXCLUDED_PATHS`` are also skipped to keep the affected-docs UI
    from showing tautological entries (e.g. decisions.yaml when the user
    is editing decisions.yaml).
    """
    out: dict[str, list[str]] = {}
    for entry in entries:
        skill = entry.get("produced_by")
        path = entry.get("path")
        if not skill or not path:
            continue
        if path in _EXCLUDED_PATHS:
            continue
        out.setdefault(skill, []).append(path)
    return out


@lru_cache(maxsize=1)
def get_skill_products_map() -> dict[str, list[str]]:
    """Return the {skill_slug: [path,...]} map, cached for the process lifetime.

    Reads ``ACE_PLUGIN_PATH`` from Django settings and parses
    ``lib/artifact-manifest.ts``. Returns an empty dict if the plugin
    path isn't set or the manifest can't be parsed.
    """
    plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "")
    if not plugin_path:
        logger.warning("ACE_PLUGIN_PATH not set; skill-products map is empty")
        return {}
    entries = _load_artifacts(Path(plugin_path))
    return build_skill_products_map(entries)
