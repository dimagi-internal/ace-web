"""Session-bridging helpers.

All DRF view functions have been removed; the v2 Ninja router in
apps/opps/api.py handles discuss, step_chats, and opp_working_session.
This module is kept as a shim because api.py still imports
_skill_md_relative_path via a lazy import.
"""
from __future__ import annotations


def _skill_display_name_lookup() -> dict[str, str]:
    """``{skill_slug: display_name}`` for the current ``ACE_PLUGIN_PATH``."""
    from django.conf import settings as _s

    from apps.system.reader import skill_display_names

    return skill_display_names(getattr(_s, "ACE_PLUGIN_PATH", "") or "")


def _skill_md_relative_path(skill: str) -> str:
    """Return the path of a skill's SKILL.md relative to the ace plugin repo root.

    The ACE plugin lays skills out as ``skills/<skill-name>/SKILL.md``.
    """
    return f"skills/{skill}/SKILL.md"
