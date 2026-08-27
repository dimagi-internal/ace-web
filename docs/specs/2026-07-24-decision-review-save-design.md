# Decision review: honest staging + durable save

**Status:** design approved 2026-07-24, implementation in progress
**Author:** jjackson + Claude
**Surface:** `apps/opps/` (Phases tab → Decisions panel)

## Problem

We shared a full run (`hh-poverty-targeting` / `20260722-1341`) with an outside
domain expert and asked her to review the decisions log alongside the PDD. Three
things break that workflow.

**1. The row header lies after you pick an option.** `DecisionsPanel.tsx`
computes the right-hand status chip from `decision.status` — the *committed
server* value — while the option pills highlight from local draft state. Pick a
different pill and the pill turns green while the chip still reads `AI-DEFAULT`
and the summary still reads `→ <ai default>`. The reviewer's own choice is not
reflected in the row she is looking at.

**2. Save is below the fold.** The expanded row stacks `Pick option` → override
reason textarea → new-option input → **Save**. On a laptop viewport the Save
button is off-screen, so the affordance reads as "there is no way to save."

**3. There is no durable save at all.** Per-row Save writes only to the Redis
shared buffer (`decisions:edits:{slug}:{run_id}`, 24h TTL). The single path that
makes an edit durable is **Fork & re-run**, which immediately creates a new run.
A reviewer therefore must either trigger a run she has no business triggering,
or watch a day of review work expire overnight.

## Scope

**In scope**

1. Stage-on-pick, with a row header that reflects the staged answer.
2. **Save to Drive** — persist the accumulated overrides to
   `ACE/<opp>/inputs/decision-overrides.yaml` without triggering any run.
3. Read-side overlay so saved overrides keep rendering after the buffer clears.

**Explicitly deferred** — decide from real evidence once the expert's edits land
(expected within days):

- How the ACE plugin *consumes* `inputs/decision-overrides.yaml` on the next
  run. Writing the file does not make it binding; the orchestrator must be
  taught to seed a new run's `decisions.yaml` from it. That is a PR in
  `dimagi-internal/ace`, not this repo.
- How PDD edits carry into the next run. The PDD is a run *product*
  (`runs/<run-id>/1-design/idea-to-pdd.md`), not an input, so there is no
  existing convention for round-tripping reviewed prose into a fresh run.

## Why `inputs/`, not the run folder

`ACE/<opp>/inputs/` is the opp-level evidence pack. `/ace:run <opp>` freezes
`runs/<run-id>/inputs-manifest.yaml` as a pointer-set over it, and a **fresh run
reads `inputs/` and does not read any prior run's `decisions.yaml`.** Overrides
parked in a run folder are therefore invisible to the next run. Overrides in
`inputs/` accumulate at the opp level and survive across runs, which is the
stated intent: review once, apply to whatever runs next.

This is a different mechanism from forking. `opp_forker._rewrite_decisions_yaml`
rewrites `decisions.yaml` *inside a newly created run folder* and starts that
run. Both stay; they answer different questions.

## Part 1 — Stage-on-pick

Clicking an option pill writes the edit to the shared buffer immediately (local
reducer + `decision.edit` over the WebSocket), the way a radio button behaves.
The per-row **Save** button is removed; the override-reason textarea saves on
blur.

Row header derives from the staged value:

- `→ <value>` reads the pending edit when present, else the committed override,
  else the AI default. (Already correct for buffer edits; the bug is that a
  local draft never reaches the buffer until Save.)
- The status chip becomes a three-state derivation rather than a passthrough of
  `decision.status`:
  - `AI-DEFAULT` (emerald) — effective value equals `ai_default`, no reasoning.
  - `OVERRIDDEN` (sky) — committed or saved override.
  - `OVERRIDDEN · pending` (violet) — staged in the buffer, not yet saved to
    Drive.

The small `ai` marker on the AI's original pill stays. It labels which option
the AI picked, which remains true and useful after a human overrides it.

**Accidental-click risk** is covered by the existing per-row Revert plus
`Discard all`; nothing is durable until the explicit Save to Drive.

## Part 2 — Save to Drive

### Endpoint

```
POST /api/w/{workspace_slug}/opps/{slug}/decision-overrides
body: {"source_run_id": "<run-id>"}
→ 200 {"file_id": ..., "override_count": N, "overrides": [...]}
```

The request body carries no edits. The server reads the **Redis buffer** as the
authoritative set, so one reviewer's stale browser tab cannot clobber another's
concurrent edits. It joins each buffered `row_id` against the run's
`decisions.yaml` (read from Drive) to recover `phase`, `question`, and
`ai_default`, which the buffer does not carry.

### File format

`ACE/<opp>/inputs/decision-overrides.yaml`:

```yaml
schema_version: 1
kind: decision-overrides
opp: hh-poverty-targeting
updated_at: 2026-07-24T15:02:11Z
overrides:
  - id: archetype-selection
    phase: idea-to-design
    question: Which delivery archetype best fits the intervention?
    ai_default: atomic-visit
    override: focus-group
    override_reasoning: >-
      Village-level enrollment means one facilitator meets 8-12 households
      together; atomic-visit would triple the FLW day count.
    decided_by: expert@partner.org
    decided_at: 2026-07-24T14:58:02Z
    source_run_id: 20260722-1341
```

Every row carries its own `source_run_id` — successive review sessions against
different runs merge into one file, and provenance must survive per row rather
than per file. `question` and `ai_default` are denormalized deliberately: a year
later the file has to explain itself without resolving a run folder that may be
gone.

### Merge semantics

Read the existing file if present, merge by `id`, last write wins. A row whose
override equals `ai_default` with no reasoning is **dropped** from the file
entirely — that is a revert, and a revert should leave no trace beyond absence.

On success the Redis buffer is cleared. Part 3 keeps the UI honest afterward.

## Part 3 — Read-side overlay

Without this, clearing the buffer makes saved overrides visually revert to
AI-DEFAULT, because the UI renders from the run's `decisions.yaml`, which never
learns about `inputs/`.

The opp snapshot gains `saved_overrides` (`{row_id: {override, reasoning,
decided_by, decided_at}}`) alongside the existing `pending_edits` injection at
`apps/opps/api.py:262`.

It must be registered in `apps/opps/freshness_overlays.py`, not stored as a
plain cached field. Finding the file requires listing `inputs/`, and per
`docs/learnings/drive-changes-api-parent-folder-blind-spot.md` the Drive Changes
API does not reliably report a parent folder as modified when a child is added
— so a cached listing would never invalidate on first creation. The overlay
costs one Drive call per snapshot request, which is what overlays cost, and it
must never clobber the cached value on a Drive blip.

Frontend precedence per row: pending buffer edit > saved override > committed
run override > AI default.

## Testing

- `apps/opps/tests/test_decision_overrides.py` — merge by id, revert drops the
  row, cumulative merge across two runs, denormalized fields captured, empty
  buffer is a no-op rather than an empty-file write.
- Overlay test against `fake_drive.py`: missing `inputs/` folder, missing file,
  malformed YAML all degrade to "no saved overrides" rather than 500.
- `DecisionsPanel.test.tsx` — pill click flips chip to pending and updates
  `→ value`; reason blur stages; revert restores AI-DEFAULT.

## Risks

- **The file is inert until the plugin reads it.** Deliberate and deferred, but
  it means a reviewer can save overrides that the next run silently ignores. The
  UI must not imply otherwise: the button says "Save to Drive," not "Apply to
  next run."
- One extra Drive call per opp-snapshot request. Measured against the ~46-55×
  cache speedup this surface already has, acceptable.
