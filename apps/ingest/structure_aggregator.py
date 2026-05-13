"""Walk a CostEvent stream and emit a hierarchical structure tree.

Output shape: documented at the top of
docs/plans/2026-05-10-session-structure-view.md.

Pure: no Django, no IO. Tested against fixture-derived event lists.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apps.ingest._common import (
    add_usage,
    empty_tokens,
    registry_lookup,
    skill_phase_index,
    wall_time_seconds,
)
from apps.ingest.parser import CostEvent
from apps.ingest.pricing import compute_cost

SCHEMA_VERSION = 1


def _tool_label(tool_name: str, tool_input: dict | None) -> str:
    """Short human-readable label for a tool call. Used as the row's title."""
    if not tool_input:
        return ""
    if tool_name == "Bash":
        return str(tool_input.get("command", ""))[:80]
    if tool_name in ("Read", "Edit", "Write"):
        return str(tool_input.get("file_path", ""))[:80]
    if tool_name == "Grep":
        return str(tool_input.get("pattern", ""))[:80]
    if tool_name == "Glob":
        return str(tool_input.get("pattern", ""))[:80]
    if tool_name == "WebFetch":
        return str(tool_input.get("url", ""))[:80]
    # Generic fallback: first string-typed value in the input dict
    for v in tool_input.values():
        if isinstance(v, str):
            return v[:80]
    return ""


def _find_tool_node(nodes: list[dict], tool_use_id: str | None) -> dict | None:
    """Search the tail of a children list for a tool node with the given id."""
    if not tool_use_id:
        return None
    for node in reversed(nodes):
        if node["kind"] == "tool" and node.get("tool_use_id") == tool_use_id:
            return node
        if node["kind"] == "parallel_group":
            for child in reversed(node["children"]):
                if child.get("tool_use_id") == tool_use_id:
                    return child
    return None


def _iter_descendants(nodes: Iterable[dict]) -> Iterable[dict]:
    """Yield every descendant node (used for status propagation).

    Uniformly recursive across all wrapper kinds so adding new container
    kinds in the future doesn't silently break error propagation.
    """
    for node in nodes:
        yield node
        children = node.get("children")
        if children:
            yield from _iter_descendants(children)


@dataclass
class _Frame:
    """An in-flight Skill/Agent dispatch. Closed by its matching tool_result."""
    tool_use_id: str
    skill_name: str
    skill_display: str
    is_subagent: bool
    containing_msg_uuid: str | None
    phase_name: str
    start_ts: datetime | None
    last_ts: datetime | None
    tokens: dict[str, int] = field(default_factory=empty_tokens)
    cost: float = 0.0
    cost_partial: bool = False
    children: list[dict] = field(default_factory=list)
    last_turn_uuid: str | None = None  # for parallel-group detection
    last_parallel_group: dict | None = None
    status: str = "ok"


def aggregate(events: list[CostEvent]) -> dict[str, Any]:
    """Build the structure tree. See module docstring for output shape."""
    phase_index = skill_phase_index()

    session_first_ts: datetime | None = None
    session_last_ts: datetime | None = None
    session_tokens = empty_tokens()
    session_cost = 0.0
    session_cost_partial = False

    open_frames: list[_Frame] = []
    phase_buckets: dict[str, dict[str, Any]] = {}
    current_phase: str | None = None

    # The parser emits `assistant_turn` *before* the `tool_use` event for the
    # same JSONL line. So when an orchestrator turn that exists only to
    # dispatch a Skill/Agent fires its assistant_turn, the frame it's
    # dispatching hasn't been opened yet — its usage would land in the
    # session-totals-only bucket and disappear from phase rollups. Pre-scan
    # to find those uuids and defer their usage onto the segment that opens
    # on the matching tool_use. Mirrors cost_aggregator's behavior.
    dispatch_turn_uuids: set[str] = {
        e.uuid for e in events
        if e.kind == "tool_use" and e.tool_name in ("Skill", "Agent") and e.uuid
    }
    pending_dispatch: dict[str, tuple[dict[str, Any] | None, float | None]] = {}

    # Per-phase orchestrator-thinking accumulators. Top-level assistant turns
    # (no open Skill/Agent frame, not themselves a dispatch turn) belong to
    # the most recently entered phase if any — that's the orchestrator
    # planning/thinking *for* that phase. Before any dispatch, they fall into
    # the global Orchestration bucket. Surfaces as a synthetic "(orchestration)"
    # skill row inside each phase at rollup time so totals reconcile with
    # session cost. Matches cost_aggregator's behavior.
    phase_orch_cost: dict[str, float] = {}
    phase_orch_partial: dict[str, bool] = {}
    phase_orch_tokens: dict[str, dict[str, int]] = {}
    phase_orch_first_ts: dict[str, datetime] = {}
    phase_orch_last_ts: dict[str, datetime] = {}

    def _ensure_phase(name: str) -> dict[str, Any]:
        if name not in phase_buckets:
            if name == "_orchestration":
                meta_display, ordinal = "Orchestration", 0
            elif name == "_other":
                meta_display, ordinal = "Other", 999
            else:
                meta_display = name
                ordinal = 500
                for entry in phase_index.values():
                    if entry["phase"] == name:
                        meta_display = entry["phase_display"]
                        ordinal = entry["phase_ordinal"]
                        break
            phase_buckets[name] = {
                "kind": "phase",
                "name": name,
                "display": meta_display,
                "ordinal": ordinal,
                "wall_time_seconds": 0,
                "estimated_cost_usd": 0.0,
                "cost_is_partial": False,
                "tokens": empty_tokens(),
                "status": "ok",
                "children": [],
                "_last_turn_uuid": None,
                "_last_parallel_group": None,
            }
        return phase_buckets[name]

    def _attach(node: dict, *, frame: _Frame | None, phase_name: str | None,
                turn_uuid: str | None) -> None:
        """Append node to (frame.children) or (phase_buckets[phase_name]['children']).

        If the previous attached node shares `turn_uuid` AND the new node is a
        tool, cluster them into a parallel_group.
        """
        if frame is not None:
            target_children = frame.children
            last_turn = frame.last_turn_uuid
            last_group = frame.last_parallel_group
        elif phase_name is not None:
            bucket = _ensure_phase(phase_name)
            target_children = bucket["children"]
            last_turn = bucket["_last_turn_uuid"]
            last_group = bucket["_last_parallel_group"]
        else:
            return

        if node["kind"] == "tool" and turn_uuid and last_turn == turn_uuid:
            # Same assistant turn → parallel cluster.
            if last_group is not None:
                last_group["children"].append(node)
                last_group["wall_time_seconds"] = max(
                    last_group["wall_time_seconds"], node.get("wall_time_seconds", 0)
                )
                return
            # Wrap previous tool + this one in a new parallel_group.
            if target_children and target_children[-1]["kind"] == "tool":
                prev = target_children.pop()
                group = {
                    "kind": "parallel_group",
                    "started_at": prev.get("started_at"),
                    "wall_time_seconds": max(
                        prev.get("wall_time_seconds", 0),
                        node.get("wall_time_seconds", 0),
                    ),
                    "children": [prev, node],
                }
                target_children.append(group)
                if frame is not None:
                    frame.last_parallel_group = group
                else:
                    phase_buckets[phase_name]["_last_parallel_group"] = group
                return

        target_children.append(node)
        if frame is not None:
            frame.last_turn_uuid = turn_uuid
            frame.last_parallel_group = None
        else:
            phase_buckets[phase_name]["_last_turn_uuid"] = turn_uuid
            phase_buckets[phase_name]["_last_parallel_group"] = None

    for event in events:
        if event.timestamp is not None:
            if session_first_ts is None or event.timestamp < session_first_ts:
                session_first_ts = event.timestamp
            if session_last_ts is None or event.timestamp > session_last_ts:
                session_last_ts = event.timestamp

        if event.kind == "assistant_turn":
            add_usage(session_tokens, event.usage)
            cost = compute_cost(event.model, event.usage)
            if cost is None:
                session_cost_partial = True
            else:
                session_cost += cost
            # Attribute usage to the innermost open frame, if any.
            if open_frames:
                add_usage(open_frames[-1].tokens, event.usage)
                if cost is None:
                    open_frames[-1].cost_partial = True
                else:
                    open_frames[-1].cost += cost
                if event.timestamp is not None:
                    open_frames[-1].last_ts = event.timestamp
            elif event.uuid in dispatch_turn_uuids:
                # Top-level dispatch turn: hold the usage until the segment
                # opens on the matching tool_use event below.
                pending_dispatch[event.uuid] = (event.usage, cost)
            else:
                # Top-level orchestrator thinking (no Skill/Agent in flight,
                # not a dispatch turn — e.g. assistant reply that precedes a
                # Bash/Read tool call, or pure thinking between dispatches).
                # Attribute to the current phase if one has been entered,
                # else to the global Orchestration bucket. Without this the
                # cost is lost from every phase rollup.
                bucket_key = current_phase or "_orchestration"
                add_usage(phase_orch_tokens.setdefault(bucket_key, empty_tokens()),
                          event.usage)
                if cost is None:
                    phase_orch_partial[bucket_key] = True
                else:
                    phase_orch_cost[bucket_key] = (
                        phase_orch_cost.get(bucket_key, 0.0) + cost
                    )
                if event.timestamp is not None:
                    if bucket_key not in phase_orch_first_ts:
                        phase_orch_first_ts[bucket_key] = event.timestamp
                    phase_orch_last_ts[bucket_key] = event.timestamp
            continue

        if event.kind == "tool_use":
            tool_name = event.tool_name or ""
            is_skill = tool_name in ("Skill", "Agent")

            if is_skill:
                skill_name = (
                    (event.tool_input or {}).get("skill")
                    or (event.tool_input or {}).get("subagent_type")
                    or "(unknown)"
                )
                entry = registry_lookup(phase_index, skill_name)
                if entry is not None:
                    phase_name = entry["phase"]
                    skill_display = entry.get("skill_display", skill_name)
                    if not open_frames:
                        # Top-level dispatch updates the orchestrator phase cursor
                        current_phase = phase_name
                elif open_frames:
                    phase_name = open_frames[-1].phase_name
                    skill_display = skill_name
                elif current_phase is not None:
                    phase_name = current_phase
                    skill_display = skill_name
                else:
                    phase_name = "_other"
                    skill_display = skill_name

                frame = _Frame(
                    tool_use_id=event.tool_use_id or "",
                    skill_name=skill_name,
                    skill_display=skill_display,
                    is_subagent=bool(open_frames),
                    containing_msg_uuid=event.uuid,
                    phase_name=phase_name,
                    start_ts=event.timestamp,
                    last_ts=event.timestamp,
                )
                # Drain any deferred dispatch-turn usage into the new frame so
                # the orchestrator's planning turn counts against this skill.
                if event.uuid and event.uuid in pending_dispatch:
                    pending_usage, pending_cost = pending_dispatch.pop(event.uuid)
                    add_usage(frame.tokens, pending_usage)
                    if pending_cost is None:
                        frame.cost_partial = True
                    else:
                        frame.cost += pending_cost
                open_frames.append(frame)
                continue

            # Regular tool call (Bash, Read, Edit, etc.)
            tool_node = {
                "kind": "tool",
                "tool_use_id": event.tool_use_id or "",
                "tool_name": tool_name,
                "label": _tool_label(tool_name, event.tool_input),
                "started_at": event.timestamp.isoformat() if event.timestamp else None,
                "wall_time_seconds": 0,
                "status": "ok",
                "content_preview": None,  # filled in by the matching tool_result
            }
            if open_frames:
                _attach(tool_node, frame=open_frames[-1], phase_name=None, turn_uuid=event.uuid)
            elif current_phase is not None:
                _attach(tool_node, frame=None, phase_name=current_phase, turn_uuid=event.uuid)
            else:
                _attach(tool_node, frame=None, phase_name="_orchestration", turn_uuid=event.uuid)
            continue

        if event.kind == "tool_result":
            # Try to close a Skill/Agent frame first (LIFO id match).
            match_idx: int | None = None
            for i in range(len(open_frames) - 1, -1, -1):
                if open_frames[i].tool_use_id == event.matched_tool_use_id:
                    match_idx = i
                    break
            if match_idx is not None:
                frame = open_frames.pop(match_idx)
                if event.timestamp is not None:
                    frame.last_ts = event.timestamp
                if event.is_error:
                    frame.status = "error"
                # Promote child errors up
                for desc in _iter_descendants(frame.children):
                    if desc.get("status") == "error":
                        frame.status = "error"
                        break
                skill_node = {
                    "kind": "skill",
                    "name": frame.skill_name,
                    "display": frame.skill_display,
                    "is_subagent": frame.is_subagent,
                    "started_at": frame.start_ts.isoformat() if frame.start_ts else None,
                    "wall_time_seconds": wall_time_seconds(frame.start_ts, frame.last_ts),
                    "estimated_cost_usd": round(frame.cost, 6),
                    "cost_is_partial": frame.cost_partial,
                    "tokens": frame.tokens,
                    "status": frame.status,
                    "children": frame.children,
                }
                if open_frames:
                    _propagate_to_parent(frame, open_frames[-1])
                    _attach(skill_node, frame=open_frames[-1], phase_name=None, turn_uuid=None)
                else:
                    _attach(skill_node, frame=None, phase_name=frame.phase_name, turn_uuid=None)
                continue

            # Regular tool result — find the open tool node and update it.
            if open_frames:
                target_children = open_frames[-1].children
            else:
                phase_for_lookup = current_phase or "_orchestration"
                target_children = _ensure_phase(phase_for_lookup)["children"]
            tool_node = _find_tool_node(target_children, event.matched_tool_use_id)
            if tool_node is not None:
                if event.timestamp is not None and tool_node.get("started_at"):
                    start = datetime.fromisoformat(tool_node["started_at"])
                    tool_node["wall_time_seconds"] = wall_time_seconds(start, event.timestamp)
                if event.is_error:
                    tool_node["status"] = "error"
                if event.content_preview is not None:
                    tool_node["content_preview"] = event.content_preview
            continue

    # Close any open frames as incomplete
    while open_frames:
        frame = open_frames.pop()
        skill_node = {
            "kind": "skill",
            "name": frame.skill_name,
            "display": frame.skill_display,
            "is_subagent": frame.is_subagent,
            "started_at": frame.start_ts.isoformat() if frame.start_ts else None,
            "wall_time_seconds": wall_time_seconds(frame.start_ts, frame.last_ts),
            "estimated_cost_usd": round(frame.cost, 6),
            "cost_is_partial": frame.cost_partial,
            "tokens": frame.tokens,
            "status": "incomplete",
            "children": frame.children,
        }
        if open_frames:
            _propagate_to_parent(frame, open_frames[-1])
            _attach(skill_node, frame=open_frames[-1], phase_name=None, turn_uuid=None)
        else:
            _attach(skill_node, frame=None, phase_name=frame.phase_name, turn_uuid=None)

    # Inject orchestrator-thinking as a synthetic "(orchestration)" skill row
    # in each phase that has any. The cost lives in `phase_orch_*` because it
    # came from top-level assistant turns with no enclosing frame — without a
    # synthetic row to carry it, the phase rollup would lose this spend even
    # though wall-time and tool nodes are correctly bucketed under the phase.
    for bucket_key, tokens in phase_orch_tokens.items():
        if not any(tokens.values()):
            continue
        bucket = _ensure_phase(bucket_key)
        synthetic_skill = {
            "kind": "skill",
            "name": "(orchestration)",
            "display": "(orchestration)",
            "is_subagent": False,
            "started_at": (
                phase_orch_first_ts[bucket_key].isoformat()
                if bucket_key in phase_orch_first_ts else None
            ),
            "wall_time_seconds": wall_time_seconds(
                phase_orch_first_ts.get(bucket_key),
                phase_orch_last_ts.get(bucket_key),
            ),
            "estimated_cost_usd": round(phase_orch_cost.get(bucket_key, 0.0), 6),
            "cost_is_partial": phase_orch_partial.get(bucket_key, False),
            "tokens": tokens,
            "status": "ok",
            "children": [],
        }
        bucket["children"].append(synthetic_skill)

    # Roll phase totals from children
    for bucket in phase_buckets.values():
        _roll_phase_totals(bucket)

    # Strip private tracking keys, sort phases by ordinal
    phases = []
    for bucket in sorted(phase_buckets.values(), key=lambda b: b["ordinal"]):
        bucket.pop("_last_turn_uuid", None)
        bucket.pop("_last_parallel_group", None)
        phases.append(bucket)

    session_status = "ok"
    if any(p["status"] == "error" for p in phases):
        session_status = "error"
    elif any(p["status"] == "incomplete" for p in phases):
        session_status = "incomplete"

    return {
        "schema_version": SCHEMA_VERSION,
        "computed_at": datetime.now(UTC).isoformat(),
        "session": {
            "wall_time_seconds": wall_time_seconds(session_first_ts, session_last_ts),
            "estimated_cost_usd": round(session_cost, 6),
            "cost_is_partial": session_cost_partial,
            "tokens": session_tokens,
            "status": session_status,
        },
        "phases": phases,
    }


def _propagate_to_parent(child: _Frame, parent: _Frame) -> None:
    """Roll a closing child frame's cost/tokens up to its parent.

    Without this, a top-level skill that dispatches all its work to subagents
    reports estimated_cost_usd≈0 — the cost lives only in the deepest frame.
    Wall time is already inclusive because we span start_ts → close_ts; we
    do the same for cost/tokens so a collapsed skill row shows what that
    subtree actually spent (and the phase rollup sums to the session total).
    """
    parent.cost += child.cost
    if child.cost_partial:
        parent.cost_partial = True
    for k in parent.tokens:
        parent.tokens[k] += child.tokens.get(k, 0)


def _roll_phase_totals(bucket: dict) -> None:
    """Sum wall/cost/tokens from a phase's direct children."""
    wall = 0
    cost = 0.0
    cost_partial = False
    tokens = empty_tokens()
    status = "ok"
    for child in bucket["children"]:
        if child["kind"] == "skill":
            wall += child.get("wall_time_seconds", 0)
            cost += child.get("estimated_cost_usd", 0.0)
            cost_partial = cost_partial or child.get("cost_is_partial", False)
            for k in tokens:
                tokens[k] += child.get("tokens", {}).get(k, 0)
            if child.get("status") == "error":
                status = "error"
            elif child.get("status") == "incomplete" and status != "error":
                status = "incomplete"
        elif child["kind"] == "parallel_group":
            wall += child.get("wall_time_seconds", 0)
            for sub in child["children"]:
                if sub.get("status") == "error":
                    status = "error"
        elif child["kind"] == "tool":
            wall += child.get("wall_time_seconds", 0)
            if child.get("status") == "error":
                status = "error"
    bucket["wall_time_seconds"] = wall
    bucket["estimated_cost_usd"] = round(cost, 6)
    bucket["cost_is_partial"] = cost_partial
    bucket["tokens"] = tokens
    bucket["status"] = status
