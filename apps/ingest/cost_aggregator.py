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

from apps.ingest._common import (
    add_usage,
    empty_tokens,
    registry_lookup,
    skill_phase_index,
    union_seconds,
    wall_time_seconds,
)
from apps.ingest.parser import CostEvent
from apps.ingest.pricing import compute_cost

SCHEMA_VERSION = 1


@dataclass
class _OpenSegment:
    skill_name: str
    tool_use_id: str
    containing_msg_uuid: str | None  # uuid of the assistant msg that contained the tool_use block
    start_ts: datetime | None
    last_ts: datetime | None
    tokens: dict[str, int] = field(default_factory=empty_tokens)
    cost_resolved: float = 0.0
    cost_is_partial: bool = False


def _finalize(seg: _OpenSegment) -> dict[str, Any]:
    return {
        "start_ts": seg.start_ts.isoformat() if seg.start_ts else None,
        "wall_time_seconds": wall_time_seconds(seg.start_ts, seg.last_ts),
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
    phase_index = skill_phase_index()
    totals_tokens = empty_tokens()
    totals_cost = 0.0
    totals_cost_partial = False
    totals_first_ts: datetime | None = None
    totals_last_ts: datetime | None = None

    # invocations grouped by (phase_name, skill_name). Phase labeling lands
    # in Task 7; for now everything is "_other" / "_orchestration".
    invocations_by_skill: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    orchestration_tokens = empty_tokens()
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
    phase_orch_tokens: dict[str, dict[str, int]] = defaultdict(empty_tokens)
    phase_orch_cost: dict[str, float] = defaultdict(float)
    phase_orch_cost_partial: dict[str, bool] = defaultdict(bool)
    phase_orch_first_ts: dict[str, datetime] = {}
    phase_orch_last_ts: dict[str, datetime] = {}

    open_segments: list[_OpenSegment] = []

    # Per (phase, skill) list of (start_ts, last_ts) datetime intervals.
    # Wall time is rolled up as the UNION of these intervals, not the sum of
    # their spans — summing double-counts wall-clock windows covered by both a
    # skill segment and the orchestration span that brackets it.
    intervals_by_skill: dict[tuple[str, str], list[tuple]] = defaultdict(list)

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
            registry_entry = registry_lookup(phase_index, skill_name)
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
                add_usage(seg.tokens, pending_usage)
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
                registry_entry = registry_lookup(phase_index, seg.skill_name)
                if registry_entry is not None:
                    phase_name = registry_entry["phase"]
                elif current_phase is not None:
                    # Unknown skill (e.g. nova:autobuild) inside a known phase:
                    # attribute to current_phase. The orchestrator was doing
                    # phase-X work and delegated to a non-ACE plugin tool —
                    # that tool's spend belongs to phase X, not "Other".
                    phase_name = current_phase
                else:
                    phase_name = "_other"
                invocations_by_skill[(phase_name, seg.skill_name)].append(_finalize(seg))
                intervals_by_skill[(phase_name, seg.skill_name)].append((seg.start_ts, seg.last_ts))
            continue

        if event.kind == "assistant_turn":
            add_usage(totals_tokens, event.usage)
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
                add_usage(target_seg.tokens, event.usage)
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
                add_usage(phase_orch_tokens[current_phase], event.usage)
                if cost is None:
                    phase_orch_cost_partial[current_phase] = True
                else:
                    phase_orch_cost[current_phase] += cost
                if event.timestamp is not None:
                    if current_phase not in phase_orch_first_ts:
                        phase_orch_first_ts[current_phase] = event.timestamp
                    phase_orch_last_ts[current_phase] = event.timestamp
            else:
                add_usage(orchestration_tokens, event.usage)
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
        registry_entry = registry_lookup(phase_index, seg.skill_name)
        if registry_entry is not None:
            incomplete_phase = registry_entry["phase"]
        elif current_phase is not None:
            incomplete_phase = current_phase
        else:
            incomplete_phase = "_other"
        invocations_by_skill[(incomplete_phase, seg.skill_name)].append(finalized)
        intervals_by_skill[(incomplete_phase, seg.skill_name)].append((seg.start_ts, seg.last_ts))

    # Build per-skill summaries grouped by phase.
    phase_skills: dict[str, list[dict[str, Any]]] = defaultdict(list)
    phase_tokens: dict[str, dict[str, int]] = defaultdict(empty_tokens)
    phase_cost: dict[str, float] = defaultdict(float)
    phase_cost_partial: dict[str, bool] = defaultdict(bool)
    phase_wall: dict[str, int] = defaultdict(int)

    # All skill-segment intervals per phase, for the union-based phase wall and
    # the residual orchestration wall (phase wall minus the skill-covered union).
    phase_skill_intervals: dict[str, list[tuple]] = defaultdict(list)
    for (phase_name, _skill_name), ivs in intervals_by_skill.items():
        phase_skill_intervals[phase_name].extend(ivs)

    # Phases that get a synthetic "(orchestration)" row: those with orchestration
    # token usage. The same set decides whether the orchestration span counts
    # toward the phase wall, keeping phase wall == sum of its skill rows.
    orch_phases = {p for p, tk in phase_orch_tokens.items() if any(tk.values())}

    def _phase_intervals(name: str) -> list[tuple]:
        ivs = list(phase_skill_intervals.get(name, []))
        if name in orch_phases:
            ivs.append((phase_orch_first_ts.get(name), phase_orch_last_ts.get(name)))
        return ivs

    for (phase_name, skill_name), invocations in invocations_by_skill.items():
        merged = empty_tokens()
        cost_sum = 0.0
        cost_partial = False
        for inv in invocations:
            for k in merged:
                merged[k] += inv["tokens"][k]
            cost_sum += inv["estimated_cost_usd"]
            cost_partial = cost_partial or inv.get("cost_is_partial", False)
        # Wall = union of this skill's invocation intervals. Summing raw spans
        # would double-count any overlap between retried/nested segments.
        wall_sum = union_seconds(intervals_by_skill[(phase_name, skill_name)])
        # Canonical display name from the registry — same label the System
        # tab uses (e.g. "Idea to PDD" instead of the raw "ace:idea-to-pdd").
        # Falls back to the raw name for unknown / non-ACE skills.
        registry_entry = registry_lookup(phase_index, skill_name)
        skill_display = skill_name
        if registry_entry and registry_entry.get("skill_display"):
            skill_display = registry_entry["skill_display"]
        phase_skills[phase_name].append({
            "skill_name": skill_name,
            "skill_display": skill_display,
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

    # Inject phase-orchestration as a synthetic skill row in each phase that
    # has any. The orchestration wall is the RESIDUAL — the phase's union wall
    # minus the wall already covered by skill segments — so the phase total
    # equals skills + orchestration with no double-counting.
    for phase_name in orch_phases:
        tokens = phase_orch_tokens[phase_name]
        phase_union = union_seconds(_phase_intervals(phase_name))
        skills_union = union_seconds(phase_skill_intervals.get(phase_name, []))
        wall = max(0, phase_union - skills_union)
        cost = phase_orch_cost[phase_name]
        partial = phase_orch_cost_partial[phase_name]
        phase_skills[phase_name].append({
            "skill_name": "(orchestration)",
            "skill_display": "(orchestration)",
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

    # Phase wall = union of all its skill segments + the orchestration span.
    for phase_name in set(phase_skills) | set(phase_skill_intervals) | orch_phases:
        phase_wall[phase_name] = union_seconds(_phase_intervals(phase_name))

    # Global _orchestration wall is a RESIDUAL too: the global orchestration
    # span minus any skill-segment wall that falls inside it. Skills dispatched
    # before the first phase is entered (current_phase still None → "_other")
    # run *within* the global orchestration span; counting both double-counts
    # that window. Subtract the skill union from the span.
    all_skill_intervals = [iv for ivs in intervals_by_skill.values() for iv in ivs]
    global_orch_span = (orchestration_first_ts, orchestration_last_ts)
    global_orch_wall = max(
        0,
        union_seconds([global_orch_span, *all_skill_intervals])
        - union_seconds(all_skill_intervals),
    )

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
            "wall_time_seconds": global_orch_wall,
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
            "wall_time_seconds": wall_time_seconds(totals_first_ts, totals_last_ts),
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
