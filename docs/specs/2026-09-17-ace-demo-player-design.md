# ACE Demo Player

**Date**: 2026-09-17
**Status**: Design — pending approval before implementation plan
**Owner**: Jonathan Jackson

## Background

An ACE run takes hours and writes real artifacts into six external systems
(Drive, Nova, CommCare HQ, Connect, OCS, connect-labs). You cannot run one in
front of an audience, and you should not want to: the interesting claim is not
"watch it work," it is **"an agent did this autonomously and every step is
auditable."**

Finished artifacts alone do not carry that claim. A training deck, a CommCare
app and a Connect opportunity look like things a human made. What proves the
claim is provenance (every step, verdict, decision and timestamp), liveness
(the audience touches the real systems), and bounded live agency (they watch an
agent actually do something, for minutes rather than hours).

ace-web already holds nearly all of the raw material. The Workbench is built for
ACE-team QA; the public summary page is built for a partner who wants the
deliverables. Neither is built to *tell the story of a run to a room*.

## Goal

A **Demo Player**: an ace-web surface, pointed at any `(workspace, opp, run)`
we have saved, that presents that run as an ordered sequence of **acts** —
starting with a time-compressed replay of the run itself.

It must work on **any** saved run, degrading honestly when a run lacks the data
an act needs. It is a product surface, not a one-off built around a single
golden run.

## Non-goals

- **Not a substitute for the Workbench.** The Workbench stays the QA surface.
  The player is narrative; it links into the Workbench for depth.
- **No new ORM tables.** Like `opps` and `videos`, everything is derived from
  Drive plus already-ingested transcripts.
- **No live agent execution inside the player.** Acts that involve a live agent
  (fork-and-rerun, the email loop, multi-player) are *staged and deep-linked*,
  never driven from inside the player process.
- **No synthetic or illustrative data, ever.** See "The honesty rule".

## The honesty rule

The player's entire value is that it is evidence. A single fabricated number
destroys it, and in a demo about auditability that failure is fatal.

So: **the player never renders a value it cannot source from the run.** When
timing data is absent it shows ordering and says so, rather than drawing a
plausible clock. When an act's data is missing the act is marked unavailable
with a reason, rather than filled in. This rule outranks every aesthetic
consideration in this document.

## No token or cost readout, anywhere in the player

The player shows **elapsed wall time and nothing else** as its measure of
effort. It does not show token counts, and it does not show dollars.

This is a deliberate omission, not an oversight, and it should not be "fixed":

- **Audiences don't read tokens.** A token count is not a unit anyone outside
  the field converts into meaning, so it costs comprehension and buys nothing.
  Elapsed time is legible to everyone in the room.
- **It discloses our own cost structure.** The funder audience frequently *is*
  an AI company. A per-phase token ledger exposes how ACE is run against
  subscription versus API pricing, which is not something a demo should be
  volunteering to that room.

Wall time is also the stronger argument on its own terms: "six hours and
fourteen minutes, unattended" lands against a human process measured in weeks,
without requiring the listener to price a token first.

Note that this constrains the player only. The Workbench's existing per-run cost
rollup chip is unchanged — worth remembering before screen-sharing *that*
surface to the same audience.

## Architecture

### The act model

An **act** is one self-contained beat of the demo, backed by real run data. The
player introspects a run, computes which acts that run can support, and renders
only those. A thin run gets a short demo; a rich run gets the full one.

Capability tiers:

| Tier | Availability | Source |
|---|---|---|
| **1** | Every run | `run_state.yaml` → phases, steps, statuses, judge verdicts, QA results, artifacts, decisions, timestamps |
| **2** | Runs with an ingested transcript | `IngestUpload.raw_jsonl_gz` → tool-level structure, subagent recursion |
| **3** | Runs that got that far | feedback ledger, a genuinely failed gate, live Connect/OCS/emulator targets, email threads |

This mirrors the pattern the structure view already uses: report
`schema_version` plus an `unavailable_reason` instead of breaking.

### Act catalogue

| Act | Tier | Source |
|---|---|---|
| **Time Machine** — phases light up, skills complete, artifacts appear, gates fire; dual clock (`T+04:12:33` / `0:47`) | 1 | `RunDetail.steps` |
| **Time ledger** — wall time per phase, drill to skill; elapsed run time against the human process it replaced | 1 | per-step timestamps in `run_state.yaml` |
| **Anatomy** — subagent tree, tool calls, parallel clusters | 2 | `apps/ingest/structure_aggregator.py` |
| **The gate that failed** — a real failing verdict and what it forced | 1 | `JudgeVerdict` / `QAResult` |
| **Decisions** — what ACE chose, and what a human overrode | 1 | `decisions` + `decision-overrides.yaml` |
| **The reviewer loop** — verbatim inbound feedback, stamped changes, UNROUTED rows | 3 | feedback ledger |
| **Touchables** — Connect opp, OCS chatbot, mobile emulator | 3 | live deep links |
| **Multi-player** — two people, one canopy session, seeded from one step | any | canopy |
| **Takeaway** — the public summary URL | 1 | `apps/opps/summary.py` |

Acts are declarative config plus a renderer component. Adding one is a registry
entry and a component, not a change to the player.

### Cuts

A **cut** is an ordered subset of acts plus a density setting. Three ship:

- **`funder`** — outcome first, then Time Machine as story, time ledger,
  reviewer loop, touchables, takeaway. Anatomy omitted.
- **`internal`** — promotes the failed gate and the decisions/override trail to
  the centre; this audience's real question is "what breaks and who catches it."
- **`technical`** — Anatomy at full density, the fork mechanic and the
  counterpart-tier model.

Cuts are data. The presenter can switch mid-demo when the room turns out to be
different than advertised.

### Backend

No new Django app — the player is opp/run-scoped and derived, so it lives in
`apps/opps/demo.py` and reuses `apps/opps/access.py` for membership checks and
the existing `OppSnapshot` cache.

One endpoint:

```
GET /api/w/<workspace_slug>/opps/<slug>/runs/<run_id>/demo
```

returning:

```json
{
  "schema_version": 1,
  "run": {"opp_slug", "run_id", "title", "started_at", "completed_at", "wall_seconds"},
  "timing_source": "measured" | "ordinal",
  "capabilities": {"timeline": true, "effort": false, "...": "..."},
  "acts": [{"id", "kind", "available", "unavailable_reason"}],
  "timeline": {"events": [...]}
}
```

`timing_source` is load-bearing: `ordinal` tells the frontend to render sequence
without a wall clock, per the honesty rule.

Timeline events are derived from steps and phases — `phase_start`, `step_start`,
`step_end` (carrying its artifacts and verdict), `decision` — each with its real
ISO timestamp.

### Frontend

`DemoPlayerPage.tsx` at `/w/<slug>/opps/<opp>/runs/<run>/demo`, with
`frontend/src/components/demo/`. A client-side clock drives playback from the
event list: no WebSocket, no server streaming, deterministic, and fully offline
after first load — which also makes it the lowest-risk surface in the demo.

Presenter controls: advance/back by act, pause, scrub, jump, speed. Keyboard
first.

## The per-step timestamp gap (must fix first)

`run_state.yaml` carries per-step `started_at` and `completed_at` (plugin
`agents/orchestrator-reference.md`, `phases.<phase>.steps.<skill>`), and
`StepManifest` has both fields. But the framework read path drops them:
`_snapshot_to_schema` in `canopy_agent_runs/drive/store.py` constructs `Step(...)`
with `key`, `ordinal`, `title`, `status` and `error` only, so
`map_step_snapshot`'s `_iso(step.started_at)` resolves to `None`.

The Time Machine's timeline depends on these. **Phase 1 threads per-step
timestamps through the framework `Step` read model**, and the player falls back
to `timing_source: "ordinal"` for runs that genuinely lack them.

## Run-complete email (designed here, built in phase 3)

No run-complete outbound email exists in the plugin today; what exists is
inbound triage plus counterpart emails (`llo-invite`, `llo-onboarding`,
`llo-uat`, `timeline-monitor`).

The gap is worth closing on its own merits: when a run finishes, ACE emails what
it produced, what it decided, what it is unsure about, and the public summary
link. It must be **re-triggerable against any already-complete run**, not only
fired at run close — that makes it usable for runs that already exist, and makes
the demo's opening beat reproducible.

Inbound is already built: `inbox-triage` routes a reply to its run, resolves the
sender's tier (`act` steers runs; `correspond` is derived from the routed run's
own state and can never mutate run state; unknown is read-only), and the
feedback ledger records it verbatim with the completeness property — an
unactioned item renders as UNROUTED rather than vanishing.

## Phasing

1. **Time Machine + act framework + capability gating**, including the per-step
   timestamp fix. Standalone-valuable as a run review surface.
2. **Time ledger, failed gate, decisions acts** — views over existing data.
3. **Run-complete email + reviewer-loop act.**
4. **Touchables, multi-player, takeaway** — staging and deep links.
5. **Cuts and presenter controls.**

Phases 1 and 2 are in scope now. Each ships as a PR into ace-web; phase 3 adds
one into the ACE plugin.

## Testing

- Backend: unit tests over `apps/opps/demo.py` capability computation and
  timeline derivation, including a run with no per-step timestamps (asserting
  `timing_source: "ordinal"`) and a run with no ingest upload (asserting the
  anatomy act is unavailable with a reason).
- Frontend: vitest over the act registry, cut filtering, and the playback clock.
- `scripts/qa/labs_probe.py` gains the demo route after phase 1 deploys.

## Open questions

- **Turn-on-inbound latency.** Whether a turn fires automatically on inbound
  mail fast enough to land inside a 20-minute demo. If not, the email act is
  presenter-triggered — honest, but a weaker closer. Verify before phase 3.
- **Tier 2 coverage.** How many existing runs have a linked `IngestUpload` with
  `raw_jsonl_gz`. This now affects only the Anatomy act (technical cut), so it
  no longer gates phase 2 — but it decides whether Anatomy is worth building in
  phase 4 or is effectively dead for most runs.
- **Fallbacks for live acts.** Touchables are the demo's only real failure
  surface. Recorded fallbacks should live inside the player rather than as
  separate files a presenter has to find under pressure. Scope in phase 4.
