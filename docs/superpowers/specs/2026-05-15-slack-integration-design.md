# Slack Integration — Design Doc

**Status:** Draft · 2026-05-15
**Author:** jjackson + Claude (brainstorming session)
**Scope:** ace-web Slack integration v1
**Spec location:** `docs/superpowers/specs/2026-05-15-slack-integration-design.md`

## Goal

Let Dimagi humans trigger, monitor, and branch ACE runs without leaving Slack.
The Slack surface mirrors the ace-web Workbench's Phase view: a parent status
card per run + one thread message per phase that mutates as skills complete.

Slack is a trigger surface and a mirror — never the source of truth. Drive
remains authoritative; ace-web computes the snapshot; Slack reflects the
current snapshot.

## Non-goals (v1)

- **Gate approve/reject** — gates aren't really the operating model anymore.
  Fork-from-phase replaces this verb.
- **Native Slack fork modal** — fork action deep-links to the existing
  web `ForkOppDialog`. Revisit only if friction is observed.
- **Token-by-token streaming** — per-skill updates inside the phase tile
  are the right cadence; raw LLM chars are too noisy for Slack.
- **Multi-tenant Slack install** — one Slack workspace ↔ one ace
  Workspace, hardcoded to `dimagi-team` at install.
- **Multi-channel routing per opp** — runs land in the channel where the
  command was triggered. No admin-configurable channel override.

## User-visible verbs (v1)

| Command                              | What it does                                                                                          |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `/ace run <pdd-link-or-opp-slug>`    | Confirmation modal, then kicks off `/ace:run` on an existing opp or a PDD in Drive.                  |
| `/ace new`                           | Modal with name + idea textarea; creates a new opp folder and starts from `idea-to-design`.          |
| `/ace status [<slug>]`               | Ephemeral message with current parent-card snapshot. Defaults to the user's most recent active run. |
| `/ace list`                          | Ephemeral list of the 5 most recent active runs the user has triggered.                              |
| `/ace link`                          | DM-sends an OAuth link URL to link the Slack identity to an ace-web user.                            |
| `/ace help`                          | Ephemeral usage.                                                                                      |
| `🍴 Fork from here…` button         | Deep-link to `/ace/w/<workspace>/opps/<slug>?fork=<phase>` → existing `ForkOppDialog`.               |

## Interaction model

**Hybrid card + thread.** Parent message is a live status card; thread is a
phase-by-phase mirror of the Workbench's `PhaseView`.

### Parent card

Single Slack message per run, posted into the channel where the command was
issued. Mirrors `WorkbenchHeader` shape:

- Opp display name + run id (e.g., `rural-health-tb-screening · run-007`)
- Triggerer (`@jjackson`), elapsed time
- Current phase indicator: `Phase 3/10 · running create-payment-units`
- Links: `opp in ace-web ↗`, `Drive folder ↗`

Updates via `chat.update` whenever the active phase or current skill changes.
2s debounce per run.

### Phase thread

One thread message per phase, posted the first time the phase appears in the
snapshot. Block Kit shape mirrors `PhaseTile` from `frontend/src/components/views/PhaseView.tsx`:

- Section: `Phase N · <agent>` (eyebrow) + `<display_name>` (title)
- Context: `X/Y done` · `mean N/100` · qa-failed / open-decisions badges
- Image-as-text: progress bar rendered as a unicode block bar (e.g. `▓▓▓▓░░░░░░ 40%`)
- Currently-running line (only while phase is running): `Currently: <skill_name> · last update Ns ago`
- Actions: `View phase ↗` (deep-link); `🍴 Fork from here…` (enabled once any
  skill in the phase has completed)

Each phase message `chat.update`s as skills complete inside that phase. When
the phase reaches a terminal status (all steps `complete` or `qa-failed` with
no more pending), the message freezes. The Fork button remains live forever —
its payload is `(slug, phase)`, so it's stateless.

### Channel etiquette

- Slash command issuer gets an ephemeral ack within 3s ("Got it — kicking off `<slug>`…").
- Real parent message is then `chat.postMessage`d ~1s later.
- All progress is in-thread; the channel only sees the (mutating) parent card.

## Architecture

```
Slack workspace
   │  POST /ace/api/slack/{events,commands,interactions}
   ▼
apps/slack/views.py            ← signing-secret verify, 3s ack
   │
apps/slack/handlers.py         ← slash + interactive dispatch
   │
   ├─ run_pdd() / run_new()    → creates Session w/ opp_slug
   │                              → existing turn_driver spawns
   │                                 claude -p /ace:run …
   │
   └─ status() / list() / link() / fork_redirect()

During the run:
   subprocess writes to Drive
       │
   apps/sessions/turn_driver  (existing)
       │  detects Drive-touching tool_use
   apps/sessions/opp_broadcast (existing)
       │  group_send "opp.updated"
   opp.<slug>.<run_id> channel group
       ├─→ OppConsumer    (existing — browser)
       └─→ SlackOppConsumer (NEW)
              │
              ├─ refetch OppSnapshot
              ├─ diff vs SlackRunThread.phase_messages[*].last_state_hash
              ├─ chat.update / chat.postMessage per changed phase
              └─ chat.update parent card if active-phase or skill changed
```

**The key reuse:** `opp_broadcast` already emits the right signal for the
browser. Slack adds a second consumer on the same group. The subprocess
doesn't know Slack exists.

## Data model

New Django app `apps/slack/`. Three tables.

### `SlackInstallation`

One row per Slack workspace install (one in v1).

| Field                | Type          | Notes                                                  |
| -------------------- | ------------- | ------------------------------------------------------ |
| `id`                 | UUID          | PK                                                     |
| `slack_team_id`      | varchar       | Unique. Slack's `T…` id.                                |
| `slack_team_name`    | varchar       | Display.                                                |
| `bot_user_id`        | varchar       | Slack's `U…` id for the bot.                            |
| `bot_token`          | encrypted text | Bot OAuth token. Stored encrypted (Django Fernet).     |
| `ace_workspace`      | FK Workspace  | Bound at install time. v1: `dimagi-team`.              |
| `installed_at`       | timestamp     |                                                         |
| `installed_by_user`  | FK User       | Whoever did the OAuth dance.                            |

### `SlackUserLink`

Maps Slack users → ace-web users.

| Field             | Type          | Notes                                              |
| ----------------- | ------------- | -------------------------------------------------- |
| `id`              | UUID          | PK                                                  |
| `installation`    | FK            |                                                     |
| `slack_user_id`   | varchar       | Slack's `U…` id.                                    |
| `ace_user`        | FK User       |                                                     |
| `slack_email`     | varchar       | For display.                                        |
| `slack_real_name` | varchar       | For display.                                        |
| `linked_at`       | timestamp     |                                                     |
| `unlinked_at`     | timestamp?    | Soft-delete; old threads keep working.              |

Unique together: `(installation, slack_user_id)`.

### `SlackRunThread`

One row per Slack-triggered run.

| Field                | Type      | Notes                                                                                                            |
| -------------------- | --------- | ---------------------------------------------------------------------------------------------------------------- |
| `id`                 | UUID      | PK                                                                                                                |
| `installation`       | FK        |                                                                                                                   |
| `channel_id`         | varchar   | Where the command was issued.                                                                                     |
| `parent_ts`          | varchar   | `chat.postMessage` `ts` of the parent card.                                                                       |
| `opp_slug`           | varchar   |                                                                                                                   |
| `run_id`             | varchar   | e.g. `run-007`.                                                                                                   |
| `ace_user`           | FK User   | Triggerer.                                                                                                        |
| `triggered_at`       | timestamp |                                                                                                                   |
| `phase_messages`     | JSONB     | `{phase_name: {ts, last_state_hash, frozen_at?}}`.                                                              |
| `parent_state_hash`  | varchar   | Last-pushed parent card state.                                                                                    |
| `broken_at`          | timestamp?| Set if `chat.update` returns `channel_not_found` / `is_archived`. Stops further updates.                          |

Unique: `(opp_slug, run_id)` — at most one Slack thread per run.

## Auth

### Slack app install

Standard Slack OAuth v2. Admin (a Dimagi engineer) does this once. Stored in
`SlackInstallation`. Bot token is encrypted at rest with the Fernet key
already in `ACE_SECRET_KEY` derivation (or a dedicated `SLACK_TOKEN_FERNET_KEY`).

**Bot scopes:**

- `commands` — receive slash commands
- `chat:write`, `chat:write.public` — post / update messages
- `users:read`, `users:read.email` — display names + email for `SlackUserLink`

### Per-user identity link

First time a Slack user runs any command without a `SlackUserLink`:

1. Bot DMs them: "Link your ace-web account → `<link>`".
2. Link goes to `/ace/auth/slack/link/?slack_user_id=<id>&nonce=<short-lived>`.
3. Route requires existing Connect OAuth login (existing flow). On success,
   create `SlackUserLink(installation, slack_user_id, request.user, …)`.
4. The original command was cached keyed by `nonce` (Redis, TTL 10 min). On
   successful link, replay it — bot posts the parent card as if the command
   just succeeded.

Subsequent commands look up `SlackUserLink` and attribute the run to that
`ace_user`.

`/ace link` re-issues the link DM, used if a user wants to re-link or check
their status.

### Signing-secret verification

`SLACK_SIGNING_SECRET` env var, loaded from AWS Secrets Manager. Every
inbound request gets verified via Slack's standard HMAC-SHA256 timestamp +
body scheme. Rejected requests get 401.

## Dispatch — `SlackOppConsumer`

`apps/slack/consumer.py`. A Channels async consumer (worker-style — not bound
to a WebSocket) that lives in the ASGI process and joins the same
`opp.<slug>.<run_id>` groups the browser's `OppConsumer` uses.

### Lifecycle

- **On startup** (`apps/slack/apps.py:ready()`): query active
  `SlackRunThread` rows (no `broken_at`, run is `active`), spawn a singleton
  consumer task, `group_add` each one. Also run an initial sweep (see below).
- **On new Slack-triggered run**: handler creates the `SlackRunThread` row
  and `group_add`s the consumer to `opp.<slug>.<run_id>`.
- **On `opp.updated` event**:

  1. Look up `SlackRunThread` by `(slug, run_id)`. If none, ignore.
  2. If `broken_at` is set, ignore.
  3. Refetch `OppSnapshot` (existing cache — hot in <10ms).
  4. For each phase in snapshot:
     - Compute `state_hash = sha256({steps_complete, steps_total, mean_score, qa_failed_count, open_decision_count, current_skill, status})`.
     - If phase has no entry in `phase_messages`: render block kit, `chat.postMessage`, store `ts` + `state_hash`.
     - If hash differs from stored: render block kit, `chat.update`, update hash.
     - If phase is in terminal state and not yet `frozen_at`: set `frozen_at` (Fork button stays enabled).
  5. Compute parent-card `state_hash` from `(active_phase, current_skill, elapsed_seconds_bucket=floor(t/60))`. If changed, `chat.update` the parent.
  6. Persist `SlackRunThread`.

### Debounce

Per-`SlackRunThread` 2s debounce. Implementation: `asyncio.Event` + sleep
loop. If multiple `opp.updated` events arrive within 2s, coalesce to one
dispatch tick.

### Replay / resilience

- **Stateless w.r.t. events**: missed events are auto-corrected on the next
  event because we always recompute from the live snapshot.
- **Worker / task replacement**: ECS task replacement kills `claude -p`
  (existing `long-running-turns-vs-deploys` learning); the Slack thread keeps
  mutating once the run resumes. On boot, the startup sweep iterates active
  `SlackRunThread`s and runs one dispatch tick each, catching anything that
  changed during the gap.
- **Sweep cadence**: every 60s, sweep all active threads as a defensive
  belt-and-suspenders. Cheap (~one snapshot fetch per active run).
- **Multi-process / multi-task**: SlackOppConsumer runs on every ECS task
  (it's part of the ASGI app). Each task has its own consumer; the Channels
  layer fans `opp.updated` to all subscribers. To avoid duplicate Slack
  updates, the dispatch tick takes a Redis SETNX lock keyed by
  `slack:dispatch:<thread_id>` with 5s TTL. Loser drops.

## Slash command flow detail

### `/ace run <pdd-link-or-opp-slug>`

1. View receives POST, verifies signature, returns 200 with ephemeral
   `response_type: ephemeral, text: "Got it — checking…"` (3s budget met).
2. Background task:
   - Resolve `SlackUserLink`; if missing, DM link prompt + cache pending
     command + return.
   - Resolve `slug`: if it's a `https://docs.google.com/document/d/…` link,
     run the existing PDD-to-opp creation; otherwise treat as opp slug and
     verify it exists in the workspace.
   - If a Slack-triggered run is already active for `(slug, current_run)`,
     ephemerally reply "already running — see thread ↗" with the existing
     `parent_ts` permalink. Done.
   - Create `Session` bound to `(opp_slug, run_id="next")`; inject the
     `/ace:run` command via the existing action-injection model.
   - Create `SlackRunThread` row.
   - `chat.postMessage` the initial parent card (status = "queued"). Capture
     `ts` into `SlackRunThread.parent_ts`.
   - `group_add` the `SlackOppConsumer` to `opp.<slug>.<run_id>`.

### `/ace new`

Opens a Slack modal (via `views.open`):

- Name (text input; auto-derives slug)
- Idea (multiline textarea, required)
- LLO seed list (optional multiline; one per line)

On submit:

- Create the opp folder via the existing opp-creator.
- Inject `/ace:run` for the new opp.
- Proceed as `/ace run` above.

### `/ace status [<slug>]`

- Ephemeral response.
- Resolves slug (default = most recent active run by this user). Renders the
  parent-card block kit. Reuses the same renderer as the dispatcher.

### `/ace list`

- Ephemeral.
- Queries `SlackRunThread` filtered to `ace_user=request_user`, ordered by
  `triggered_at` desc, limited to 5 active.

### `🍴 Fork from here…`

- `block_actions` payload contains `action_id="fork_from_phase"` and `value=<slug>:<phase>`.
- Handler returns a 200 with an ephemeral response containing a direct link
  to `https://labs.connect.dimagi.com/ace/w/<workspace>/opps/<slug>?fork=<phase>`.
- Frontend: small change to `OppWorkbenchPage` to read `?fork=<phase>` and
  auto-open `ForkOppDialog` with that phase preselected.

## Block Kit rendering

`apps/slack/blocks.py` — pure functions, take a snapshot + phase data, return
Block Kit JSON.

- `render_parent_card(snapshot, thread) -> list[dict]`
- `render_phase_tile(snapshot, phase, run_id) -> list[dict]`
- `render_progress_bar(complete, total) -> str` — unicode block bar.

Unit-tested with fixture snapshots; no Slack contact.

## Error handling

| Failure                                 | Behavior                                                                                                       |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Invalid signing-secret signature        | 401, no log shouting (legitimate bot probes happen).                                                            |
| Unlinked user                           | DM link prompt; cache command; return ephemeral "I'll continue once you link."                                |
| `slug` doesn't exist in workspace       | Ephemeral "no opp `<slug>` in workspace `<ws>`."                                                              |
| Run already active                      | Ephemeral "already running — `<permalink>`."                                                                  |
| Slack `chat.update` `channel_not_found` / `is_archived` | Set `SlackRunThread.broken_at`; stop further updates; no retries.                                |
| Slack `rate_limited` (429)              | Backoff via `Retry-After`; debounce holds the next tick anyway.                                                |
| Snapshot refetch raises                 | Log + skip the tick; next `opp.updated` re-tries.                                                              |
| Subprocess crashes mid-run              | Existing ace-web behavior. Slack parent card stays "running" until next `opp.updated` (none arrives). Status query manually re-syncs the user. (Out of scope: auto-mark broken on crash signal.) |
| ECS task replacement                    | Startup sweep catches up. Phase messages don't duplicate because `phase_messages[<phase>].ts` is the lookup key. |

## Testing

- **Unit**: block-kit renderers against snapshot fixtures; state-hash stability;
  command parsing.
- **Integration (Django test client)**:
  - signing-secret verify happy path + bad-sig 401
  - `/ace run` with valid slug → creates `SlackRunThread`, posts parent
  - `/ace run` with unlinked user → DM + pending-command cache hit on link callback
  - Duplicate `/ace run` → ephemeral "already running"
- **Channels-layer integration**: emit `opp.updated` to a group; assert
  `SlackOppConsumer` called the (mocked) Slack client with the expected
  block-kit payload. Use `channels.testing.WebsocketCommunicator` for the
  worker side, mock `slack_sdk.WebClient`.
- **End-to-end** (manual, dogfood): run `/ace run` on a known opp in the
  dimagi-team workspace against staging Slack; verify thread mutates through
  3 phases; click fork → web dialog opens with phase preselected.

No mock-vs-real-Slack-divergence risk: we hit Slack via the official SDK in
all production paths, and the SDK is the standard mock target.

## Configuration

New env vars:

- `SLACK_CLIENT_ID` — Slack app OAuth client id (for install + `/ace link`)
- `SLACK_CLIENT_SECRET`
- `SLACK_SIGNING_SECRET` — for inbound request verification
- `SLACK_DEFAULT_INSTALLATION_ID` — optional; pin which `SlackInstallation`
  to use when there's exactly one (skips a query on every event)

All via AWS Secrets Manager → ECS task-def → Django settings.

## Open questions deferred to implementation

- **Bot token encryption key**: derive from `SECRET_KEY` (simplest) or
  introduce `SLACK_TOKEN_FERNET_KEY` (cleaner rotation). Decide during
  planning.
- **`/ace new` LLO seed list**: pass-through to the existing opp-creator if
  that path accepts seed LLOs; otherwise drop from the modal in v1.
- **Frontend `?fork=<phase>` plumbing**: minor `OppWorkbenchPage` change.
  Confirm `ForkOppDialog` already accepts `forkAtPhase` as a controlled prop
  (it does, per `PhaseView.tsx:305-313` — `forkAtPhase` is already a
  prop). Just need to wire the query param to the dialog's `open` state.
- **`run_id` resolution at trigger time**: `/ace:run` normally chooses the
  next `run-NNN` folder. The Slack handler needs `run_id` to key
  `SlackRunThread` correctly. Two paths: (a) pre-allocate the next
  `run-NNN` before invoking `/ace:run` and pass it explicitly via the
  injected command phrasing; (b) lazy bind — defer the parent-card post
  and `SlackRunThread` row until the first `opp.updated` event reveals the
  run_id (the ephemeral ack covers the gap). Pick during planning. (b) is
  simpler if `/ace:run` doesn't accept an explicit run_id; (a) avoids any
  race where two simultaneous triggers can't be distinguished.

## What ships in v1

- `apps/slack/` Django app — views, handlers, consumer, blocks, models, migrations
- `/ace/api/slack/events`, `/commands`, `/interactions`, `/install`, `/oauth/callback`, `/auth/slack/link/`
- One slash command (`/ace`) with subcommands as above
- Block-kit parent card + phase tile renderers
- `SlackOppConsumer` joining `opp.<slug>.<run_id>` groups; 2s debounce; 60s sweep
- Per-user OAuth linking flow with 10-min pending-command cache
- One-time admin Slack app install flow
- Encrypted bot-token storage
- Frontend: `?fork=<phase>` query param → auto-open `ForkOppDialog`
- Tests as outlined above
- Docs: `docs/architecture/slack-integration.md` for the runbook +
  add `slack-integration` learning entry to `CLAUDE.md`

## What's explicitly NOT in v1

- Gate approve/reject buttons
- Native Slack fork modal
- Token-by-token streaming
- Multi-tenant Slack install (>1 `SlackInstallation` row)
- Admin-configurable channel routing
- Auto-mark-broken on subprocess crash detection
- Cross-channel notifications (e.g., notify #ace-runs whenever a run finishes
  regardless of trigger channel)
- Slack-side comment-to-chat ingest (replying in the thread doesn't seed
  anything into the ace-web Session; thread is read-only from ACE's POV)
