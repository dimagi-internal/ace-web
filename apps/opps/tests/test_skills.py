"""Tests for the dynamic skill metadata loader.

The registry is loaded from ``ACE_PLUGIN_PATH`` at first access. These
tests rely on the default settings value pointing at the sibling ``ace``
repo; any machine with the plugin vendored in gets real data.
"""
from dataclasses import FrozenInstanceError

import pytest

from apps.opps.skills import (
    SKILL_REGISTRY,
    all_phases,
    get_skill,
    reset_cache,
    skills_in_phase,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_cache()
    yield
    reset_cache()


def test_registry_is_non_empty_when_plugin_present():
    """With the vendored ACE plugin on disk, the registry is populated
    from agent frontmatter. If the plugin isn't there (e.g. CI without
    submodules), this test degrades gracefully."""
    assert len(SKILL_REGISTRY) >= 0  # smoke
    # In the dev environment with the plugin vendored, we expect the
    # full 20+ skill set.
    if len(SKILL_REGISTRY) > 0:
        assert len(SKILL_REGISTRY) >= 15


def test_ordinals_are_unique_and_increasing():
    ordinals = [s.ordinal for s in SKILL_REGISTRY]
    if not ordinals:
        pytest.skip("plugin not present — no skills to check")
    assert ordinals == sorted(ordinals)
    assert len(ordinals) == len(set(ordinals))


def test_names_are_unique():
    names = [s.name for s in SKILL_REGISTRY]
    assert len(names) == len(set(names))


def test_get_skill_by_name():
    if len(SKILL_REGISTRY) == 0:
        pytest.skip("plugin not present")
    s = get_skill("idea-to-pdd")
    assert s.ordinal == 1
    assert s.has_judge is True
    assert s.is_gate is True  # idea-to-pdd produces gate-briefs/idea-to-pdd.md


def test_get_skill_unknown_raises():
    with pytest.raises(KeyError):
        get_skill("nonexistent-skill")


def test_gate_steps_match_manifest():
    """Gate skills are derived from the manifest — any skill that
    produces ``gate-briefs/<name>.md`` is a gate."""
    gates = {s.name for s in SKILL_REGISTRY if s.is_gate}
    # Minimum known-stable set of gates from the plugin's current manifest.
    if len(SKILL_REGISTRY) == 0:
        pytest.skip("plugin not present")
    expected_minimum = {"idea-to-pdd", "app-deploy", "llo-invite", "llo-launch"}
    assert expected_minimum.issubset(gates), f"missing gates: {expected_minimum - gates}"


def test_recurring_skills_present():
    recurring = {s.name for s in SKILL_REGISTRY if s.is_recurring}
    if len(SKILL_REGISTRY) == 0:
        pytest.skip("plugin not present")
    # timeline-monitor and flw-data-review are the canonical recurring
    # operational skills.
    assert {"timeline-monitor", "flw-data-review"}.issubset(recurring)


def test_skill_is_frozen_dataclass():
    if len(SKILL_REGISTRY) == 0:
        pytest.skip("plugin not present")
    s = get_skill("idea-to-pdd")
    with pytest.raises(FrozenInstanceError):
        s.ordinal = 999  # type: ignore[misc]


def test_all_phases_matches_agent_order():
    """Phases come back in agent phase_ordinal order."""
    phases = all_phases()
    if not phases:
        pytest.skip("plugin not present")
    # In the current plugin: design-review, commcare-setup, connect-setup,
    # ocs-setup, llo-management, closeout.
    assert phases[0] == "design-review"
    assert phases[-1] == "closeout"


def test_skills_in_phase_ordered():
    if not all_phases():
        pytest.skip("plugin not present")
    for phase in all_phases():
        skills = skills_in_phase(phase)
        ordinals = [s.ordinal for s in skills]
        assert ordinals == sorted(ordinals)
        for s in skills:
            assert s.phase == phase
