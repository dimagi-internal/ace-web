"""Walk a CostEvent stream and emit a hierarchical structure tree.

Output shape: documented at the top of
docs/plans/2026-05-10-session-structure-view.md.

Pure: no Django, no IO. Tested against fixture-derived event lists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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

SCHEMA_VERSION = 6

# Subjects like "Phase 3: commcare-setup (Nova builds)" — capture the skill slug.
_PHASE_SUBJECT_RE = re.compile(r"^Phase \d+:\s*([a-z][a-z0-9-]+)")


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

    # Pre-scan TaskCreate events to build task_id -> phase_name. The ACE
    # orchestrator publishes a `Phase N: <skill>...` task list up front, then
    # marks each one in_progress via TaskUpdate as it advances. This is the
    # *only* phase-boundary signal for phases dispatched inline (subagents
    # can't nest, so commcare-setup et al. run from the orchestrator without
    # a Skill tool call). TaskCreate returns sequential task_ids 1..N in
    # transcript order, so we count instead of trying to parse a return value.
    task_phase_map: dict[str, str] = {}
    task_counter = 0
    # Pre-scan turn cost + tool count so we can attribute a top-level tool
    # row's display cost to its parent assistant turn. Without this, every
    # tool reads "$0.00" because cost lives on the assistant_turn event, not
    # the tool_use event. Visual aid only — not used in phase rollups, so
    # there's no double-count risk.
    turn_cost: dict[str, tuple[float | None, int]] = {}
    for e in events:
        if e.kind == "assistant_turn" and e.uuid:
            c = compute_cost(e.model, e.usage)
            turn_cost[e.uuid] = (c, 0)
        elif e.kind == "tool_use" and e.uuid and e.uuid in turn_cost:
            c, n = turn_cost[e.uuid]
            turn_cost[e.uuid] = (c, n + 1)
        if e.kind != "tool_use" or e.tool_name != "TaskCreate":
            continue
        task_counter += 1
        subject = (e.tool_input or {}).get("subject", "")
        m = _PHASE_SUBJECT_RE.match(subject)
        if not m:
            continue
        entry = registry_lookup(phase_index, m.group(1))
        if entry is not None:
            task_phase_map[str(task_counter)] = entry["phase"]

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
    # Per-turn rows for the "(direct turns)" synthetic skill, so the user can
    # drill into orchestrator spend instead of staring at a single rolled-up
    # cost. Order matters — preserved in emit.
    phase_orch_turns: dict[str, list[dict[str, Any]]] = {}

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
                turn_uuid: str | None, target_dict: dict | None = None) -> None:
        """Append node to a frame, a phase bucket, or a target dict (used for
        pending_top_skill — the "currently active" top-level skill that
        absorbs follow-on inline work until the next dispatch fires).

        If the previous attached node shares `turn_uuid` AND the new node is a
        tool, cluster them into a parallel_group.
        """
        if frame is not None:
            target_children = frame.children
            last_turn = frame.last_turn_uuid
            last_group = frame.last_parallel_group
        elif target_dict is not None:
            target_children = target_dict["children"]
            last_turn = target_dict.get("_last_turn_uuid")
            last_group = target_dict.get("_last_parallel_group")
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
                elif target_dict is not None:
                    target_dict["_last_parallel_group"] = group
                else:
                    phase_buckets[phase_name]["_last_parallel_group"] = group
                return

        target_children.append(node)
        if frame is not None:
            frame.last_turn_uuid = turn_uuid
            frame.last_parallel_group = None
        elif target_dict is not None:
            target_dict["_last_turn_uuid"] = turn_uuid
            target_dict["_last_parallel_group"] = None
        else:
            phase_buckets[phase_name]["_last_turn_uuid"] = turn_uuid
            phase_buckets[phase_name]["_last_parallel_group"] = None

    # The "currently active" top-level skill. When a top-level Skill/Agent
    # dispatch closes, we don't attach it to the phase right away — instead
    # we stage it here so subsequent inline assistant turns and tool calls
    # (orchestrator follow-on work) get absorbed into the skill that caused
    # them. The pending slot flushes to the phase on: next top-level
    # dispatch, phase boundary, or end of stream. Mental model: "skill X
    # stays active until skill Y dispatches."
    pending_top_skill: dict | None = None

    def _flush_pending() -> None:
        nonlocal pending_top_skill
        if pending_top_skill is None:
            return
        skill_node = pending_top_skill
        pending_top_skill = None
        phase = skill_node.pop("_phase_name", None) or "_orchestration"
        # Final wall_time = start → last activity (assistant_turn / tool_use /
        # tool_result timestamp), reflecting the full regime, not just the
        # original frame's open→close.
        start_iso = skill_node.get("started_at")
        last_iso = skill_node.pop("_last_ts", None)
        if start_iso and last_iso:
            try:
                skill_node["wall_time_seconds"] = wall_time_seconds(
                    datetime.fromisoformat(start_iso),
                    datetime.fromisoformat(last_iso),
                )
            except ValueError:
                pass
        skill_node.pop("_last_turn_uuid", None)
        skill_node.pop("_last_parallel_group", None)
        _ensure_phase(phase)["children"].append(skill_node)

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
            elif pending_top_skill is not None:
                # A top-level skill is currently "active" — its dispatch has
                # closed but no new dispatch (and no phase boundary) has
                # happened yet. Subsequent orchestrator narration / loose
                # tool calls are follow-on work for that skill, so absorb
                # the cost into its skill row and (for narration turns)
                # append a direct_turn child so the user can see what was
                # being said.
                add_usage(pending_top_skill["tokens"], event.usage)
                if cost is None:
                    pending_top_skill["cost_is_partial"] = True
                else:
                    pending_top_skill["estimated_cost_usd"] = round(
                        pending_top_skill["estimated_cost_usd"] + cost, 6
                    )
                if event.timestamp is not None:
                    pending_top_skill["_last_ts"] = event.timestamp.isoformat()
                if event.text_preview:
                    turn_tokens = empty_tokens()
                    add_usage(turn_tokens, event.usage)
                    pending_top_skill["children"].append({
                        "kind": "direct_turn",
                        "started_at": (
                            event.timestamp.isoformat() if event.timestamp else None
                        ),
                        "model": event.model,
                        "estimated_cost_usd": (
                            round(cost, 6) if cost is not None else 0.0
                        ),
                        "cost_is_partial": cost is None,
                        "tokens": turn_tokens,
                        "text_preview": event.text_preview,
                    })
            else:
                # No skill has dispatched yet in this phase (or we're pre-
                # phase). This work has no skill to attribute to — it goes
                # into the residual "Inline work" bucket. Typically small:
                # the TaskUpdate marker turn that opens the phase, plus
                # whatever narration precedes the first dispatch.
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
                if event.text_preview:
                    turn_tokens = empty_tokens()
                    add_usage(turn_tokens, event.usage)
                    phase_orch_turns.setdefault(bucket_key, []).append({
                        "kind": "direct_turn",
                        "started_at": (
                            event.timestamp.isoformat() if event.timestamp else None
                        ),
                        "model": event.model,
                        "estimated_cost_usd": (
                            round(cost, 6) if cost is not None else 0.0
                        ),
                        "cost_is_partial": cost is None,
                        "tokens": turn_tokens,
                        "text_preview": event.text_preview,
                    })
            continue

        if event.kind == "tool_use":
            tool_name = event.tool_name or ""
            is_skill = tool_name in ("Skill", "Agent")

            if is_skill:
                if not open_frames:
                    # A new top-level dispatch is starting; the previous
                    # skill's "active" regime ends here. Flush so its
                    # absorbed inline work lands in the phase before we
                    # open the new frame.
                    _flush_pending()
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

            # Phase-boundary marker: top-level TaskUpdate setting a known
            # phase-bearing task to in_progress. See the task_phase_map
            # pre-scan above for why this is the only signal for inline-
            # dispatched ACE phases. Advance before attaching so the marker
            # tool itself lands in the new phase (it's the "Phase 3 starts
            # here" beat, not the tail of Phase 2). Also flush any pending
            # top-level skill — its regime ends when the phase boundary
            # crosses, even if no new skill has dispatched yet.
            if (
                tool_name == "TaskUpdate"
                and not open_frames
                and (event.tool_input or {}).get("status") == "in_progress"
            ):
                new_phase = task_phase_map.get(
                    str((event.tool_input or {}).get("taskId", ""))
                )
                if new_phase and new_phase != current_phase:
                    _flush_pending()
                    current_phase = new_phase
                elif new_phase:
                    current_phase = new_phase

            # Regular tool call (Bash, Read, Edit, etc.)
            # For top-level tools (no enclosing skill frame), attribute a
            # share of the parent assistant turn's cost to the tool row so
            # the user can scan "where did the money go." Cost is split
            # evenly across parallel tools fired by the same turn. Display
            # only — phase rollups still come from the synthetic skill
            # bucket, so no double-count.
            tool_cost = 0.0
            tool_cost_partial = False
            if not open_frames and event.uuid in turn_cost:
                c, n = turn_cost[event.uuid]
                if c is None:
                    tool_cost_partial = True
                elif n > 0:
                    tool_cost = c / n
            tool_node = {
                "kind": "tool",
                "tool_use_id": event.tool_use_id or "",
                "tool_name": tool_name,
                "label": _tool_label(tool_name, event.tool_input),
                "started_at": event.timestamp.isoformat() if event.timestamp else None,
                "wall_time_seconds": 0,
                "estimated_cost_usd": round(tool_cost, 6),
                "cost_is_partial": tool_cost_partial,
                "status": "ok",
                "content_preview": None,  # filled in by the matching tool_result
            }
            if open_frames:
                _attach(tool_node, frame=open_frames[-1], phase_name=None, turn_uuid=event.uuid)
            elif pending_top_skill is not None:
                # Top-level tool fired after a skill's dispatch closed —
                # absorb into that skill's children (orchestrator follow-on).
                _attach(
                    tool_node, frame=None, phase_name=None,
                    target_dict=pending_top_skill, turn_uuid=event.uuid,
                )
                if event.timestamp is not None:
                    pending_top_skill["_last_ts"] = event.timestamp.isoformat()
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
                # The frame itself is "error" only if its own closing
                # tool_result is_error — tool errors of its children don't
                # promote up. (See the comment in `aggregate()` rollup.)
                if event.is_error:
                    frame.status = "error"
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
                    # Top-level skill closed. Don't attach to the phase yet —
                    # stage it as the active pending skill so subsequent
                    # inline work (orchestrator narration + loose tool calls)
                    # gets absorbed into this skill's children. Flush any
                    # previously-pending one first; the new skill takes over.
                    _flush_pending()
                    skill_node["_phase_name"] = frame.phase_name
                    skill_node["_last_ts"] = (
                        frame.last_ts.isoformat() if frame.last_ts else None
                    )
                    skill_node["_last_turn_uuid"] = None
                    skill_node["_last_parallel_group"] = None
                    pending_top_skill = skill_node
                continue

            # Regular tool result — find the open tool node and update it.
            # Tools fired by the orchestrator at top level live inside
            # pending_top_skill (the absorber for follow-on work); fall back
            # to phase children for pre-skill orchestrator tool calls.
            if open_frames:
                target_children = open_frames[-1].children
            elif pending_top_skill is not None:
                target_children = pending_top_skill["children"]
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

    # Flush any pending top-level skill — its regime ends at end-of-stream.
    _flush_pending()

    # Inject orchestrator-thinking as a synthetic "(orchestration)" skill row
    # in each phase that has any. The cost lives in `phase_orch_*` because it
    # came from top-level assistant turns with no enclosing frame — without a
    # synthetic row to carry it, the phase rollup would lose this spend even
    # though wall-time and tool nodes are correctly bucketed under the phase.
    # The phase view's mental model is Phase → Agent/Skill — tool noise below
    # that is rarely useful. Pull every top-level tool / parallel_group out of
    # the phase and into the synthetic "Inline work" skill so each phase's
    # direct children are exclusively skill rows. The synthetic skill becomes
    # the home for everything the orchestrator did directly: narration turns,
    # one-off Bash/Read calls, MCP tool invocations.
    all_phase_keys = set(phase_orch_tokens) | set(phase_buckets)
    for bucket_key in all_phase_keys:
        bucket = _ensure_phase(bucket_key)
        # Split phase children: tools/parallel_groups go inside the synthetic
        # skill; everything else (real skill dispatches) stays at phase level.
        inline_children: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []
        for child in bucket["children"]:
            if child["kind"] in ("tool", "parallel_group"):
                inline_children.append(child)
            else:
                kept.append(child)
        bucket["children"] = kept

        tokens = phase_orch_tokens.get(bucket_key, empty_tokens())
        has_orch_cost = any(tokens.values()) or phase_orch_partial.get(bucket_key, False)
        if not has_orch_cost and not inline_children:
            continue
        synthetic_skill = {
            "kind": "skill",
            "name": "(direct turns)",  # stable key — don't change
            "display": "Inline work",
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
            # Narration turns first (they show "what the orchestrator was
            # doing"), then the tool calls they fired. Tools default-hidden
            # in the UI; the "Show tool calls" toggle reveals them.
            "children": [*phase_orch_turns.get(bucket_key, []), *inline_children],
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

    # Tool-level errors stay pinned to the tool row that caused them; we do not
    # roll them up to skill / phase / session because a single tool failure
    # rarely means "this skill failed" (most tool errors are caught and worked
    # around). Incomplete still rolls up — a frame that never closed is a real
    # lifecycle signal, not a transient tool blip.
    session_status = "ok"
    if any(p["status"] == "incomplete" for p in phases):
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


def _phase_wall_span(bucket: dict) -> int:
    """Compute phase wall as the span of its first → last child timestamp.

    Summing child wall_time double-counts: a top-level Bash tool runs *during*
    an orchestrator-thinking turn, so the synthetic "direct turns" span and
    the tool's wall both cover the same wall-clock seconds. Use a span instead
    — the phase wall is "from earliest activity to latest activity in this
    bucket", which is what a user reading "wall=822s" expects.
    """
    starts: list[datetime] = []
    ends: list[datetime] = []
    for child in bucket["children"]:
        start_iso = child.get("started_at")
        if not start_iso:
            continue
        try:
            start = datetime.fromisoformat(start_iso)
        except ValueError:
            continue
        wall = child.get("wall_time_seconds", 0) or 0
        starts.append(start)
        ends.append(start + timedelta(seconds=wall))
    if not starts:
        return 0
    return wall_time_seconds(min(starts), max(ends))


def _roll_phase_totals(bucket: dict) -> None:
    """Sum cost/tokens from a phase's direct children; wall is a span.

    Status rolls up `incomplete` only — see the comment in `aggregate()` for
    why tool errors stay pinned to the tool row.
    """
    cost = 0.0
    cost_partial = False
    tokens = empty_tokens()
    status = "ok"
    for child in bucket["children"]:
        if child["kind"] == "skill":
            cost += child.get("estimated_cost_usd", 0.0)
            cost_partial = cost_partial or child.get("cost_is_partial", False)
            for k in tokens:
                tokens[k] += child.get("tokens", {}).get(k, 0)
            if child.get("status") == "incomplete":
                status = "incomplete"
    bucket["wall_time_seconds"] = _phase_wall_span(bucket)
    bucket["estimated_cost_usd"] = round(cost, 6)
    bucket["cost_is_partial"] = cost_partial
    bucket["tokens"] = tokens
    bucket["status"] = status
