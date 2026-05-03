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
from datetime import datetime, timezone
from typing import Any

from apps.ingest.parser import CostEvent
from apps.ingest.pricing import compute_cost

SCHEMA_VERSION = 1


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
    }


def aggregate(events: list[CostEvent]) -> dict[str, Any]:
    """Build the breakdown JSON. See module docstring for output shape."""
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

    open_segments: list[_OpenSegment] = []

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
            open_segments.append(_OpenSegment(
                skill_name=skill_name,
                tool_use_id=event.tool_use_id or "",
                start_ts=event.timestamp,
                last_ts=event.timestamp,
            ))
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
                phase_name = "_other"
                invocations_by_skill[(phase_name, seg.skill_name)].append(_finalize(seg))
            continue

        if event.kind == "assistant_turn":
            _add_usage(totals_tokens, event.usage)
            cost = compute_cost(event.model, event.usage)
            if cost is None:
                totals_cost_partial = True
            else:
                totals_cost += cost
            # Attribute to the innermost open segment, or to orchestration
            # if no segment is open. Sidechain attribution lands in Task 5.
            if open_segments and not event.is_sidechain:
                seg = open_segments[-1]
                _add_usage(seg.tokens, event.usage)
                if cost is None:
                    seg.cost_is_partial = True
                else:
                    seg.cost_resolved += cost
                if event.timestamp is not None:
                    seg.last_ts = event.timestamp
            elif not event.is_sidechain:
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
        phases.append({
            "phase_name": name,
            "phase_display": "Other" if name == "_other" else name,
            "phase_ordinal": 999 if name == "_other" else 500,
            "wall_time_seconds": phase_wall[name],
            "estimated_cost_usd": round(phase_cost[name], 6),
            "cost_is_partial": phase_cost_partial[name],
            "tokens": phase_tokens[name],
            "skills": skills,
        })
    phases.sort(key=lambda p: p["phase_ordinal"])

    cache_total = totals_tokens["cache_read_tokens"] + totals_tokens["cache_creation_tokens"] + totals_tokens["input_tokens"]
    cache_hit_ratio = (
        totals_tokens["cache_read_tokens"] / cache_total
        if cache_total > 0
        else 0.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
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
