# Learning: long-running chat turns die on ECS task replacement

**Date**: 2026-05-13
**Context**: `/ace:run` against a real opp produces multi-hour chat turns
with hundreds of tool calls. A labs deploy replaces the ECS task,
killing the `claude -p` subprocess and its enclosing asyncio turn task
mid-flight. The orchestrator typically has to be told to pick up where
it left off, which requires the operator to (a) notice the kill, (b)
clean up the now-stale `cli_session_id`, and (c) resend a continuation.
**Status**: Known fragility — flagged but not yet addressed.

## Observed failure mode

1. User kicks off `/ace:run leep-paint-collection` via the chat UI.
2. The orchestrator subagent runs for many minutes — Phase 1 PDD
   generation, then Phase 2 commcare-setup form building, etc.
3. Someone (the user, CI, an auto-deploy on `main` push) fires
   `deploy-ace-web-labs.yml`. ECS pulls the new image, starts a new
   task, drains old task connections, terminates the old container.
4. The old container's `claude -p` subprocess receives SIGTERM. The
   subprocess exits; the asyncio turn task driving it bubbles up a
   `CLIBackendError` ("subprocess died mid-turn"); the consumer
   evicts the `SessionProcess`, broadcasts `chat.stream_error`, and
   updates the assistant message status to `error`.
5. `Session.cli_session_id` may or may not be cleared depending on
   what state the turn was in when SIGTERM hit. If the CLI emitted
   a `SESSION_ID` event before dying, the id is captured on the
   Django row but the CLI's local store on the NEW container doesn't
   have it. The next `/ace:run` tries `--resume <stale-id>` and
   gets `error_during_execution` from the CLI. (Audit fix #13 in
   commit `b53f3dc` clears `cli_session_id` on this terminal error,
   so the second resend after a stall always spawns fresh.)

The 2026-05-13 Leep run hit this twice — once when a teammate
deployed at 19:49Z and once when this PR (commit `4039e0f`) deployed
at 22:09Z. Both times the recovery sequence was: send a fresh
`/ace:run`, see `error_during_execution`, send again, second send
spawns fresh and continues from current Drive state.

## Why the cli-backend "long-lived" path can't paper over this

Phase 1B's `SessionProcess` pool keeps one `claude -p` subprocess per
session alive across turns to amortise MCP-startup cost. That's a
process-local optimisation. ECS task replacement is a process kill —
the pool, the subprocess, and the asyncio turn task all go away
together. There's no "checkpoint mid-turn and migrate to the new
container" mechanism, and there can't be: the CLI subprocess's
internal state (LLM conversation context, in-flight tool execution,
file descriptors to staged credentials) isn't migrable.

## What works as resumption today

The Drive state (`pdd.md`, `state.yaml`, per-skill subfolders) is the
durable source of truth for orchestrator progress. A fresh
`/ace:run <opp-slug>` against a partially-complete run folder
correctly reads `state.yaml` and continues from `current_phase`/
`current_step`. The cost is one rebooted CLI + MCP startup
(~5–30s) plus the orchestrator re-reading the Drive state.

## Improvements considered but not done

- **Drain ECS deploys**: ECS supports configurable deregistration
  delay. Today it's the default (~30s). Bumping it to 30 min would
  let in-flight turns finish, but most turns are longer than that.
- **Pre-deploy quiesce**: workflow could call
  `/api/sessions/active-runs` to check for in-flight turns and
  pause/refuse to deploy. Not implemented; would slow down deploys
  and isn't always desirable.
- **In-process checkpointing**: ace-orchestrator's per-skill
  step boundaries are natural checkpoint points. The plugin
  already writes `state.yaml` updates at those boundaries. The
  improvement would be on the ace-web side: notice SIGTERM,
  finish-the-current-tool-call-and-stop semantics, persist a
  "resume here" marker, and have the resume flow detect and use
  it. Significant work.
- **Auto-resume after stall**: a background job could detect
  sessions with `last_message_at` older than N minutes AND
  `cli_session_id` null AND a `current_phase` that isn't terminal,
  and automatically POST a fresh `/ace:run` to resume. Brittle —
  doesn't know whether the user actually wants to resume; could
  loop forever on a genuinely broken orchestrator state.

## Diagnostics that landed in this PR

- `GET /api/sessions/<slug>/turn-state` — answers "is a turn
  currently driving the backend on this worker". Lets a script
  decide to stop waiting without resorting to wall-clock guesses.
  See `apps/sessions/views.py::session_turn_state`.
- `_TURN_BG_TASKS` + `_TURN_TASKS_BY_SLUG` in `consumers.py` —
  module-level strong refs so the turn task survives WS disconnect
  (the local-vs-remote variant of this same death). See
  `apps/sessions/tests/test_consumers.py::test_turn_task_strong_referenced_at_module_level`.
- Audit fix #13 in `cli_backend.py` — clears `cli_session_id` on
  terminal ERROR events from the seeded-history fallback path, so
  the user only sees one error before resumption works.

## How to recover after a deploy kills a long-running turn

```bash
# 1. Check current state
TOKEN=$(grep ACE_E2E_AUTH_TOKEN .env | cut -d= -f2-)
curl -s -X POST https://labs.connect.dimagi.com/ace/auth/e2e-login/ \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$YOUR_EMAIL\",\"token\":\"$TOKEN\"}" -c cookies
curl -s -b cookies -H 'X-Workspace: dimagi-team' \
  https://labs.connect.dimagi.com/ace/api/sessions/<slug>/turn-state \
  | jq .data
# Expect running=false, cli=null. last_message_at tells you when it died.

# 2. Send fresh /ace:run via the watch script.
ACE_E2E_TOKEN="$TOKEN" ACE_USER_EMAIL="$YOUR_EMAIL" \
  uv run python scripts/ace_send_and_watch.py <slug> "/ace:run <opp-slug>"
# Expect: [stream_error] error_during_execution within ~12s — that's the
# stale --resume failing and the audit fix clearing cli_session_id.

# 3. Send again. The second attempt spawns fresh and resumes from Drive state.
ACE_E2E_TOKEN="$TOKEN" ACE_USER_EMAIL="$YOUR_EMAIL" \
  uv run python scripts/ace_send_and_watch.py <slug> "/ace:run <opp-slug>"
# Expect: [stream_start] then a stream of tool_use/tool_result events
# as the orchestrator reads state.yaml and continues from current_step.
```
