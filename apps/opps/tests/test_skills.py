"""Tests for the canonical skill metadata registry."""
from dataclasses import FrozenInstanceError

import pytest

from apps.opps.skills import (
    PHASE_APP_BUILDING,
    PHASE_CLOSEOUT,
    PHASE_CONNECT_SETUP,
    PHASE_LLO_MANAGEMENT,
    SKILL_REGISTRY,
    get_skill,
    skills_in_phase,
)


def test_registry_has_nineteen_skills():
    assert len(SKILL_REGISTRY) == 19


def test_ordinals_are_unique_and_sequential():
    ordinals = sorted(s.ordinal for s in SKILL_REGISTRY)
    assert ordinals == list(range(1, 20))


def test_names_are_unique():
    names = [s.name for s in SKILL_REGISTRY]
    assert len(names) == len(set(names))


def test_get_skill_by_name():
    s = get_skill("idea-to-pdd")
    assert s.ordinal == 1
    assert s.phase == PHASE_APP_BUILDING
    assert s.has_judge is True
    assert s.is_gate is True


def test_get_skill_unknown_raises():
    with pytest.raises(KeyError):
        get_skill("nonexistent-skill")


def test_phase_grouping():
    building = skills_in_phase(PHASE_APP_BUILDING)
    assert [s.name for s in building] == [
        "idea-to-pdd",
        "pdd-to-learn-app",
        "pdd-to-deliver-app",
        "app-deploy",
        "app-test",
        "training-materials",
    ]
    setup = skills_in_phase(PHASE_CONNECT_SETUP)
    assert [s.name for s in setup] == [
        "connect-program-setup",
        "connect-opp-setup",
        "llo-invite",
    ]
    llo = skills_in_phase(PHASE_LLO_MANAGEMENT)
    assert len(llo) == 6
    closeout = skills_in_phase(PHASE_CLOSEOUT)
    assert [s.name for s in closeout] == [
        "opp-closeout",
        "llo-feedback",
        "learnings-summary",
        "cycle-grade",
    ]


def test_gate_steps():
    gates = [s.name for s in SKILL_REGISTRY if s.is_gate]
    # From the ACE design spec gate list: idea-to-pdd, app-deploy, llo-invite, llo-launch
    assert set(gates) == {"idea-to-pdd", "app-deploy", "llo-invite", "llo-launch"}


def test_recurring_steps():
    recurring = [s.name for s in SKILL_REGISTRY if s.is_recurring]
    assert set(recurring) == {"timeline-monitor", "flw-data-review"}


def test_skill_is_frozen_dataclass():
    s = get_skill("idea-to-pdd")
    with pytest.raises(FrozenInstanceError):
        s.ordinal = 999  # type: ignore[misc]
