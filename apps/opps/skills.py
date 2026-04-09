"""Canonical metadata for the 19 ACE skills.

This is the single source of truth that the sync layer, preview extractors,
serializers, and the frontend all consume. Pinned to match the ACE plugin
playbook (../ace/docs/generated/playbook.md). When the ACE plugin adds a new
skill, this registry must be updated to match.

Not a database table because the ACE plugin's skill set is the source of
truth — duplicating it into Postgres would create a sync problem.
"""
from __future__ import annotations

from dataclasses import dataclass

PHASE_APP_BUILDING = "app-building"
PHASE_CONNECT_SETUP = "connect-setup"
PHASE_LLO_MANAGEMENT = "llo-management"
PHASE_CLOSEOUT = "closeout"

ALL_PHASES = (
    PHASE_APP_BUILDING,
    PHASE_CONNECT_SETUP,
    PHASE_LLO_MANAGEMENT,
    PHASE_CLOSEOUT,
)

PHASE_DISPLAY_NAMES = {
    PHASE_APP_BUILDING: "App Building",
    PHASE_CONNECT_SETUP: "Connect Setup",
    PHASE_LLO_MANAGEMENT: "LLO Management",
    PHASE_CLOSEOUT: "Closeout",
}


@dataclass(frozen=True)
class Skill:
    name: str                       # e.g. "idea-to-idd"
    ordinal: int                    # 1..19 across the full lifecycle
    phase: str                      # one of the PHASE_* constants above
    has_judge: bool                 # LLM-as-Judge runs on this step's output
    is_gate: bool                   # human gate required in review mode
    is_recurring: bool              # runs periodically during active opp (weekly)
    primary_output: str             # the "headline" artifact filename for preview extraction


SKILL_REGISTRY: tuple[Skill, ...] = (
    Skill(
        "idea-to-idd", 1, PHASE_APP_BUILDING, True, True, False, "idd.md"
    ),
    Skill(
        "idd-to-learn-app",
        2,
        PHASE_APP_BUILDING,
        True,
        False,
        False,
        "learn-app-brief.md",
    ),
    Skill(
        "idd-to-deliver-app",
        3,
        PHASE_APP_BUILDING,
        True,
        False,
        False,
        "deliver-app-brief.md",
    ),
    Skill(
        "app-deploy",
        4,
        PHASE_APP_BUILDING,
        False,
        True,
        False,
        "deploy-summary.md",
    ),
    Skill(
        "app-test",
        5,
        PHASE_APP_BUILDING,
        True,
        False,
        False,
        "test-results.yaml",
    ),
    Skill(
        "training-materials",
        6,
        PHASE_APP_BUILDING,
        True,
        False,
        False,
        "llo-manager-guide.md",
    ),
    Skill(
        "connect-program-setup",
        7,
        PHASE_CONNECT_SETUP,
        False,
        False,
        False,
        "program-config.md",
    ),
    Skill(
        "connect-opp-setup",
        8,
        PHASE_CONNECT_SETUP,
        False,
        False,
        False,
        "opp-config.md",
    ),
    Skill(
        "llo-invite",
        9,
        PHASE_CONNECT_SETUP,
        False,
        True,
        False,
        "invite-list.md",
    ),
    Skill(
        "llo-onboarding",
        10,
        PHASE_LLO_MANAGEMENT,
        False,
        False,
        False,
        "onboarding-emails.md",
    ),
    Skill(
        "llo-uat",
        11,
        PHASE_LLO_MANAGEMENT,
        False,
        False,
        False,
        "uat-protocol.md",
    ),
    Skill(
        "llo-launch",
        12,
        PHASE_LLO_MANAGEMENT,
        False,
        True,
        False,
        "launch-checklist.md",
    ),
    Skill(
        "ocs-agent-setup",
        13,
        PHASE_LLO_MANAGEMENT,
        True,
        False,
        False,
        "ocs-context.md",
    ),
    Skill(
        "timeline-monitor",
        14,
        PHASE_LLO_MANAGEMENT,
        True,
        False,
        True,
        "timeline-report.md",
    ),
    Skill(
        "flw-data-review",
        15,
        PHASE_LLO_MANAGEMENT,
        True,
        False,
        True,
        "flw-review.md",
    ),
    Skill(
        "opp-closeout",
        16,
        PHASE_CLOSEOUT,
        False,
        False,
        False,
        "invoice-summary.md",
    ),
    Skill(
        "llo-feedback",
        17,
        PHASE_CLOSEOUT,
        False,
        False,
        False,
        "feedback-report.md",
    ),
    Skill(
        "learnings-summary",
        18,
        PHASE_CLOSEOUT,
        False,
        False,
        False,
        "learnings.md",
    ),
    Skill(
        "cycle-grade",
        19,
        PHASE_CLOSEOUT,
        True,
        False,
        False,
        "grade-report.md",
    ),
)

_BY_NAME = {s.name: s for s in SKILL_REGISTRY}


def get_skill(name: str) -> Skill:
    """Return the Skill metadata for a given skill name. Raises KeyError if unknown."""
    return _BY_NAME[name]


def skills_in_phase(phase: str) -> list[Skill]:
    """Return all skills in a phase, ordered by ordinal."""
    return sorted((s for s in SKILL_REGISTRY if s.phase == phase), key=lambda s: s.ordinal)
