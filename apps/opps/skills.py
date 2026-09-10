"""Skill metadata for the Workbench — loaded dynamically from the ACE plugin.

The plugin's agent frontmatter (``phase``, ``phase_ordinal``, ``skills[]``,
``recurring_skills[]``) and its ``lib/artifact-manifest.ts`` are the single
source of truth. Adding or renaming a skill is a one-file edit in the
plugin; no ace-web change required.

Cached per process. Tests that swap ``ACE_PLUGIN_PATH`` must call
``reset_cache()``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from django.conf import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Skill:
    name: str                       # e.g. "idea-to-pdd"
    ordinal: int                    # 1..N across the full lifecycle
    phase: str                      # agent-declared phase name (e.g. "design-review")
    has_judge: bool                 # LLM-as-Judge runs on this step's output
    is_gate: bool                   # human gate required in review mode
    is_recurring: bool              # runs periodically during active opp
    primary_output: str             # "headline" artifact path (relative to opp root)


def _gate_skills(artifacts: list[dict[str, Any]]) -> set[str]:
    """Skills that produce a ``gate-briefs/<skill>.md`` artifact.

    That's the canonical signal for "this skill is a review-mode gate" —
    every gate writes a brief to this path.
    """
    return {
        a.get("produced_by") or ""
        for a in artifacts
        if (a.get("path") or "").startswith("gate-briefs/") and a.get("produced_by")
    }


def _primary_output(skill_name: str, skill_summary: dict, artifacts: list[dict[str, Any]]) -> str:
    """Best-effort headline artifact for preview extraction.

    Preference order:
      1. ``primary_output`` from agent frontmatter (optional override)
      2. Reader's resolved primary_output (first produced artifact)
      3. Empty string — preview fallback in ``previews.py`` will handle it
    """
    explicit = skill_summary.get("primary_output")
    if explicit:
        return explicit
    for art in artifacts:
        if art.get("produced_by") == skill_name:
            return art.get("path") or ""
    return ""


@lru_cache(maxsize=1)
def _load_registry() -> tuple[Skill, ...]:
    # Deferred import to avoid a circular dependency (apps.system.reader
    # imports nothing from apps.opps, but being explicit keeps us safe).
    from apps.system.reader import load_system_overview

    plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "") or ""
    overview = load_system_overview(plugin_path)
    artifacts = overview.get("artifacts") or []
    gates = _gate_skills(artifacts)

    result: list[Skill] = []
    for s in overview.get("skills") or []:
        # Utility skills (no phase owner — e.g. upload-transcript) are
        # not Workbench rows. Only phase-owned skills become steps.
        if s.get("ordinal") is None or not s.get("phase"):
            continue
        name = s["name"]
        result.append(
            Skill(
                name=name,
                ordinal=s["ordinal"],
                phase=s["phase"],
                has_judge=bool(s.get("has_judge")),
                is_gate=name in gates,
                is_recurring=bool(s.get("is_recurring")),
                primary_output=_primary_output(name, s, artifacts),
            )
        )
    result.sort(key=lambda sk: sk.ordinal)
    if not result:
        # Loud once-per-process signal so a misconfigured ACE_PLUGIN_PATH
        # (Docker vendor missing, dev sibling-repo not found) doesn't
        # silently produce an empty Workbench. Tests pin the path
        # explicitly via apps/opps/tests/conftest.py and never hit this.
        log.warning(
            "Skill registry is empty; ACE_PLUGIN_PATH=%r resolved to no agents. "
            "Workbench will render zero step rows until the path is fixed.",
            plugin_path,
        )
    return tuple(result)


def reset_cache() -> None:
    """Clear the cached registry. Tests that override ``ACE_PLUGIN_PATH``
    must call this so the next access reloads from the new plugin dir.

    Also flushes ``apps.system.reader``'s per-path caches — the registry
    is built from ``load_system_overview`` and tests that swap the plugin
    path expect every downstream cache to follow."""
    _load_registry.cache_clear()
    from apps.system.reader import clear_caches as _clear_reader_caches  # noqa: PLC0415

    _clear_reader_caches()


class _SkillRegistryProxy:
    """Tuple-like view over the lazily-loaded Skill registry."""

    def __iter__(self):
        return iter(_load_registry())

    def __len__(self):
        return len(_load_registry())

    def __getitem__(self, index):
        return _load_registry()[index]

    def __contains__(self, item):
        return item in _load_registry()

    def __bool__(self):
        return len(_load_registry()) > 0


SKILL_REGISTRY: _SkillRegistryProxy = _SkillRegistryProxy()


def get_skill(name: str) -> Skill:
    """Return the Skill metadata for a given skill name. Raises KeyError if unknown."""
    for s in _load_registry():
        if s.name == name:
            return s
    raise KeyError(name)


def all_phases() -> list[str]:
    """Ordered list of agent-declared phase names."""
    seen: list[str] = []
    for s in _load_registry():
        if s.phase not in seen:
            seen.append(s.phase)
    return seen


def skills_in_phase(phase: str) -> list[Skill]:
    """Return all skills in a phase, ordered by ordinal."""
    return sorted((s for s in _load_registry() if s.phase == phase), key=lambda s: s.ordinal)


@dataclass(frozen=True)
class ForkPoint:
    """A resolved point in the lifecycle to fork at.

    A fork point is *one concept with two spellings*. Callers name either a
    phase or a skill; both resolve to the same shape, so downstream trim
    logic never branches on which spelling arrived.

    ``phase_ordinal`` is 1-based and matches the ``<N>-`` prefix of a run's
    phase folders. ``skill_ordinal`` is ``None`` for a phase fork (the whole
    phase is re-run) and set for a skill fork (that phase is partially
    kept — artifacts from strictly-earlier skills survive).
    """

    phase: str
    phase_ordinal: int
    skill: str | None = None
    skill_ordinal: int | None = None

    @property
    def is_skill_fork(self) -> bool:
        return self.skill_ordinal is not None

    def label(self) -> str:
        """Human-readable fork point for session titles and messages."""
        return self.skill or self.phase


def resolve_fork_point(*, phase: str | None = None, skill: str | None = None) -> ForkPoint:
    """Resolve a phase name OR a skill name into a :class:`ForkPoint`.

    Exactly one of ``phase`` / ``skill`` must be given. Raises ``KeyError``
    with the offending name when it isn't in the registry; callers translate
    that into their own error envelope.

    A skill fork resolves to its owning phase, so a caller that names the
    FIRST skill of a phase gets a fork functionally equivalent to naming the
    phase itself — with one deliberate difference: no artifact in that phase
    has a lower ordinal, so nothing from it is kept either way.
    """
    if (phase is None) == (skill is None):
        raise ValueError("resolve_fork_point requires exactly one of phase / skill")

    phases = all_phases()

    if phase is not None:
        try:
            return ForkPoint(phase=phase, phase_ordinal=phases.index(phase) + 1)
        except ValueError as exc:
            raise KeyError(phase) from exc

    target = get_skill(skill)  # raises KeyError(skill) when unknown
    return ForkPoint(
        phase=target.phase,
        phase_ordinal=phases.index(target.phase) + 1,
        skill=target.name,
        skill_ordinal=target.ordinal,
    )


def artifact_producers() -> dict[str, str]:
    """Map artifact basename → producing skill name, across all phases.

    Keyed by BASENAME rather than full path because the trim walks Drive
    folders and only sees leaf filenames. Basenames are unique in practice
    (the 0.13.0+ convention is ``<N>-<phase>/<skill>[_<role>].<ext>``); on
    the rare collision, last-writer-wins is acceptable — the fallback in
    ``skill_ordinal_for_artifact`` keeps unknown files rather than dropping
    them, so a wrong answer costs an extra copied file, never a lost one.
    """
    from apps.system.reader import load_system_overview

    plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "") or ""
    overview = load_system_overview(plugin_path)
    out: dict[str, str] = {}
    for art in overview.get("artifacts") or []:
        path = art.get("path") or ""
        producer = art.get("produced_by") or ""
        if path and producer:
            out[path.rsplit("/", 1)[-1]] = producer
    return out


def skill_ordinal_for_artifact(basename: str) -> int | None:
    """Ordinal of the skill that produces ``basename``, or None if unknown.

    None means "not attributable" — callers must KEEP such files. An
    unattributed artifact is far cheaper to copy needlessly than to drop
    from a fork that was supposed to preserve it.
    """
    producer = artifact_producers().get(basename)
    if not producer:
        return None
    try:
        return get_skill(producer).ordinal
    except KeyError:
        return None


# The plugin's documented companion suffixes (skills/README.md § QA vs Eval —
# "every producer skill has either a `-qa` companion skill OR an inline QA
# step", same for `-eval`). A companion is a sibling of its producer, so for
# ordering purposes it takes the producer's ordinal. Checked longest-first so
# a hypothetical `-qa-eval` resolves through `-eval`.
_STEP_COMPANION_SUFFIXES = ("-eval", "-qa")


def skill_ordinal_for_step(step_name: str, phase: str) -> int | None:
    """Ordinal of the skill a ``phases.<phase>.steps.<step_name>`` entry
    belongs to, or None when the registry cannot place it in ``phase``.

    Resolution order:

    1. ``step_name`` IS a registry skill in ``phase`` → its ordinal.
    2. ``step_name`` is ``<producer>-qa`` / ``<producer>-eval`` for a registry
       skill in ``phase`` → the producer's ordinal (the plugin's documented
       companion convention; companions are not Workbench rows so they are
       not in the registry themselves).
    3. Otherwise None.

    A skill that exists in the registry but under a DIFFERENT phase is None
    here on purpose: a step recorded under the wrong phase block is not
    something the forker should reason about.

    Unlike :func:`skill_ordinal_for_artifact`, callers must DROP a step they
    cannot place — see ``opp_forker._skill_fork_phase_block`` for why the
    safe direction flips between files and state.
    """
    candidates = [step_name] + [
        step_name[: -len(sfx)]
        for sfx in _STEP_COMPANION_SUFFIXES
        if step_name.endswith(sfx) and len(step_name) > len(sfx)
    ]
    for name in candidates:
        try:
            skill = get_skill(name)
        except KeyError:
            continue
        if skill.phase == phase:
            return skill.ordinal
    return None


def product_producers(phase: str) -> dict[str, str] | None:  # noqa: ARG001
    """Map top-level ``phases.<phase>.products.<key>`` → producing skill, or
    None when the plugin declares no such attribution for ``phase``.

    Today this is None for EVERY phase, and that is a finding, not a stub.
    The plugin has two candidate sources and neither attributes products:

    * ``lib/artifact-manifest.ts`` — ``producedBy`` attributes FILES (that is
      what :func:`artifact_producers` reads). No product key appears in it.
    * ``lib/phase-products-schema.ts`` — types each phase's ``products``
      block (``SyntheticProducts`` etc.) and names no producer at all.

    Worse, the canonical case cannot be split at the top-level key even in
    principle: ``products.synthetic`` is ONE block written by three parties —
    ``demo-data-setup`` (``.source``, ``.labs_opp_id``, ``.workflows``),
    ``demo-narrative`` (``.narrative``) and the Phase-7 agent (``ddd_*``).

    So a skill fork carries the whole ``products`` block and records that it
    did so unattributed (ace#2341). This function is the seam: when the
    plugin grows a ``producedBy`` per product key, return it here and the
    forker's attributed path (already tested) takes over — nothing else in
    ace-web needs to change.
    """
    return None
