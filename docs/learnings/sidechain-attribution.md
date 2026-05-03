# Learning: Sidechain assistant turns attribute via parentUuid → containing-message uuid

**Date**: 2026-05-03
**Context**: `apps/ingest/cost_aggregator.py` rolls subagent activity into the parent skill segment for cost/timing breakdowns. Without sidechain attribution, all subagent token spend lands in the "Orchestration" pseudo-phase and Phase totals under-report by the cost of every Agent dispatch.
**Status**: Active — covered by `apps/ingest/tests/test_cost_aggregator.py::test_aggregate_attributes_sidechain_to_agent_segment`.

## Problem

Claude Code's `Agent` tool dispatches subagents whose work is recorded in the same JSONL with `isSidechain: true`. The sidechain assistant turns do **not** carry the parent `tool_use_id` directly. Their `parentUuid` points to the **containing assistant message** of the parent's `tool_use` block — not to `tool_use_id`, not to the `Agent` event itself.

A naive aggregator that drops all sidechain turns under-reports phase costs by 30–80% on ACE runs (most of the work happens inside subagents). A naive aggregator that buckets sidechain turns into "Orchestration" produces a misleading "Orchestration was the most expensive phase" result.

## Root cause

The transcript structure is:

```
{uuid: u-5, content: [{type: tool_use, id: tu-agent-1, name: Agent}]}        <- non-sidechain
{uuid: u-6, parentUuid: u-5, isSidechain: true, content: [{type: text, ...}]} <- sidechain root
{uuid: u-7, parentUuid: u-6, isSidechain: true, content: [{type: text, ...}]} <- sidechain continuation
```

`u-6.parentUuid == u-5` and `u-5` is the assistant message that *contained* the `tool_use` block — so attribution requires matching against the **containing message uuid**, not the `tool_use_id`.

## Fix / Key takeaway

When opening an `Agent`/`Skill` segment, record the `tool_use` event's own `uuid` (the containing assistant message) on the segment alongside the `tool_use_id`. For each sidechain assistant turn, walk the `parentUuid` chain upward; if any ancestor uuid matches an open segment's `containing_msg_uuid`, attribute the turn's tokens there. Otherwise drop to Orchestration.

The walk is bounded by `seen: set[str]` to defend against malformed transcripts that loop back to themselves.
