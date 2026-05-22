# In-Workbench Decisions Editor + Edit-Aware Fork

Status: Draft — 2026-05-22

## Motivation

The current iteration loop on an ACE run is: review a completed run, decide some answer in `decisions.yaml` is wrong, hand-run `/ace:fork-run` from the CLI (with no way to carry edits), and either re-run interactively or use the `decisions-render` + `decisions-sync` gdoc round-trip. The gdoc round-trip has never been successfully used in practice.

The dominant usage pattern is iterating on Phase 1 (idea-to-design) until the PDD and work order are right, then proceeding through the rest of the pipeline — re-running and pruning prior runs as needed.

The goal of this spec is to collapse the loop into a direct in-app action: edit answers in the Phases view, see which artifacts will be regenerated, fork with one click. The current run stays immutable; iteration creates new runs.

## Background

What ships today:

- **`decisions.yaml`** (run root): canonical Q&A log. Rows carry `id`, `phase_tag`, `source` (skill name), `question`, `answer`, `status`, `options_considered`, `rationale`, `ordinal`.
- **`idea-to-pdd`** SKILL.md (step 4, line 137) is explicit: when re-running against a `decisions.yaml` containing rows with `status: overridden`, it uses the human's value verbatim and does NOT re-interview. Downstream phases honor overridden rows the same way.
- **`pdd-to-work-order`** reads `decisions.yaml` and produces `1-design/pdd-to-work-order.gdoc`, appending `wo-*` rows back into decisions.
- **`decisions-render`** writes `decisions.gdoc` at end of every phase (legacy round-trip).
- **`decisions-sync`** reads gdoc edits → writes back as `status: overridden` rows (legacy round-trip; unused in practice).
- **`/ace:fork-run`** + **`POST /api/opps/<slug>/runs/<from_run_id>/fork`**: copies pre-fork phase artifacts, trims `decisions.yaml` to `ordinal < fork_at`, marks downstream phases pending. Does NOT currently accept an edits payload.
- **`lib/artifact-manifest.ts`** in the ACE plugin: declares each skill's `products`. Already read at ace-web process start by `apps/system/parsers.py` for file → skill attribution.

What is missing:

- An in-app surface to edit answers.
- A path for the fork to carry edits into the new run's `decisions.yaml`.
- A human-facing summary of which artifacts the fork will regenerate.

What is **not** missing (verified during design):

- The propagation mechanism. `idea-to-pdd` and other phase skills already respect `status: overridden` on re-run. The skills regenerate their products (PDD, work order, etc.) from the new answers automatically. No inline LLM patching of prose is required.

## Folder layout (current)

```
<opp>/runs/<run-id>/
├── inputs-manifest.yaml             # orchestrator-emitted input index
├── inputs/                          # multi-doc evidence pack
├── decisions.yaml                   # Q&A log — what we edit
├── run_state.yaml                   # phase orchestration state
├── README.md
└── 1-design/
    ├── idea-to-pdd.md               # PDD output
    └── pdd-to-work-order.gdoc       # work order output
```

`idea.md` was retired as a default artifact on 2026-05-05 in favor of the `inputs-manifest.yaml` + `inputs/` model. It now only appears if the operator passes `--idea FILE` and is irrelevant to this feature.

## Design

### Surface — Phases view, per-phase Questions panels

The Phases view is the primary surface. Each phase block gets an expandable **"Questions (N)"** affordance. Expanding reveals the rows from `decisions.yaml` filtered by `phase_tag == <phase>`. Each row renders:

- Question text
- Current answer (editable; click to edit, like the video beat editor's drawer pattern)
- Source skill (small caption)
- Status badge (`default` / `applied` / `overridden`)
- Options considered (collapsed by default)
- Rationale (collapsed by default)

### Edit semantics — local buffer, batched save

Mirrors the video beat editor (`frontend/src/components/videos/`):

- Local buffer of `EditOp = { row_id, new_answer }`, coalesced by `row_id` (later edit to the same row overwrites earlier edit)
- Effective decisions computed in-memory via `applyOps(decisions, buffer)`
- Per-row revert affordance
- Sticky action bar at bottom of the Phases view appears when buffer is non-empty, showing "N pending edits" with two buttons: **Discard all** (clears buffer) and **Fork & re-run** (opens the save modal)

Read-only mode kicks in when `run_state.yaml.phases.<current>.status == "running"`; panels render with a tooltip ("Editing locked while phase is in progress").

### Single save path = Fork with edits

There is no "save edits to the current run" path. The current run stays immutable; iteration creates new runs. This:

- Matches the stated usage pattern ("delete prior runs once satisfied").
- Avoids needing an inline LLM patcher to rewrite prose docs — the existing Phase 1 re-synthesis from `decisions.yaml` does this correctly.
- Keeps the data model simple: a completed run's `decisions.yaml` is a stable historical artifact.

### Auto-fork-point

`fork_at_phase` defaults to **the lowest phase ordinal across all edited rows**, computed client-side from the buffer when the save modal opens. Overridable via a dropdown in the modal.

Example: edits touch one row tagged `phase_tag: design` (ordinal 1) and one tagged `phase_tag: ocs-setup` (ordinal 6). Default fork point is `design`. Forked run re-runs from Phase 1 onward; both edits land.

### Affected-docs resolution — manifest crosswalk

For each edited row:

```
row.source  →  artifact-manifest[source].products  →  paths
```

ace-web already loads the manifest at process start (`apps/system/parsers.py`). The crosswalk is an in-memory dictionary lookup. Union the resulting paths across all edited rows; that's the save modal's "will regenerate" list.

Backwards-compat: rows whose `source` is missing from the manifest render a fallback line ("this phase's outputs will be regenerated"). No per-row `affects:` metadata is added to `decisions.yaml` — the manifest is the source of truth.

A verification step at the start of implementation: confirm that each Phase 1 skill's `products` in the manifest are a clean "fork-rerun would regenerate" list (no orchestration noise, no transient logs). If noise exists, filter at read-time in `apps/opps/` rather than touching the manifest contract.

### Save modal copy

```
Fork run <NNN> with <N> answer change(s)

Your edits touch Phase <P>. The new run will re-run from there and regenerate:
  • 1-design/idea-to-pdd.md
  • 1-design/pdd-to-work-order.gdoc
  [...any other affected paths]

Fork point: [ Phase <P>: <phase-name> ▾ ]

[ Cancel ]  [ Fork & re-run ]
```

Flat list, no per-doc emphasis or callouts.

### Backend — extend the existing fork endpoint

```
POST /api/opps/<slug>/runs/<from_run_id>/fork
{
  "fork_at_phase": "design",
  "edits": [
    { "row_id": "pdd-target-population", "new_answer": "FLWs in rural Tanzania" },
    ...
  ]   // optional; absent → current fork behavior unchanged
}
```

Forker behavior (`apps/opps/opp_forker.py`):

1. Copy pre-fork phase artifacts (current behavior).
2. Copy run-root files: `decisions.yaml`, `inputs-manifest.yaml`, etc. (current behavior).
3. **`_rewrite_decisions_yaml` (extended)**:
   - Trim rows to `ordinal < fork_at_phase` (current behavior).
   - For each edit in the payload: find the matching row by `row_id`; update `answer` to `new_answer`; set `status: overridden`; preserve the prior value in `options_considered` (matching `decisions-sync`'s contract).
   - Write the merged `decisions.yaml` to the new run folder.
4. `_build_run_state_yaml`: phases ≥ `fork_at_phase` marked `pending` (current behavior).
5. Return new `run_id`.

Edits are applied atomically inside the fork transaction — one Drive write to the new run's `decisions.yaml`. No separate decisions-edit endpoint; the edit and the fork are one operation.

### Re-run trigger

After fork returns the new `run_id`, the new run needs to be kicked off. Two viable options, to be picked during implementation based on what the existing fork endpoint already does:

- (a) Extend the fork endpoint to auto-trigger the re-run via the same mechanism `/ace:run` uses today.
- (b) Frontend makes a second API call to whatever re-run endpoint exists.

This is an implementation detail, not a design decision — the user-visible behavior is the same either way (one click → new run is forked and starts re-running).

### Read pathway

The Questions panels read `decisions.yaml` through the existing opp-cache pipeline (`apps/opps/access.py` → Drive Changes API + `OppSnapshot` cache). No new read path; `decisions.yaml` is already part of the cached run snapshot.

### Frontend file organization

New under `frontend/src/components/decisions/`:

- `DecisionsPanel.tsx` — expandable panel embedded per-phase in the Phases view
- `DecisionRow.tsx` — single editable row, click-to-edit drawer
- `decisionsReducer.ts` — local-buffer reducer (same pattern as `editorReducer.ts`)
- `ForkWithEditsModal.tsx` — the save modal
- `useAffectedDocs.ts` — hook that crosswalks `row.source` → manifest `products`

### API types

Frontend `EditOp` type generated from the Ninja schema via the existing OpenAPI → TS regen pipeline. Backend schema added in `apps/opps/api.py` alongside the fork endpoint signature update.

## Data model

No new ORM tables. `decisions.yaml` schema unchanged. `status: overridden` and `options_considered` are existing fields already used by `decisions-sync`; we reuse the same contract.

Drive remains the source of truth (per `project_drive_is_source_of_truth`).

## Edge cases

- **Concurrent edits across two tabs**: include the run's `decisions.yaml` ETag from the cache in the fork request; forker checks `If-Match`; mismatch returns 409 with "decisions.yaml changed — reload."
- **Editing while phase is running**: panels render read-only; sticky action bar is hidden. Detected via `run_state.yaml.phases.<current>.status`.
- **Edited row's source not in manifest**: fallback "this phase's outputs will be regenerated" line in the modal; console warning for debugging.
- **Empty buffer at Save**: Save button disabled (cannot reach this state via normal UI).
- **Editing a row whose `status` is already `overridden`**: rewrite the answer; status stays `overridden`; original default preserved in `options_considered` from the prior override.
- **Row whose `source` is unknown (older runs predating the `source` field)**: row renders read-only with a tooltip ("Source unknown — fork this run and re-run to pick up edits"). Defer editing such rows; they're rare and pre-date the contract.

## Out of scope

- gdoc round-trip (`decisions-render` / `decisions-sync`) stays running at end-of-phase. Becomes a legacy archival path. Removing it is a separate cleanup not part of this spec.
- Inline LLM patching of prose docs (PDD, work-order) without a fork. Considered ("approach B") and dropped: fork-and-rerun via Phase 1's re-synthesis handles propagation correctly with no new skill.
- Search / filter / bulk-revert across decisions rows. Phase 1 ships with the straightforward list UI; revisit if scale demands it.
- Comments per question.
- Surfacing decisions in non-Phases surfaces (Workbench tab, opp summary page). Phases view is the primary surface; mirror into other surfaces in a follow-up if needed.
- A `POST /decisions/preview-affected` endpoint. Affected-docs resolution is a pure manifest lookup and is computed entirely client-side in v1. Add a server endpoint later only if the manifest needs to stop shipping to the frontend.

## Verification during implementation

1. Confirm each Phase 1 skill's `products` in `artifact-manifest.ts` is a clean "fork-rerun would regenerate" set (no orchestration noise). If noise, filter at read-time in `apps/opps/`.
2. Confirm `_rewrite_decisions_yaml` preserves `options_considered` correctly when status flips from `default` → `overridden` (matches `decisions-sync` behavior).
3. End-to-end smoke test: edit one PDD-affecting answer + one work-order-affecting answer in a real opp, fork, confirm the new run's `1-design/idea-to-pdd.md` and `1-design/pdd-to-work-order.gdoc` reflect the edited values.
4. Confirm the ETag plumbing for `decisions.yaml` is reachable from the cache pipeline (or accept last-write-wins for v1 if not).

## References

- `docs/specs/2026-05-15-video-beat-editor-react-port-design.md` — editor pattern source
- `docs/learnings/opp-cache-architecture.md` — read pathway
- `docs/learnings/drive-service-account.md` — Drive write pathway
- ACE plugin skills: `idea-to-pdd`, `pdd-to-work-order`, `decisions-render`, `decisions-sync`, `fork-run`
- `apps/opps/opp_forker.py` — existing fork mechanism
- `apps/system/parsers.py` — manifest reader

## Open question (non-blocking)

The current `/ace:fork-run` skill is the CLI surface for forking; this spec's backend extension makes the existing endpoint do more on a single call. The CLI skill could later grow an `--edits` flag to take advantage of the same endpoint, but that's optional and not part of this spec.
