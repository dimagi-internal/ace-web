# Per-session and per-opp cost & timing breakdown

**Date**: 2026-05-03
**Status**: Design — pending approval before implementation plan
**Owner**: Jonathan Jackson

## Background

Every Claude CLI `.jsonl` transcript that lands in ace-web (via
`/ace:upload-transcript`, the plugin-side skill triggered by
`/ace:run --ace-web-url`) already carries everything we need to answer
"how long did Phase 4 take" and "what did this opp cost":

- Each `assistant` event has a `usage` block (`input_tokens`,
  `output_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`) plus a `message.model` field.
- Every event has `timestamp`.
- `tool_use` blocks name the `Skill` / `Agent` invocation; `tool_result`
  blocks reference the originating `tool_use_id`. A skill segment is
  everything between those two.
- Subagent dispatches show up as `isSidechain: true` events with a
  `parentUuid` chain that resolves back to the originating Agent
  `tool_use_id`, so phase-level boundaries are recoverable.

The current ingest pipeline (`apps/ingest/parser.py` →
`apps/sessions/models.Message`) ignores all of this. Costs and wall
times are not exposed anywhere in ace-web today.

## Goal

Surface per-phase / per-skill cost and timing breakdowns inside ace-web's
existing UI, computed once at ingest time and persisted on the `Session`
row. Two surfaces:

1. **Per-session detail view** — one row per phase, expandable to
   per-skill, expandable again to per-invocation when a skill ran more
   than once. Header totals (wall time, $, cache hit ratio).
2. **Per-opp Workbench rollup** — a card on `OppWorkbenchPage`
   summing across every transcript linked to the opp via `opp_slug`.
   Click → dialog with the same phase-by-phase table summed across
   all linked sessions, each phase row linking back to the contributing
   sessions.

## Non-goals

- **Live timing during a run.** This is a post-hoc analysis on
  uploaded JSONL. Live observability would require a `PostToolUse` hook
  or status-line widget — explicitly out of scope.
- **Eval harness.** Phase 5 ("Polish") is deferred indefinitely
  (CLAUDE.md). This feature does not revive it.
- **Re-aggregation history.** We persist the aggregator's output, not
  the source JSONL. If the aggregator logic changes meaningfully, we
  tell users to re-upload via `/ace:upload-transcript`. No source-file
  storage, no S3 dependency, no `reaggregate_costs` management command.
- **Backfill of pre-existing uploads.** Going-forward only. Existing
  uploads (and uploads from CLI versions that pre-date the parser
  extension) display "No cost data — re-upload to populate."

## Architecture

```
┌──────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│  /ace:upload-    │────▶│  apps/ingest/        │────▶│  apps/ingest/      │
│  transcript      │     │  parser.py (extended)│     │  cost_aggregator.py│
└──────────────────┘     └──────────────────────┘     └────────────────────┘
                                  │                            │
                                  ▼                            ▼
                         ┌─────────────────────────────────────────────┐
                         │  Session.cost_breakdown (JSONField)         │
                         └─────────────────────────────────────────────┘
                                  │                            │
              ┌───────────────────┘                            └────────────┐
              ▼                                                             ▼
   GET /api/sessions/<slug>/cost-breakdown          GET /api/opps/<slug>/cost-rollup
              │                                                             │
              ▼                                                             ▼
   Cost & Timing tab on session detail              Cost card on OppWorkbenchPage
   (frontend/src/components/sessions/...)           (frontend/src/components/opps/...)
```

Phase / skill labels come from `apps/system/reader.py`'s existing
agent-frontmatter registry — the same source of truth that
`apps/system/` and `apps/opps/` already use. No hardcoded
phase mapping in this feature.

## Component design

### 1. Parser extension — `apps/ingest/parser.py`

Add a parallel cost-aggregation pass alongside the existing
turn-extraction. The new pass walks every JSONL line and emits a flat
list of events:

```python
@dataclass
class CostEvent:
    timestamp: datetime              # from line.timestamp
    uuid: str                        # from line.uuid
    parent_uuid: str | None          # from line.parentUuid
    is_sidechain: bool               # from line.isSidechain
    kind: Literal["assistant_turn", "tool_use", "tool_result"]
    # assistant_turn fields
    model: str | None                # from message.model
    usage: dict | None               # raw usage block
    # tool_use fields
    tool_use_id: str | None
    tool_name: str | None            # "Skill", "Agent", "Read", ...
    tool_input: dict | None          # for Skill: {"skill": "..."}, for Agent: {"subagent_type": "..."}
    # tool_result fields
    matched_tool_use_id: str | None  # from tool_result.tool_use_id
```

The original `ParsedTurn` flow is untouched. `parse_session_file`
returns both the existing `ParsedSession` and a new
`list[CostEvent]`.

### 2. Aggregator — `apps/ingest/cost_aggregator.py`

New module. Pure function:
`aggregate(events: list[CostEvent]) -> CostBreakdown`.

Algorithm:

1. Build a `parent_uuid → [uuid]` index for sidechain attribution.
2. Walk events in chronological order, maintaining a stack of open
   segments: `[(skill_name, tool_use_id, start_ts, accumulator)]`.
3. On a `tool_use` whose `tool_name` is `Skill` or `Agent`: extract
   the skill name from `tool_input` (`tool_input["skill"]` for Skill,
   `tool_input["subagent_type"]` for Agent). Push a new segment.
4. On a `tool_result` whose `matched_tool_use_id` matches a segment
   on the stack: pop, finalize. `wall_time = last_event_ts -
   first_event_ts`. Tokens = sum of `usage` over all assistant turns
   *inside* the segment, including assistant turns from sidechain
   children whose `parentUuid` chain resolves to this segment's
   `tool_use_id`.
5. Events outside any segment → "Orchestration" pseudo-phase.
6. Map each finalized segment to its phase via
   `apps.system.reader.skill_index_by_name`. Unknown skills → "Other"
   pseudo-phase.
7. Apply pricing (per-model, per-usage-tier) to each segment's totals.

Output JSON shape (this is what gets stored on
`Session.cost_breakdown`):

```json
{
  "schema_version": 1,
  "computed_at": "2026-05-03T18:42:11Z",
  "totals": {
    "wall_time_seconds": 4823,
    "input_tokens": 12345,
    "output_tokens": 67890,
    "cache_creation_tokens": 23456,
    "cache_read_tokens": 987654,
    "estimated_cost_usd": 1.234,
    "cache_hit_ratio": 0.91
  },
  "phases": [
    {
      "phase_name": "design-review",
      "phase_display": "Phase 1: Design Review",
      "phase_ordinal": 1,
      "wall_time_seconds": 412,
      "estimated_cost_usd": 0.18,
      "tokens": { "input_tokens": ..., "output_tokens": ..., "cache_creation_tokens": ..., "cache_read_tokens": ... },
      "skills": [
        {
          "skill_name": "ace:idea-to-pdd",
          "invocation_count": 2,
          "wall_time_seconds": 252,
          "estimated_cost_usd": 0.11,
          "tokens": { ... },
          "invocations": [
            { "start_ts": "...", "wall_time_seconds": 130, "estimated_cost_usd": 0.06, "tokens": { ... } },
            { "start_ts": "...", "wall_time_seconds": 122, "estimated_cost_usd": 0.05, "tokens": { ... } }
          ]
        }
      ]
    },
    {
      "phase_name": "_orchestration",
      "phase_display": "Orchestration",
      "phase_ordinal": 0,
      "wall_time_seconds": 87,
      "estimated_cost_usd": 0.04,
      "tokens": { ... },
      "skills": []
    }
  ]
}
```

`phase_ordinal: 0` sorts orchestration to the top of the table.
`_orchestration` and `_other` are reserved phase names that the UI
recognizes for special rendering (italicized label, no link).

### 3. Pricing table — `apps/ingest/pricing.py`

Small dict keyed by model id prefix. All values are **USD per million
tokens**.

```python
PRICING = {
    "claude-opus-4":   {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.5},
    "claude-sonnet-4": {"input":  3.0, "output": 15.0, "cache_write":  3.75, "cache_read": 0.30},
    "claude-haiku-4":  {"input":  1.0, "output":  5.0, "cache_write":  1.25, "cache_read": 0.10},
}
# Source: anthropic.com/pricing. Last refreshed 2026-05-03.
```

Rates may need a refresh roughly twice a year; that is a one-line edit
plus a comment update. Unknown model ids → cost field is `null` for
that turn (tokens still tracked); the segment-level
`estimated_cost_usd` is the sum of resolvable turns only, with a
boolean `cost_is_partial: true` set on the segment when any turns were
unpriceable.

### 4. Persistence

Single Django migration:

```python
class Session(models.Model):
    ...
    cost_breakdown = models.JSONField(default=dict, blank=True)
```

The upload endpoint (`apps/ingest/views.py::upload`) runs the parser,
runs the aggregator, populates `Session.cost_breakdown` in the same
transaction that creates the session and bulk-creates messages.
Aggregator failures are caught and logged; the upload still succeeds
with `cost_breakdown = {}` so cost-tracking failures don't break
transcript ingest.

### 5. Read APIs

Both endpoints live under existing app URL roots; both use the
standard `{data, error}` envelope (`apps.common.envelope`).

- **`GET /api/sessions/<slug>/cost-breakdown`** — workspace-scoped
  permission (same as session detail). Returns
  `Session.cost_breakdown` directly. Empty breakdown returns
  `{ data: { schema_version: 0, totals: null, phases: [] } }` so the
  UI can render the "no cost data" state without a 404 round-trip.

- **`GET /api/opps/<slug>/cost-rollup`** — workspace-scoped (same as
  opp Workbench reads). Loads all sessions in the workspace whose
  `opp_slug` matches, sums `phases[].tokens` + `wall_time_seconds` +
  `estimated_cost_usd` across them grouped by `phase_name`. Returns:

  ```json
  {
    "totals": { ... },
    "phases": [ { "phase_name": ..., "tokens": ..., "wall_time_seconds": ...,
                  "estimated_cost_usd": ...,
                  "session_slugs": ["abc12345", "def67890"] } ],
    "session_count": 2,
    "sessions_without_breakdown": 1
  }
  ```

  `sessions_without_breakdown` is the count of linked sessions with
  empty `cost_breakdown` so the UI can disclose under-counting.

### 6. UI surfaces

**Per-session — new "Cost & Timing" tab** added to the session detail
view (alongside existing chat / metadata). Layout:

- **Header strip**: total wall time (e.g. "1h 20m"), total cost
  (e.g. "$1.23"), cache hit ratio (e.g. "91%"), session model
  composition (e.g. "Opus 4.7 · 87% · Sonnet 4.6 · 13%").
- **Phase table**: one row per phase, columns:
  Phase · Wall time · Cost · Output tokens · Cache hit %.
  Default sort: wall time desc. Toggle: sort by cost desc.
  Each row is a disclosure: expand → list of skills inside that phase
  with the same column shape. Each skill row with
  `invocation_count > 1` is itself a disclosure: expand → per-invocation
  rows with start timestamp + delta.
- **Empty-state** ("No cost data"): single sentence + link to docs
  for `/ace:upload-transcript` and a "Re-upload" button that opens
  the upload modal.

Component placement: `frontend/src/components/sessions/CostTimingTab.tsx`
plus three sub-components (`CostPhaseRow`, `CostSkillRow`,
`CostInvocationRow`). Uses existing shadcn Table + Disclosure
primitives.

**Per-opp — new card on `OppWorkbenchPage`** placed next to
`ScorecardPanel.tsx` in the header. Surface:

- **Chip** showing opp totals (e.g. "$3.42 · 5h 18m") with a
  cache-hit-ratio dot.
- **Click → dialog** with the same phase-table shape as the per-session
  view. Each phase row shows which sessions contributed (linked).
  When `sessions_without_breakdown > 0`, a banner: "N sessions
  haven't been re-uploaded since cost tracking shipped — totals may
  understate."

Component placement: `frontend/src/components/opps/CostRollupCard.tsx`
+ `CostRollupDialog.tsx`. Reuses the same `CostPhaseRow` from the
per-session tab.

## Edge cases

- **Transcripts with no `usage` blocks** (very old CLI versions, or
  uploads that pre-date stream-json metadata): aggregator emits an
  empty breakdown. UI shows "No cost data."
- **Mid-stream tool errors / interrupted runs**: a `tool_use` with no
  matching `tool_result`. Aggregator finalizes the segment at the last
  observed event timestamp inside it; flags `incomplete: true` on the
  segment. UI renders "(interrupted)" suffix on the phase row.
- **Nested skill calls** (a skill invoked inside another skill): handled
  naturally by the segment stack — inner segment's tokens roll up to
  itself; the outer segment's totals include the inner via the
  enclosing assistant-turn pass.
- **Sidechain turns whose `parentUuid` chain doesn't resolve to a
  known segment**: bucketed into Orchestration. Logged at `debug`.
- **Unknown skill names** (skill in transcript, not in plugin
  registry): bucketed under the `_other` pseudo-phase. Logged at
  `info` so we notice plugin/web drift.
- **Cost computation when `model` is missing**: usage tracked with
  `cost = null`; the segment's `cost_is_partial: true` flag set so
  the UI can asterisk the displayed dollar amount.

## Testing

- `apps/ingest/tests/test_cost_aggregator.py` — unit tests against a
  new fixture `cost_session.jsonl` with at least one full Phase 1 +
  Phase 2 dispatch including a sidechain. Cases:
  - Phase grouping via system reader (assert phase_display strings).
  - Sidechain rollup: assistant turns with `parentUuid` chains that
    resolve to a parent Agent dispatch are attributed to that
    segment, not Orchestration.
  - `tool_use_id` ↔ `tool_result` matching, including out-of-order
    events.
  - Multi-invocation counting (one skill called twice → one skill row
    with `invocation_count: 2` and two entries in `invocations`).
  - Ungrouped events → Orchestration bucket.
  - Interrupted segment (no matching `tool_result`) → finalized with
    `incomplete: true`.
  - Unknown model id → `cost: null`, segment flagged
    `cost_is_partial: true`.
- `apps/ingest/tests/test_pricing.py` — assert dollar math per model
  + cache-tier weighting, including `cache_read = ~10% of cache_write`.
- `apps/ingest/tests/test_views.py` — extend existing tests to assert
  `cost_breakdown` is populated on upload, including the failure-
  isolation case (aggregator raises → upload still succeeds with
  empty breakdown).
- `apps/sessions/tests/test_cost_endpoints.py` — per-session endpoint
  coverage including the legacy-empty case and the workspace-scoping
  case (non-member gets 404).
- `apps/opps/tests/test_cost_rollup.py` — assert rollup sums correctly
  across multiple linked sessions, ignores sessions without
  breakdowns, returns `sessions_without_breakdown` count.

## Migration / rollout

Single Django migration adds `Session.cost_breakdown` (JSONField,
default `{}`, nullable-equivalent). No data migration. Deploy proceeds
through the normal `deploy-labs.yml` workflow with
`run_migrations: true`.

After deploy, existing uploaded sessions show empty cost breakdowns
in their new tab; new uploads (and re-uploads of old transcripts)
populate. The Workbench cost card on opps with no fresh-upload
sessions shows the empty state with the under-counting banner.

No CLI/plugin changes required. The plugin's `upload-transcript` skill
already sends the JSONL with timestamps and usage intact; the parser
extension simply starts reading those fields.

## Out of scope, intentionally

- Persisting source JSONL for re-aggregation. Aggregator changes will
  require a re-upload via `/ace:upload-transcript`. The plugin owns
  the source on the user's machine; there is no value in maintaining
  a third copy.
- A separate "cost history" / trend view at the workspace or
  cross-opp level. Per-opp + per-session covers the primary use case
  ("what did this opp cost"); a cross-opp dashboard is unjustified
  until requested.
- Live token/cost streaming during in-progress chat. The harness
  already has the `usage` data in the streaming response; surfacing it
  live is a separate, smaller feature that should not block this one.
