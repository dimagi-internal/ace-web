# ACE Web Harness — Design Spec

**Date:** 2026-04-08
**Status:** Approved for execution. Phase 1 complete; Phase 2 implementation plan to follow.
**Scope:** The complete ace-web product. Phase breakdown is engineering execution order, not user-facing milestones.

## 1. Overview

ace-web is a browser-based chat harness on top of Claude. The team logs in via Google SSO (GCP IAP), lands in their conversation library, picks up an existing thread or starts a new one, types a prompt, and watches Claude stream a response in real time with tool use rendered cleanly. They can hand a draft to a teammate to refine, see who else is active in a session, share a read-only link with someone outside the team, and import old `.jsonl` transcripts from a laptop into the same library.

The intended audience is the internal Dimagi team building ACE / CRISPR-Connect. The bar is "polished internal tool the team actively wants to use," not "MVP for paying customers."

## 2. Goals

1. **Persistent, recoverable transcripts.** Every chat the team has with Claude is durable in Postgres, navigable, searchable, and recoverable across instance restarts and deploys.
2. **Real-time streaming UX.** Token-by-token response rendering, never "spinner then full reply."
3. **Multi-player collaboration.** More than one team member can participate in the same conversation, propose drafts together, and see each other's presence.
4. **Subscription auth via Claude CLI.** Uses the team's Claude subscription via the local CLI (`claude -p --output-format stream-json`), not API keys. Self-service in-app onboarding for new team members.
5. **Imported library.** Existing local `.jsonl` Claude CLI sessions can be uploaded into the same library so the team has one place to find any conversation.
6. **No incremental user shipping.** The team uses ace-web only after all phases land. Each phase is an engineering checkpoint, not a release candidate.

## 3. Users

Internal Dimagi team members on the ACE / CRISPR-Connect initiative. Authenticated via GCP IAP behind Google SSO. Membership is managed at the IAP layer. There are no external users in scope; share-token viewers are the only anonymous case, and they get read-only access.

## 4. Functional scope

### 4.1 Conversation engine

- `ChatBackend` abstraction (`Protocol`) so the transport to Claude is swappable. Only `CLIBackend` ships; `ApiBackend` and `McpBackend` are reserved enum values, not implemented.
- `CLIBackend` wraps `claude -p --output-format stream-json` and parses the JSONL event stream.
- **Hybrid resume strategy.** Each turn first attempts `claude -p --resume <Session.cli_session_id>`. On failure (CLI session store missing — instance churn, deploy, container restart) it restarts with the full conversation history seeded from Django and captures the new `cli_session_id`. Django is the durable source of truth; the CLI's session store is a hot cache.
- Real token-by-token streaming over **SSE** in Phase 2; replaced by **WebSocket (Channels)** in Phase 3 once the multi-player consumer needs broadcast.
- Tool use and tool result blocks are first-class. Each `tool_use` and `tool_result` block becomes its own `Message` row with its own monotonically-incrementing `turn_index` (the unique constraint is `(session, turn_index)`, so siblings cannot share an index). The UI groups adjacent `tool_use` / `tool_result` rows visually under the assistant row that emitted them, using role + adjacency, not a parent foreign key.
- Auto-titling: the first user message in a session triggers a separate one-shot CLI call to summarize the message in ~6 words. The result becomes the session title. Manual edits override. Failure leaves the title blank — non-blocking.
- Stop button: cleanly cancels an in-flight model call. Server detects client disconnect via the async iterator being cancelled, sends `SIGTERM` to the subprocess, then `SIGKILL` after 2s if it has not exited. Partial output is preserved on the `Message` row with `status=error` and `error_detail="cancelled"`.
- Circuit breaker on the `CLIBackend`: 5 consecutive failures opens the breaker, calls fail fast for a cooldown window. Ported from `canopy-web/apps/common/anthropic_client.py`.

### 4.2 CLI authentication

Full PTY-based `claude setup-token` flow ported from `canopy-web/apps/common/auth_flow.py`:

- `apps/common/auth_flow.py` — the PTY driver. Spawns `claude setup-token`, parses ANSI-stripped output to extract the auth URL, accepts a pasted code, captures the resulting `sk-ant-oat...` token.
- REST endpoints under `/api/auth/cli/`: `start`, `complete`, `poll`, `cancel`, `status`.
- React `/auth/cli` page: "Connect Claude" button, displayed auth URL, code paste box, status indicator, error states.
- Token persisted to `/var/lib/ace-claude/oauth-token` (configurable via `ACE_CLAUDE_TOKEN_FILE`), exported to `os.environ["CLAUDE_CODE_OAUTH_TOKEN"]`.
- Loaded at app boot via a Django `AppConfig.ready()` hook.
- A top-of-page banner in the chat UI shows "Claude not connected — visit /auth/cli" if the token is missing or has expired.

### 4.3 Multi-player collaboration

- WebSocket consumer at `apps/sessions/consumers.py` replaces SSE for the streaming transport.
- channels-redis migration: `CHANNEL_LAYERS` switches to `RedisChannelLayer` pointing at a Memorystore Redis instance. Cloud Run `max-instances` is relaxed.
- ASGI-scope IAP middleware: a parallel auth path for WebSocket handshakes (Channels' `__call__` does not run the HTTP middleware stack). Resolves the gap flagged in `docs/learnings/iap-websocket-coverage.md`.
- **Drafts model** (already in the schema from Phase 1): multiple users compose the next message together.
  - `slot=next` is the active draft (one open per session, enforced by the partial unique constraint already in the schema).
  - `slot=queued` is for planned follow-ups behind the active draft, with `queue_position` ordering.
  - Version-tracked, last-editor stamped, status transitions `open → sent | discarded`.
  - When sent, a draft becomes the user `Message` for the next turn and the `Draft.sent_message` foreign key is set.
- **Presence**: `SessionParticipant.last_seen_at` updated on heartbeat. UI shows who's currently in the session and who's actively typing in the active draft.
- **Real-time broadcast**: when one user sends a message, every connected participant's UI receives the streaming response from the same source. Tool use events broadcast too.

### 4.4 Transcript library

- Session list page (`/library` or `/`): the user's sessions, paginated, filterable by `status` (active/archived/imported), sortable by recent, with a search box that does a case-insensitive substring match on title.
- Inline title editing on every row.
- Per-row actions: open, archive/unarchive, delete (with confirmation).
- Per-session participants view (modal or sidebar): list of `SessionParticipant` rows with role and last-seen-at.
- Session metadata view: source (web/upload), backend, created/updated, message count, owner.

### 4.5 Share and access

- Share tokens (already in the schema): generate a public read-only link for any session. URL shape: `/share/<token>`. Token is revocable via `ShareToken.revoked_at`. Anonymous viewers see the transcript but cannot post, see participant identities, or see other session metadata.
- Per-session participant management: `SessionParticipant` rows with `role` in `owner`, `editor`, `viewer`. UI for adding/removing participants by email.
- The IAP layer is still the team-membership boundary; participant management is *within* the team.

### 4.6 Ingest

- `ace upload <file.jsonl>` CLI is a standalone console script (a Python entrypoint installed via `pyproject.toml` `[project.scripts]`, not a `manage.py` subcommand) backed by code in `apps/ingest/`. Reads a local Claude CLI session file and POSTs it to `/api/ingest/upload` as a single multipart request. Server parses the JSONL into `Session` + `Message` rows with `source=upload`, `status=imported`, and creates a matching `IngestUpload` row recording the original path, byte count, line count, and `cli_session_id` from the file.
- Bulk import: passing a directory uploads every `.jsonl` file in it.
- Imported sessions render in the same UI as live ones. The send box is disabled — they're read-only.
- The CLI requires a Claude IAP-authenticated identity token (`gcloud auth print-identity-token`) and the user's email is matched to a Django `User` row at the server.

### 4.7 Polish

- Structured logs with `session_slug`, `user_id`, `turn_index`, `cli_session_id` correlation fields.
- Counters / gauges: CLI calls per minute, latency p50/p95/p99, error rate, circuit breaker state, active SSE/WebSocket connections.
- Eval harness: a fixture session in `tests/fixtures/` runs through `CLIBackend` end-to-end and snapshots the resulting messages. Backend regressions get caught.
- Accessibility: keyboard-navigable chat (tab through messages, j/k navigation, enter-to-send, shift-enter for newline), screen-reader-friendly streaming (use `aria-live="polite"` on the assistant message currently streaming).
- Empty / error / loading states for every page.
- Security review: secrets handling, IAP boundary integrity, share-token revocation correctness, subprocess argument injection check.
- Demo prep: a scripted walkthrough doc covering "first-time team-member onboarding → first chat → first draft collaboration → first share".
- Full documentation pass: `docs/learnings/` cleanup, `CLAUDE.md` updated, `README.md` updated.

## 5. Architecture

### 5.1 Stack

Already defined in Phase 1 (Plan 1A). Recap: Django 5 + Channels 4 + DRF, ASGI via uvicorn, PostgreSQL 16, React 19 + Vite + Tailwind 3.4, deployed on GCP Cloud Run behind IAP. See `docs/plans/2026-04-07-1a-foundation.md` for the full scaffold and the post-execution corrections that hardened it.

### 5.2 Streaming transport

Two transports across the lifetime of the project. The `ChatBackend.stream_completion()` interface is identical for both — only the wrapping changes.

**Phase 2 — SSE (Server-Sent Events)**
- `GET /api/messages/<id>/stream` returns `StreamingHttpResponse` with `text/event-stream`.
- Async generator drives `CLIBackend.stream_completion()` and serializes each `StreamEvent` to an SSE frame (`event: <type>\ndata: <json>\n\n`).
- Reconnect semantics: if the client reconnects mid-stream, the server reads the message's current `plaintext`, yields it as a single delta event, then continues streaming. If the message is already `complete`, yields the final state and closes immediately.
- Single consumer per stream — natively fine for single-user chat. No fan-out infrastructure needed.

**Phase 3 — WebSocket (Channels)**
- `apps/sessions/consumers.py` defines a `SessionConsumer` (Channels async consumer).
- The consumer subscribes to a per-session group on connect, dispatches `chat.send` actions to a backend task that runs `CLIBackend.stream_completion()`, and broadcasts events to the group.
- Same `StreamEvent` types, same DB write semantics, same auto-title and stop-button paths.
- Drafts get their own message types on the same WebSocket (`draft.update`, `draft.send`, `draft.discard`, `presence.heartbeat`).

The CLIBackend is unchanged across this transition. The `stream_completion()` async iterator is consumed once by the SSE view in Phase 2 and once by the consumer task in Phase 3. The streaming pipeline written in Phase 2 is *not* throwaway code — only the HTTP wrapping is.

### 5.3 Persistence

- **Postgres** (AWS RDS in prod, dockerized in dev) is the durable store for everything user-facing: users, sessions, messages, drafts, share tokens, ingest uploads.
- **CLI session store persistence** (the `~/.claude` directory) is deferred — ECS EFS mount or dropped entirely in favor of the hybrid-resume Django-replay path. No Filestore equivalent is provisioned; the hybrid resume strategy is the primary approach.
- **docker-compose** uses a local Postgres container for dev; no CLI state volume is needed since hybrid resume handles cold starts.
- **AWS ElastiCache Redis** (shared connect-labs instance, free — already provisioned) will be used in Phase 3 for `channels-redis`. No new Redis infrastructure required.

### 5.4 Authentication and authorization

- **Edge auth:** Auth is handled at the ALB layer or via django-allauth with Connect OAuth — final decision in the AWS migration plan.
- **Per-session authorization:** `SessionParticipant` rows. `owner` and `editor` can edit drafts and send messages; `viewer` can read only. Created automatically for the session creator on `POST /api/sessions`.
- **Share tokens:** The `/share/<token>` route is public within the application. The view checks `ShareToken.revoked_at IS NULL` and returns the read-only view. **ALB routing details deferred to Phase 4 implementation.**

### 5.5 Data model

Already defined in Phase 1 with seven tables: `users`, `sessions`, `session_participants`, `messages`, `drafts`, `share_tokens`, `ingest_uploads`. The schema is complete for the entire vision — no migrations are required to ship Phase 2 beyond what Plan 1A already shipped.

Phase 3 adds nothing schema-wise. Phase 4 adds nothing schema-wise. The Phase 1 schema was forward-designed to cover the whole vision.

The fields that are placeholders today and become live in later phases:
- `Session.cli_session_id` — used in Phase 2 (CLIBackend hybrid resume).
- `SessionParticipant.last_seen_at` — used in Phase 3 (presence).
- `Draft.*` — used in Phase 3 (multi-player drafts).
- `ShareToken.*` — used in Phase 4 (share links).
- `IngestUpload.*` — used in Phase 4 (ingest CLI).

## 6. Phase breakdown

| Phase | Name | Scope | Output |
|---|---|---|---|
| 1 | Foundation | Skeleton, IAP, data model, deploy | **Complete** — `docs/plans/2026-04-07-1a-foundation.md`, jjackson/ace-web#1 |
| 2 | Conversation engine | ChatBackend interface, CLIBackend, CLI auth, SSE streaming, REST API for sessions/messages, single-user chat UI with recent-sessions sidebar, auto-title, stop button, tool-use rendering, Filestore mount | A user can create a session, type a message, watch streaming response, navigate back later, continue. CLI auth is in-app self-service. |
| 3 | Multi-player collaboration | WebSocket consumer, channels-redis (free — shared ElastiCache already exists on connect-labs), ASGI auth middleware, drafts (slots/versions), presence, real-time broadcast | Two users can sit in the same session, draft together, see each other present, see the same streaming response. |
| 4 | Library and ingest | Session list page (search/filter/archive), share tokens, `ace upload` CLI, ingest UI, participant management | The team has a real library with search, sharing, and import. |
| 5 | Polish | Observability, eval harness, accessibility, empty/error/loading states, security review, demo prep, full docs pass | The bar is met. The team starts using it. |

Each phase produces its own implementation plan file in `docs/plans/<date>-<phase-slug>.md`, written via the writing-plans skill. Implementation is via subagent-driven-development per the Phase 1 precedent.

## 7. Non-goals

Deliberately excluded from the entire vision (not deferred to a "later phase" — explicitly out):

- **API-key backend (`ApiBackend`).** Not shipped. The schema's enum value is reserved but no implementation lands. canopy-web has the pattern if it ever becomes needed.
- **MCP backend (`McpBackend`).** Reserved enum value, no implementation.
- **Cross-session search (full-text or semantic).** A title substring search is in Phase 4. Searching across message bodies is not in scope.
- **Exporting transcripts back to `.jsonl`.** Import only.
- **Mobile-responsive design.** Desktop-only. The team is on laptops.
- **Branded marketing landing page.** Anyone past IAP lands directly in the library.
- **Pricing / billing / quotas.** Internal tool, no commercial layer.
- **Email notifications.** No "your teammate sent a message" emails. Presence in-app is sufficient.
- **External integrations beyond Claude CLI.** No Slack, no GitHub, no Linear hooks.
- **Conversation forking / branching.** Each session is linear.

## 8. Open risks

- **Shared infrastructure coupling** — if connect-labs infrastructure changes or goes down, ace-web is affected. Mitigated by the small number of tenants and the team's direct ops control.
- **`claude -p --output-format stream-json` event format is an external dependency.** Phase 2 must capture real fixtures and document the event shapes in `docs/learnings/cli-stream-json-format.md`. If the CLI changes its output format, the parser breaks. Mitigation: snapshot fixtures + an opt-in integration test that hits a real CLI.
- **PTY auth flow is fragile.** ANSI parsing, threading, subprocess lifecycle. The canopy-web port is the proven shape; deviating from it should be deliberate.
- **Channels-redis migration in Phase 3 is a real config change.** The warning comment in `production.py` should be the trigger to invest the time. The ElastiCache instance is already provisioned (shared with connect-labs) so no new infra is needed.
- **Share-token auth exemption** approach depends on the final AWS auth decision (ALB OIDC vs django-allauth). Phase 4 implementation decides and documents.

## 9. Key technical decisions (for cross-reference from phase plans)

- CLI is the only backend that ships. `ApiBackend` and `McpBackend` are reserved enum values.
- Hybrid CLI resume: `--resume` first, Django-replay on miss. Django is the durable source of truth.
- SSE in Phase 2, WebSocket in Phase 3. The streaming pipeline is shared.
- CLI session store persistence deferred (ECS EFS or dropped); hybrid resume is the primary strategy. No Filestore equivalent provisioned.
- One subprocess per chat turn. Cancellation via SIGTERM then SIGKILL. No subprocess pool.
- Tool use as nested `Message` rows under the parent assistant turn.
- Stop button + clean cancel ships in Phase 2. Auto-titling ships in Phase 2.
- channels-redis arrives with multi-player in Phase 3, using the shared connect-labs ElastiCache instance.
- Share links are public-by-token, revocable, anonymous-readable.
- Polish (observability, evals, accessibility, security review, demo prep) bundled in Phase 5.

## 10. References

- Phase 1 plan with post-execution corrections: `docs/plans/2026-04-07-1a-foundation.md`
- Existing learnings: `docs/learnings/{api-envelope-convention,channels-single-instance,user-google-sub-nullable}.md`
- Pattern source for the CLI backend: `../canopy-web/apps/common/anthropic_client.py`
- Pattern source for the PTY auth flow: `../canopy-web/apps/common/auth_flow.py`
- Deploy guide: `docs/deploy.md`
