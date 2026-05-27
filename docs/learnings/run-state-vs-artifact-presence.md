# Learning: `run_state.yaml` is the source of truth for step status, not artifact-file presence

**Date**: 2026-05-27
**Context**: `apps/opps/sync.py:_build_steps` synthesizes the per-step status rows the workbench detail view renders (`pending` / `running` / `complete` / `skipped` / `error` / `qa-failed`). For years it derived that status from whether the artifact files declared by `lib/artifact-manifest.ts` existed in the run folder. PR #575 (2026-05-27) switched the primary source to `phases.<phase>.steps.<skill>.status` in the parsed `run_state.yaml`, with artifact-presence retained as a fallback for legacy runs.
**Status**: Active. Single load-bearing rule for the workbench live-progress feel.

## The gotcha in one sentence

If you want step status to update during a live run, read it from `run_state.yaml` content (one file_id, Changes API reliably reports edits), not from artifact-file presence in subfolders (new child files, Changes API blind spot — see [drive-changes-api-parent-folder-blind-spot](drive-changes-api-parent-folder-blind-spot.md)).

## Why it bites

Watching `/ace:run bednet-spot-check` on labs end-to-end (90-min full lifecycle), the opp-detail API stayed pinned at 6/43 steps complete for over an hour while the agent was actually deep into Phase 8 (writing `solicitation-management/llo-invite: reason="no-op — smoke opp, no Preferred LLOs in PDD"` into the run_state.yaml in real time). The agent was making progress. The cache was eventually-consistent. The disconnect was: `_build_steps` only looked at `<run>/<phase>/<skill>/` folder listings to decide step status, and per-phase artifact listings are intentionally NOT in `freshness_overlays.SNAPSHOT_OVERLAYS` (an overlay there would have paid 10-30 Drive list calls on every cache hit; see the comment block in that module for the rationale).

The agent dutifully patched `run_state.yaml` at every step transition. The Drive Changes API dutifully reported each patch. The OppSnapshot cache dutifully invalidated. The rebuild dutifully re-read `run_state.yaml` — but `_build_steps` ignored what it said and went back to listing folders, which the underlying listing cache was happy to serve stale.

Symptom for the user: opp-detail page that updates twice per `/ace:run` (once on cold load, once when the user reloads after lunch). Looks broken when it isn't. Polling makes it worse — every poll is wasted because the cache doesn't refresh anything actually useful.

## Why `run_state.yaml` is the right source

1. **The plugin writes it deliberately.** Every step transition is an `mcp__plugin_ace_ace-gdrive__update_yaml_file` call patching `phases.<phase>.steps.<skill>.status` to `running`, `done`, `skipped`, `no-op`, `failed`, etc. The agent's intent is explicit.

2. **Drive Changes API reports edits to existing files reliably.** The blind spot is for new child files added to folders ([learning](drive-changes-api-parent-folder-blind-spot.md)). `run_state.yaml` is a single existing file_id — every patch is a Changes event → snapshot cache invalidates → next request rebuilds with fresh data.

3. **It carries semantic info artifact-presence cannot.**
   - `running` — mid-step state (no artifact yet, but step is alive)
   - `skipped` / `no-op` — smoke-opp's `llo-invite` correctly surfaces as skipped instead of being flattened to "pending" forever
   - `pending` on a forked run with carried-over artifacts (the agent says "I haven't run this yet"; artifacts on disk are misleading evidence)
   - `error` on failed steps (some failure modes leave partial artifacts on disk)

4. **Cheaper.** One `drive_read_file` per snapshot rebuild vs ~10-30 `drive_list_folder` + verdict-file reads.

5. **Multi-viewer falls out for free.** Shared `OppSnapshot` in Redis invalidates once per agent write, every viewer hits the same fresh cache. **O(1) Drive cost per viewer**, scales with active runs not viewer count.

## Why artifact-presence stays as a fallback, not deleted

- **Legacy runs** that pre-date the decisions-log era (pre-PR #511 in the plugin) may not populate `phases.<phase>.steps.<skill>.status` for every step.
- **Unit tests** that exercise `_build_steps` directly without constructing a fake run_state shouldn't break.
- **Future schema drift.** If the plugin renames `status:` to something else and we don't notice for a release, artifact-presence keeps the workbench broadly correct (just laggy) instead of showing everything as pending.

The `_RUN_STATE_TO_CANONICAL` map in `apps/opps/sync.py` accepts unknown status strings → falls through to the artifact-presence path. Defensive against plugin schema changes we haven't shipped a reader for yet.

## Why we don't surface `broken` when run_state says complete but no artifacts

Considered and rejected. Three failure modes look identical from the cache's vantage point:

1. **Legitimate no-op step.** Smoke-opp `llo-invite` with no Preferred LLOs intentionally has no artifact. Plugin writes `status: skipped` or `status: done` with a `reason:` field. Correct outcome: surface as `skipped` / `complete`.
2. **Drive write lag.** Agent flipped status to `done` 200ms ago, the artifact upload is still in flight. Surfacing `broken` for ~1 second creates UI flicker.
3. **Real plugin bug** — agent claims `done`, never wrote the artifact. Rare. The `verify_phase_artifacts` MCP atom (added to the orchestrator's phase-closeout fence in PR #517 / #519 of the plugin) catches this at the agent's own boundary.

A `log.debug` in `_build_steps` logs when run_state declares `complete` with no load-bearing artifacts. Sufficient signal for forensics; no UI noise.

## Sweep — who else reads artifact-presence?

PR #575's sweep found `_build_steps` was the only caller making the artifact-presence-as-truth mistake. The siblings are correct:

- **`RunSummary` / `list_opp_runs`** — reads `run_state.yaml` via `_derive_phase_progress(state, ...)`. ✓
- **`OppCard` / `load_opp_card`** — reads `run_state.yaml` directly; docstring is explicit ("`last_activity_at` is run_state.yaml's Drive modifiedTime — the plugin updates run_state.yaml on every step transition, so this is the best cheap proxy for 'when did anything happen here'"). ✓
- **`apps/activity/workspace_activity.py`** — explicit "NO inferred liveness claims (no `is_running`, no `is_alive`)"; reads `current_phase` / `last_activity_at` from the OppCard which sources from `run_state.yaml`. ✓
- **`_load_opp_eval_summary`** — reads actual YAML content of verdict files, not just presence. ✓

If you add a new field that depends on "did skill X run," reach for the run_state map first, not the artifact list.

## Related

- [drive-changes-api-parent-folder-blind-spot](drive-changes-api-parent-folder-blind-spot.md) — the Drive Changes API quirk that makes artifact-folder-listings unreliable as a freshness signal.
- [opp-cache-architecture](opp-cache-architecture.md) — the cache layer this fix relies on for the multi-viewer scaling property.
- `apps/opps/sync.py:_extract_step_statuses` — the helper that pulls per-skill status strings out of `run_state.yaml`, handling all three phase shapes (`steps:` wrapper, bare skill→string, mixed) that the existing `_derive_phase_progress` already tolerates.
- `apps/opps/sync.py:_RUN_STATE_TO_CANONICAL` — the normalization map (plugin's literal `done` → canonical `complete`, etc.).
