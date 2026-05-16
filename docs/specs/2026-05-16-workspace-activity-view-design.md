# Workspace Activity View — Design Doc

**Status:** Draft · 2026-05-16
**Author:** jjackson + Claude (brainstorming session)
**Scope:** A unified "what's happening across the workspace right now?" view, rendered identically (data-wise) on both ace-web and Slack.

## Why

Today both surfaces (ace-web's Phase view, Slack's `/ace list opps`) are
opp-scoped. Neither answers the question:

> "What's running across all opps right now, on anyone's machine or in the cloud — and how stale is each one?"

Today the answer requires clicking into every opp one by one. The
Activity view fills that gap. Same data, two presentations.

## Design principles

1. **Slack is a co-equal surface, not a notification channel.** Every
   capability the Activity view exposes lands on both ace-web and Slack.
   The data primitive is shared; the rendering is platform-native.

2. **Phase view is the canonical opp drill-down.** Clicking a row in the
   Activity view deep-links to Phase view, not the Workbench. Workbench
   becomes a power-user fallback.

3. **Show observable facts, don't infer state.** Plugin runs break all
   the time. We can't reliably tell "alive vs dead" from outside. So:
   - **Don't** label rows "running" / "broken" / "stuck".
   - **Do** show "last update 3m ago" / "last update 47m ago".
   - Some legitimate steps take minutes; 10m stale ≠ broken.
   - Sort by recency, let the user's eye do the categorization.
   - Use colour/opacity to fade older rows, not to claim liveness.

4. **Source attribution is also a fact, not a claim.** We can tell:
   - There IS an active ace-web `Session` touching this run → "ace-web"
   - There is NO matching Session, only Drive writes → "Drive only"
   - Both are facts about what *we observed*, not claims about *what's
     alive*. (A laptop run could be paused at a prompt, an ace-web
     session could be a zombie task that hasn't exited yet.)

5. **Heartbeat is a future option, not v1.** If timestamp-only UX feels
   weak after living with it, add a `POST /api/ace/heartbeat?slug=X&run_id=Y`
   that the plugin pings every 30s while alive. Then we *can* promote
   "last touched Nm ago" to "actively running" with confidence. See
   "Open questions" at the bottom.

## Data shape

A new endpoint `GET /api/w/<slug>/activity` returns a list of
`ActivityRow` items, one per recent-active run.

### `ActivityRow`

| Field | Type | Source | Notes |
|---|---|---|---|
| `opp_slug` | str | Drive opp folder name | |
| `opp_display_name` | str | `opp.yaml` | Falls back to slug. |
| `run_id` | str | Drive `runs/<id>/` folder name | |
| `last_activity_at` | ISO-8601 timestamp | Drive `modifiedTime` of `run_state.yaml` | The cheapest live signal. |
| `current_phase_name` | str \| null | `run_state.yaml.current_phase` | null when run has finished or hasn't started a phase. |
| `current_phase_display` | str \| null | plugin metadata lookup | Eg. "Connect Setup". |
| `current_step_name` | str \| null | `run_state.yaml.current_step` | The skill name. |
| `current_step_display` | str \| null | plugin metadata lookup | |
| `lifecycle_status` | "in_progress" \| "complete" \| "qa-failed" \| "error" | `run_state.yaml` | What the file *says*, not what the plugin *is doing*. |
| `last_actor` | str \| null | `run_state.yaml.last_actor` | Plugin's self-reported actor (e.g. "ace@dimagi-ai.com"). |
| `source_hint` | "ace-web" \| "drive-only" | inferred | See below. |
| `source_actor_email` | str \| null | `Session.created_by.email` | Only present when source_hint = "ace-web". |
| `phase_url` | str | derived | Deep-link to `/w/<slug>/opps/<opp_slug>?run_id=<run_id>` (the Phase view). |

### Source-detection logic

```
def detect_source(workspace, opp_slug, run_id) -> tuple[source_hint, actor_email | None]:
    # An ace-web chat Session is bound to (slug, run_id) on creation.
    session = (
        Session.objects
        .filter(opp_slug=opp_slug, opp_run_id=run_id, status="active")
        .order_by("-updated_at")
        .first()
    )
    if session is not None:
        return ("ace-web", session.created_by.email if session.created_by else None)
    return ("drive-only", None)
```

`drive-only` is the explicit, documented label — NOT "laptop". A
drive-only row could mean:
- A laptop is driving it
- An old ace-web session was deleted but the run kept going somewhere
- Two cloud tasks raced and one finished without a Session row
- ace@dimagi-ai.com automation that doesn't open a chat session

The UI labels it "Drive only · last update 3m ago" — leaving
interpretation to the user.

### Filtering

By default, `GET /api/w/<slug>/activity` returns rows where:
- `lifecycle_status != "complete"`, OR
- `last_activity_at >= now - 24h`

Sort: `last_activity_at` desc.

Default limit: 20. The frontend can request `?limit=50` for the full
view; the Slack surface caps at 10.

`?include_completed=false` (default true) — when false, even
recently-completed runs are dropped, leaving only `in_progress` /
`qa-failed` / `error`. Useful for a tighter "what needs attention" view.

## Implementation

### Backend

- New module `apps/activity/workspace_activity.py` (sibling to the
  existing `apps/activity/` Workspace Timeline aggregator).
- Reuses `apps.opps.api.list_opp_cards` + `list_opp_runs_for_workspace`
  to enumerate opps/runs from Drive. **One Drive snapshot read per
  request** — same cost as `/ace list opps`. Async response_url path on
  the Slack side stays the same.
- New Ninja endpoint at `apps/api/activity.py` (or extend the existing
  `apps/activity/api.py`) returning `list[ActivityRowOut]` Pydantic
  model.

### ace-web rendering

Add a workspace-level **Activity** view at `/w/<slug>/activity`. Sits in
top-nav alongside Opps / Sessions / etc. Renders as a table:

```
Activity · dimagi-team

┌──────────────────────────────┬────────────────────┬──────────────┬─────────────┬───────────┐
│ Opp                          │ Run                │ Source       │ Last update │ State     │
├──────────────────────────────┼────────────────────┼──────────────┼─────────────┼───────────┤
│ turmeric                     │ 20260515-1830      │ ace-web      │ 12s ago     │ Phase 3:  │
│   Turmeric Initiative         │  (jjackson)        │              │             │  Connect  │
│                              │                    │              │             │   Setup   │
├──────────────────────────────┼────────────────────┼──────────────┼─────────────┼───────────┤
│ rural-tb-screening           │ 20260515-1715      │ Drive only   │ 4m ago      │ Phase 2:  │
│   Rural TB Screening          │                    │              │             │  Scenarios│
├──────────────────────────────┼────────────────────┼──────────────┼─────────────┼───────────┤
│ leep-paint-collection        │ 20260514-1530      │ Drive only   │ 47m ago     │ qa-failed │
│   (faded, sub-section)        │                    │              │             │           │
└──────────────────────────────┴────────────────────┴──────────────┴─────────────┴───────────┘

Showing 3 active runs · 12 completed in last 24h (toggle to show)
```

Row click → Phase view at the opp+run.

Visual treatment:
- Top section: rows with `last_activity_at` within 5m — bright, full-opacity.
- Middle section: 5m-1h — slightly faded.
- Bottom section: >1h — heavy fade, smaller font.
- Auto-refresh every 30s (visible "Last refreshed Xs ago · ↻ refresh").

No "running" labels anywhere.

### Slack rendering — `/ace activity`

Use Block Kit fully:

```
🔔 Workspace activity · dimagi-team — 3 active

──────────────────────────────────────────────
   *turmeric*  ·  `20260515-1830`             [Open ↗] [⋯]
   Phase 3 · Connect Setup · `create-payment-units`
   ace-web · jjackson · last update 12s ago
──────────────────────────────────────────────
   *rural-tb-screening*  ·  `20260515-1715`    [Open ↗] [⋯]
   Phase 2 · Scenarios & Acceptance
   Drive only · last update 4m ago
──────────────────────────────────────────────
   *leep-paint-collection*  ·  `20260514-1530`   [Open ↗] [⋯]
   qa-failed
   Drive only · last update 47m ago
──────────────────────────────────────────────
↻ Refresh   ·   Showing 3 active   ·   /ace activity --all to include recent completed
```

Each row uses a `section` block with the title + metadata, plus an
`actions` accessory or a separate `actions` block holding:
- `[Open ↗]` — URL button to Phase view
- `[⋯]` overflow menu:
  - "Track this run" → `SlackRunThread` create
  - "Fork from current phase…" → deep-link to ForkOppDialog
  - "Stop tracking" (if currently tracked)

Dividers between rows. Context block at the bottom for the refresh +
count info. The whole message uses `response_url` async (the data fetch
is one Drive snapshot read + one Session query — 1-2s typical, but the
3s budget warrants async).

`/ace activity --all` includes completed runs from the last 24h.

## Files touched

**Backend:**
- Create: `apps/activity/workspace_activity.py` — aggregator + `ActivityRow` dataclass
- Create: `apps/activity/tests/test_workspace_activity.py`
- Modify: `apps/activity/api.py` — add `list_workspace_activity` endpoint
- Modify: `apps/api/api.py` — register if not already auto-included

**Slack:**
- Create: `apps/slack/verbs_activity.py` — `/ace activity` handler
- Modify: `apps/slack/handlers.py` — route `activity` verb
- Modify: `apps/slack/blocks.py` — `render_activity_row` + accessory factories

**Frontend:**
- Create: `frontend/src/pages/WorkspaceActivityPage.tsx`
- Create: `frontend/src/api/activity.ts` — fetch hook
- Modify: `frontend/src/router.tsx` — add `/w/:workspaceSlug/activity` route
- Modify: top-nav or workspace shell — add "Activity" link

**Docs:**
- Modify: `docs/architecture/slack-integration.md` — runbook entry
- Modify: `CLAUDE.md` — workspace activity entry

## Out of scope (v1)

- Plugin heartbeat. We defer this until timestamp-only UX is proven
  insufficient.
- Per-row "Stop the run" (we don't have a kill signal anyway).
- Cross-workspace activity (Activity is always workspace-scoped).
- Push-based UI updates (auto-refresh on a timer is fine for v1).

## Open questions

1. **Heartbeat: add now or later?**
   - **For:** Promotes "last update Nm ago" to "actively running" with
     confidence; lets us distinguish "stalled at a prompt" from "crashed".
   - **Against:** Plugin code change + new endpoint + cookie/token plumbing
     between the laptop plugin and ace-web; the Drive `modifiedTime` is
     already a decent passive signal for most operations.
   - **Recommendation:** ship Activity view without heartbeat, live with
     it for 1-2 weeks, revisit if the team consistently can't tell what's
     live from timestamps.

2. **Should Activity be the workspace landing page?**
   - **For:** It's the first thing you want to see when you walk in.
   - **Against:** Most days the answer is "nothing's running" — the opp
     grid is more useful then.
   - **Recommendation:** add it to the top nav as "Activity" with a
     count badge ("Activity (3)"); landing stays Opps.

3. **Slack `/ace activity` and the parent card from `/ace run` / `/ace track`** —
   do they overlap meaningfully? The parent card tracks ONE run; activity
   lists MANY. Different views of the same data. I think they coexist
   cleanly.

## Implementation plan

After spec approval, this becomes a single PR (or 2-3 small ones in a
stack):

1. **Backend aggregator + API** — `apps/activity/workspace_activity.py`,
   API endpoint, tests. Standalone-shippable.
2. **Slack `/ace activity`** — Block Kit + handler + tests.
3. **Frontend Activity page** — React page + route + nav link.

Each PR is independently useful — backend API alone is testable; Slack
verb works without the frontend; frontend works without Slack changes.

## Sign-off

When approved, will draft an implementation plan under
`docs/superpowers/plans/` and execute via subagent-driven-development.
