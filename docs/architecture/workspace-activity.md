# Workspace Activity — operator runbook

Cross-surface "what's running across the workspace right now?" view.
Rendered identically (data-wise) on both ace-web and Slack — same
backend primitive, two presentations.

Spec: [`docs/specs/2026-05-16-workspace-activity-view-design.md`](../specs/2026-05-16-workspace-activity-view-design.md)

## What you see

### ace-web
- Top-nav item **Activity** (first in the workspace nav) →
  `/w/<slug>/activity`
- Table view: opp, run-id, state, source, last update
- Auto-refresh every 30s; manual ↻ refresh
- Recency-based opacity fade (bright <5m, faded >1h) — never hides
  rows, never claims liveness
- Row click → Phase view (`/w/<slug>/opps/<opp>?run_id=<id>`),
  the canonical opp drill-down

### Slack
- `/ace activity` — active runs from the last 24h
- `/ace activity --all` — same, including recently-completed runs
- Block Kit thread: header + section blocks per row + `Open ↗` accessory
  + `Track in this channel` action button
- Always async via `response_url` (Drive read can be 5-15s on cold cache)

## The data primitive

Both surfaces consume `GET /api/w/<slug>/activity/runs`. Implementation:
- `apps/activity/workspace_activity.py` — aggregator + `ActivityRow`
- `apps/activity/api.py` — `workspace_activity` Ninja endpoint

Each row is built from:
- `apps.opps.api.list_opp_cards(workspace)` — one row per opp's current run
- `apps.activity.workspace_activity.detect_source(...)` — looks for an
  active `Session` bound to `(opp_slug, opp_run_id)`; returns `"ace-web"`
  + actor email if found, else `"drive-only"`

## Design constraint: observable facts only

Plugin runs break all the time, and we can't reliably probe liveness.
The view enforces this discipline:

| Don't say | Say |
|---|---|
| "Running" / "Broken" | "Last update 3m ago" |
| `is_alive=true` | (don't carry that field at all) |
| `running` / `paused` status badges | recency-based opacity fade |
| "Laptop" / "Cloud" hard claim | `ace-web` (Session found) / `Drive only` (no Session) |
| "✓ complete" inferred from `current_phase=None` | nothing — `current_phase=None` could mean finished, crashed, or between phases. Don't claim. |

A `drive-only` row could be a laptop, a stranded session, an
`ace@dimagi-ai.com` automation run, or two cloud tasks racing. We
describe what we observed, not what we suspect.

## Operational notes

- **Cost per request:** one Drive snapshot read (cached) + one Session
  lookup per opp. Same shape as `/api/w/<slug>/opps`.
- **No background workers.** This is read-through, request-time only.
- **Auto-refresh cadence** in the frontend: 30s. The Slack surface is
  on-demand (each slash command invocation is a fresh fetch).
- **`server_now` field** in the API response lets the frontend compute
  "N ago" deltas without client-clock skew.

## Troubleshooting

- **Activity page shows no rows but `/ace list opps` shows opps**:
  Activity drops opps with `last_run_id=None` (no runs yet). Expected.
- **Source shows "Drive only" for a run someone clearly started in
  ace-web**: the chat Session may have been archived (`status !=
  "active"`). `detect_source` only matches active Sessions.
- **Slack `/ace activity` times out**: shouldn't happen — we ack via
  `response_url`. If it does, check that `verbs_activity.run_async` was
  reached (look for "Loading workspace activity…" in the channel).
- **"Last update" shows "—"** for a row: the opp's `run_state.yaml` has
  no `modifiedTime` (very rare). Drive sync issue; investigate at the
  Drive level.

## Heartbeat — not implemented

The spec flagged a plugin heartbeat (`POST /api/ace/heartbeat?slug=X&run_id=Y`
every 30s while alive) as a future option. If timestamp-only UX
proves insufficient — i.e. people consistently can't tell whether a
"45m ago" row is genuinely stalled vs. mid-LLM-thinking — that's the
upgrade path. Until then, we ship facts and let the user interpret.
