# apps/ingest/cost_aggregator.py
"""Walk a list of CostEvents and produce a structured cost breakdown.

The output JSON shape is documented in
docs/specs/2026-05-03-cost-timing-breakdown-design.md and persisted to
Session.cost_breakdown.

This module is pure: no Django, no IO. Aggregator is unit-testable
against fixture-derived event lists.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apps.ingest.parser import CostEvent
from apps.ingest.pricing import compute_cost

SCHEMA_VERSION = 1


def _registry_lookup(
    phase_index: dict[str, dict], name: str
) -> dict | None:
    """Look up a skill or agent in the phase index, with namespace fallback.

    JSONL transcripts identify skills/agents with the plugin namespace
    prefix (e.g. "ace:idea-to-pdd", "ace:design-review"). The registry indexes
    by the unprefixed name from each agent's frontmatter. Try the literal
    name first, then strip the "<namespace>:" prefix and try again.
    """
    direct = phase_index.get(name)
    if direct is not None:
        return direct
    if ":" in name:
        return phase_index.get(name.split(":", 1)[1])
    return None


def _skill_phase_index() -> dict[str, dict]:
    """Return {skill_name: {phase, phase_display, phase_ordinal}} from the ACE plugin registry.

    Wraps apps.system.reader.get_skill_phase_index with a lazy import and
    exception guard so the aggregator stays pure (no hard Django dependency at
    module load time) and tests can monkeypatch this function in isolation.
    """
    try:
        from apps.system.reader import get_skill_phase_index  # noqa: PLC0415

        return get_skill_phase_index()
    except Exception:
        return {}


def _empty_tokens() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }


def _add_usage(target: dict[str, int], usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    target["input_tokens"] += usage.get("input_tokens", 0) or 0
    target["output_tokens"] += usage.get("output_tokens", 0) or 0
    target["cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0) or 0
    target["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0) or 0


def _wall_time_seconds(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None:
        return 0
    delta = (end - start).total_seconds()
    return max(0, int(round(delta)))


@dataclass
class _OpenSegment:
    skill_name: str
    tool_use_id: str
    containing_msg_uuid: str | None  # uuid of the assistant msg that contained the tool_use block
    start_ts: datetime | None
    last_ts: datetime | None
    tokens: dict[str, int] = field(default_factory=_empty_tokens)
    cost_resolved: float = 0.0
    cost_is_partial: bool = False


def _finalize(seg: _OpenSegment) -> dict[str, Any]:
    return {
        "start_ts": seg.start_ts.isoformat() if seg.start_ts else None,
        "wall_time_seconds": _wall_time_seconds(seg.start_ts, seg.last_ts),
        "tokens": seg.tokens,
        "estimated_cost_usd": round(seg.cost_resolved, 6),
        "cost_is_partial": seg.cost_is_partial,
        "incomplete": False,
    }


def _resolve_segment_for_sidechain(
    event: CostEvent,
    parent_of: dict[str, str | None],
    open_segments: list[_OpenSegment],
) -> _OpenSegment | None:
    """Walk parent_uuid upward; return the open segment whose
    containing_msg_uuid matches an ancestor uuid.

    Each Agent segment records the uuid of the orchestrator assistant turn
    that contained the tool_use block (containing_msg_uuid). Sidechain turns
    inside that agent have parentUuid chains that lead back to that same uuid.
    We walk the chain until we find a match or exhaust it.

    A seen-set bounds the walk against circular uuid references.
    """
    cur = event.parent_uuid
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        for seg in open_segments:
            if seg.containing_msg_uuid == cur:
                return seg
        cur = parent_of.get(cur)
    return None


def aggregate(events: list[CostEvent]) -> dict[str, Any]:
    """Build the breakdown JSON. See module docstring for output shape."""
    phase_index = _skill_phase_index()
    totals_tokens = _empty_tokens()
    totals_cost = 0.0
    totals_cost_partial = False
    totals_first_ts: datetime | None = None
    totals_last_ts: datetime | None = None

    # invocations grouped by (phase_name, skill_name). Phase labeling lands
    # in Task 7; for now everything is "_other" / "_orchestration".
    invocations_by_skill: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    orchestration_tokens = _empty_tokens()
    orchestration_cost = 0.0
    orchestration_cost_partial = False
    orchestration_first_ts: datetime | None = None
    orchestration_last_ts: datetime | None = None

    # Per-phase orchestrator-thinking buckets. An orchestration assistant turn
    # (no enclosing segment, not sidechain) is attributed to the most-recently-
    # dispatched phase if any — i.e., the orchestrator was just doing work
    # "for" Phase X. Before any dispatch fires, current_phase is None and the
    # turn falls into the global _orchestration bucket (genuine setup work).
    current_phase: str | None = None
    phase_orch_tokens: dict[str, dict[str, int]] = defaultdict(_empty_tokens)
    phase_orch_cost: dict[str, float] = defaultdict(float)
    phase_orch_cost_partial: dict[str, bool] = defaultdict(bool)
    phase_orch_first_ts: dict[str, datetime] = {}
    phase_orch_last_ts: dict[str, datetime] = {}

    open_segments: list[_OpenSegment] = []

    # Build ancestry index: every event uuid → its parent_uuid.
    # Used by _resolve_segment_for_sidechain to walk the parentUuid chain.
    parent_of: dict[str, str | None] = {
        e.uuid: e.parent_uuid for e in events if e.uuid
    }

    # Pre-scan: identify which assistant-turn uuids are "dispatch turns" —
    # turns whose only content is a Skill/Agent tool_use block. The parser
    # emits assistant_turn before tool_use for the same uuid, so without
    # this we'd incorrectly route dispatch-turn usage to orchestration before
    # the segment is even open. We store pending usage by uuid and apply it
    # when the tool_use event opens the segment.
    dispatch_turn_uuids: set[str] = {
        e.uuid
        for e in events
        if e.kind == "tool_use" and e.tool_name in ("Skill", "Agent") and e.uuid
    }
    # Pending usage from dispatch assistant_turns: uuid → (usage, cost, model)
    pending_dispatch: dict[str, tuple[dict[str, Any] | None, float | None]] = {}

    for event in events:
        # Track session-level wall time spanning everything.
        if event.timestamp is not None:
            if totals_first_ts is None or event.timestamp < totals_first_ts:
                totals_first_ts = event.timestamp
            if totals_last_ts is None or event.timestamp > totals_last_ts:
                totals_last_ts = event.timestamp

        if event.kind == "tool_use" and event.tool_name in ("Skill", "Agent"):
            skill_name = (
                (event.tool_input or {}).get("skill")
                or (event.tool_input or {}).get("subagent_type")
                or "(unknown)"
            )
            # Update current_phase cursor: the orchestrator is now (and
            # subsequent orchestration turns belong to) the phase this skill
            # maps to. Unknown skills don't update the cursor — they leave it
            # pointing at the previous phase.
            registry_entry = _registry_lookup(phase_index, skill_name)
            if registry_entry is not None:
                current_phase = registry_entry["phase"]
            seg = _OpenSegment(
                skill_name=skill_name,
                tool_use_id=event.tool_use_id or "",
                containing_msg_uuid=event.uuid,  # the orchestrator msg uuid
                start_ts=event.timestamp,
                last_ts=event.timestamp,
            )
            # Apply any pending dispatch-turn usage that belongs to this segment.
            # The assistant_turn for this uuid was seen before the tool_use event,
            # so its usage was deferred rather than attributed to orchestration.
            if event.uuid and event.uuid in pending_dispatch:
                pending_usage, pending_cost = pending_dispatch.pop(event.uuid)
                _add_usage(seg.tokens, pending_usage)
                if pending_cost is None:
                    seg.cost_is_partial = True
                else:
                    seg.cost_resolved += pending_cost
            open_segments.append(seg)
            continue

        if event.kind == "tool_result":
            # Pop the matching segment (LIFO with id match).
            match_idx: int | None = None
            for i in range(len(open_segments) - 1, -1, -1):
                if open_segments[i].tool_use_id == event.matched_tool_use_id:
                    match_idx = i
                    break
            if match_idx is not None:
                seg = open_segments.pop(match_idx)
                if event.timestamp is not None:
                    seg.last_ts = event.timestamp
                registry_entry = _registry_lookup(phase_index, seg.skill_name)
                phase_name = registry_entry["phase"] if registry_entry else "_other"
                invocations_by_skill[(phase_name, seg.skill_name)].append(_finalize(seg))
            continue

        if event.kind == "assistant_turn":
            _add_usage(totals_tokens, event.usage)
            cost = compute_cost(event.model, event.usage)
            if cost is None:
                totals_cost_partial = True
            else:
                totals_cost += cost

            target_seg: _OpenSegment | None = None
            if event.is_sidechain:
                # Sidechain turn: walk parentUuid upward to find the open segment
                # whose containing_msg_uuid matches an ancestor. If none found,
                # the turn falls through to orchestration below.
                target_seg = _resolve_segment_for_sidechain(
                    event, parent_of, open_segments
                )
            elif event.uuid in dispatch_turn_uuids:
                # Dispatch turn: this assistant_turn opens a Skill/Agent segment
                # on the very next event (same uuid). Defer usage to that segment
                # rather than routing to orchestration or the currently-open segment.
                pending_dispatch[event.uuid] = (event.usage, cost)
                continue
            elif open_segments:
                target_seg = open_segments[-1]

            if target_seg is not None:
                _add_usage(target_seg.tokens, event.usage)
                if cost is None:
                    target_seg.cost_is_partial = True
                else:
                    target_seg.cost_resolved += cost
                if event.timestamp is not None:
                    target_seg.last_ts = event.timestamp
            elif current_phase is not None:
                # Orchestration thinking after at least one phase has been
                # entered: attribute to that phase. Surfaces in the phase row
                # as a synthetic "(orchestration)" skill.
                _add_usage(phase_orch_tokens[current_phase], event.usage)
                if cost is None:
                    phase_orch_cost_partial[current_phase] = True
                else:
                    phase_orch_cost[current_phase] += cost
                if event.timestamp is not None:
                    if current_phase not in phase_orch_first_ts:
                        phase_orch_first_ts[current_phase] = event.timestamp
                    phase_orch_last_ts[current_phase] = event.timestamp
            else:
                _add_usage(orchestration_tokens, event.usage)
                if cost is None:
                    orchestration_cost_partial = True
                else:
                    orchestration_cost += cost
                if event.timestamp is not None:
                    if orchestration_first_ts is None:
                        orchestration_first_ts = event.timestamp
                    orchestration_last_ts = event.timestamp
            continue

    # Finalize segments still open at end of stream — interrupted/crashed
    # runs. Flag with incomplete=True so the UI can render "(interrupted)".
    while open_segments:
        seg = open_segments.pop()
        finalized = _finalize(seg)
        finalized["incomplete"] = True
        registry_entry = _registry_lookup(phase_index, seg.skill_name)
        incomplete_phase = registry_entry["phase"] if registry_entry else "_other"
        invocations_by_skill[(incomplete_phase, seg.skill_name)].append(finalized)

    # Build per-skill summaries grouped by phase.
    phase_skills: dict[str, list[dict[str, Any]]] = defaultdict(list)
    phase_tokens: dict[str, dict[str, int]] = defaultdict(_empty_tokens)
    phase_cost: dict[str, float] = defaultdict(float)
    phase_cost_partial: dict[str, bool] = defaultdict(bool)
    phase_wall: dict[str, int] = defaultdict(int)

    for (phase_name, skill_name), invocations in invocations_by_skill.items():
        merged = _empty_tokens()
        cost_sum = 0.0
        cost_partial = False
        wall_sum = 0
        for inv in invocations:
            for k in merged:
                merged[k] += inv["tokens"][k]
            cost_sum += inv["estimated_cost_usd"]
            cost_partial = cost_partial or inv.get("cost_is_partial", False)
            wall_sum += inv["wall_time_seconds"]
        phase_skills[phase_name].append({
            "skill_name": skill_name,
            "invocation_count": len(invocations),
            "wall_time_seconds": wall_sum,
            "estimated_cost_usd": round(cost_sum, 6),
            "cost_is_partial": cost_partial,
            "tokens": merged,
            "invocations": invocations,
        })
        for k in merged:
            phase_tokens[phase_name][k] += merged[k]
        phase_cost[phase_name] += cost_sum
        phase_cost_partial[phase_name] = phase_cost_partial[phase_name] or cost_partial
        phase_wall[phase_name] += wall_sum

    # Inject phase-orchestration as a synthetic skill row in each phase that
    # has any. Surfaces orchestrator thinking ("(orchestration)") alongside
    # the real skills so the phase totals add up to skills + orchestration.
    for phase_name, tokens in phase_orch_tokens.items():
        if not any(tokens.values()):
            continue
        wall = _wall_time_seconds(
            phase_orch_first_ts.get(phase_name),
            phase_orch_last_ts.get(phase_name),
        )
        cost = phase_orch_cost[phase_name]
        partial = phase_orch_cost_partial[phase_name]
        phase_skills[phase_name].append({
            "skill_name": "(orchestration)",
            "invocation_count": 1,
            "wall_time_seconds": wall,
            "estimated_cost_usd": round(cost, 6),
            "cost_is_partial": partial,
            "tokens": dict(tokens),
            "invocations": [],
        })
        for k in tokens:
            phase_tokens[phase_name][k] += tokens[k]
        phase_cost[phase_name] += cost
        phase_cost_partial[phase_name] = phase_cost_partial[phase_name] or partial
        phase_wall[phase_name] += wall

    # Build a phase meta index from the registry for display/ordinal lookups.
    # {phase_name: (phase_display, phase_ordinal)}
    phase_meta_by_name: dict[str, tuple[str, int]] = {}
    for entry in phase_index.values():
        pn = entry["phase"]
        if pn not in phase_meta_by_name:
            phase_meta_by_name[pn] = (entry["phase_display"], entry["phase_ordinal"])

    phases: list[dict[str, Any]] = []
    if any(orchestration_tokens.values()):
        phases.append({
            "phase_name": "_orchestration",
            "phase_display": "Orchestration",
            "phase_ordinal": 0,
            "wall_time_seconds": _wall_time_seconds(orchestration_first_ts, orchestration_last_ts),
            "estimated_cost_usd": round(orchestration_cost, 6),
            "cost_is_partial": orchestration_cost_partial,
            "tokens": orchestration_tokens,
            "skills": [],
        })
    for name, skills in phase_skills.items():
        if name == "_other":
            phase_display = "Other"
            phase_ordinal = 999
        else:
            meta = phase_meta_by_name.get(name)
            phase_display = meta[0] if meta else name
            phase_ordinal = meta[1] if meta else 500
        phases.append({
            "phase_name": name,
            "phase_display": phase_display,
            "phase_ordinal": phase_ordinal,
            "wall_time_seconds": phase_wall[name],
            "estimated_cost_usd": round(phase_cost[name], 6),
            "cost_is_partial": phase_cost_partial[name],
            "tokens": phase_tokens[name],
            "skills": skills,
        })
    phases.sort(key=lambda p: p["phase_ordinal"])

    cache_total = (
        totals_tokens["cache_read_tokens"]
        + totals_tokens["cache_creation_tokens"]
        + totals_tokens["input_tokens"]
    )
    cache_hit_ratio = (
        totals_tokens["cache_read_tokens"] / cache_total
        if cache_total > 0
        else 0.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "computed_at": datetime.now(UTC).isoformat(),
        "totals": {
            "wall_time_seconds": _wall_time_seconds(totals_first_ts, totals_last_ts),
            "input_tokens": totals_tokens["input_tokens"],
            "output_tokens": totals_tokens["output_tokens"],
            "cache_creation_tokens": totals_tokens["cache_creation_tokens"],
            "cache_read_tokens": totals_tokens["cache_read_tokens"],
            "estimated_cost_usd": round(totals_cost, 6),
            "cost_is_partial": totals_cost_partial,
            "cache_hit_ratio": round(cache_hit_ratio, 4),
        },
        "phases": phases,
    }
