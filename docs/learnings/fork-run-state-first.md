# Fork writes `run_state.yaml` first, and its progress must match `ForkProgress`

**Context:** ace-web#734. A phase-level fork of
`hh-poverty-targeting/20260824-1404` copied all six phase folders and
`decisions.yaml`, then stopped — no `run_state.yaml`, no
`inputs-manifest.yaml`, no `README.md`. Meanwhile
`GET .../fork/status` answered `{"status": "unknown"}` on seven
consecutive polls across five minutes while folders were visibly
landing in Drive. The operator recovered by hand-shaping a
`run_state.yaml` from the source run.

Three separate defects, worth remembering separately.

## 1. `run_state.yaml` is what makes a folder a run — write it first

ACE's resume path derives execution order from
`run_state.yaml.phases.<phase>.status`. Without that file there is
nothing to resume: `/ace:run <opp>/<run-id>` has no state to read, and
the expensive part (the Drive copy) is wasted.

`fork_opp` used to synthesize and upload it **after** the whole bulk
copy. Any stall in the tail — a hung Drive call, an ECS task
replacement mid-fork (see `long-running-turns-vs-deploys.md`) — left an
unrunnable pile of copied artifacts.

The state file depends on *nothing* the copy produces (opp slug, new
run-id, owner, fork point, source run name, timestamp). So it goes
first, immediately after `drive.create_folder`. The same stall now
leaves a **resumable-but-incomplete** run.

**General rule for this codebase:** when a write sequence has one small
file that confers identity/resumability and a large body that doesn't,
the small one goes first. Ordering is the cheapest crash-safety there
is when there's no transaction to lean on — and Drive gives us none.

## 2. A strict response model needs a test that runs producer → consumer

`ForkProgress` is a `StrictModel` (`extra="forbid"`). The forker emitted
`{"status", "copied", "total", "current", "opp_slug"}`; the model
declares `{"status", "progress", "files_total", "files_copied",
"error", "new_slug", "new_run_id"}`. **Every payload the forker ever
emitted failed validation.** The endpoint could not have reported
anything but `unknown`, on any fork, ever.

It shipped because the only test of the endpoint
(`test_fork_status_happy_path`) monkeypatches `cache.get` to return a
**hand-written** payload in the model's shape — a payload no producer
emits. Writer and reader were each tested against a fiction of the
other. The frontend, separately, hand-rolled a TS union matching the
*forker's* shape and swallowed poll failures (`/* poll failures are
non-fatal */`), so the dead progress bar was silent there too.

Fixes, all three needed:

* the forker emits through one `_Progress.emit()` that builds exactly
  the schema's field names;
* `test_fork_run_state_first.py` runs the real forker with the real
  cache-writing callback and then reads the real endpoint;
* `frontend/src/api/opps.ts` takes `ForkProgress` from `generated.ts`
  instead of hand-rolling it, so a schema change breaks `tsc -b`.

## 3. `unknown` during an active fork is worse than no endpoint

A caller whose POST hangs has exactly one way to learn what run was
created. If the poll says `unknown`, the caller reasonably concludes
nothing started and **retries the POST — minting a second partial
fork**. So:

* `new_run_id` is reported from the moment the run folder is minted,
  not just in the terminal `done` payload;
* a Drive failure emits `status: error` with the message and the
  run-id it left behind, before re-raising;
* progress is written under both the `(slug, source_run_id)` key and a
  per-opp `_latest` alias, because a poll that omits `?source_run_id=`
  reads the alias and would otherwise never see a fork started with one.

## 4. The POST is blocking; say so

`POST .../fork` holds the connection for the whole copy (one
`copy_file` per artifact at ~150 ms). The ACE plugin's `fork-run` skill
documents forks as async-with-a-poll. The poll now works, and the
endpoint's OpenAPI description states plainly that the POST blocks and
that a timed-out caller must poll rather than retry. If the blocking
POST ever becomes a real ceiling, the async precedent is
`apps/mobile/`'s `run-recipe` (202 + `job_id` + worker thread), but
that's an API break for both the SPA dialog and the plugin skill.

## 5. A run folder with no `run_state.yaml` gets a 404, not a 200

`build_summary_payload` used to fall back to `state = {}` and build a
payload out of `opp.yaml` alone, so the public run summary answered
**200 with an empty body** for #734's broken fork — making "the fork
failed" and "the run has not started" indistinguishable from the API.
It now returns `None`, which the endpoint maps to 404.

This does **not** contradict "pre-run is a valid state" (PR #390): that
rule is about an *opp* whose `runs/` folder is empty, and the Workbench
still renders its empty shell. This is about a *named run* that isn't
one.
