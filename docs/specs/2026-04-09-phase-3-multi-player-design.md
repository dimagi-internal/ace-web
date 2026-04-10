# ACE Web — Phase 3: Multi-player Collaboration — Design

**Date:** 2026-04-09
**Status:** Approved for implementation planning.
**Scope:** Detailed design for Phase 3 of `docs/specs/2026-04-08-ace-web-design.md`. Expands §4.3 and §5.2 of the main spec with the decisions made in the Phase 3 brainstorming session.

## 1. Goal

Two or more `@dimagi.com` teammates can sit in the same `Session`, collaboratively draft the next prompt, watch the same streaming assistant response, and see each other's live presence. The product model is **turn-taking hand-off drafting**: usually one person is actively typing while the rest watch; any editor can take over when the current drafter goes idle; any editor can stop a bad response mid-stream.

This is not Google-Docs-style simultaneous co-typing. That is a separate product bet for a later focused effort.

## 2. Non-goals (for this phase)

- CRDT / operational transform for true real-time co-typing. Evaluated and rejected in favor of a soft-lock turn-taking model that matches the actual use case.
- Full participant management UI (add/remove/change role with confirmations, error handling, admin-style table). Phase 3 ships only a minimal "add teammate by email" control; the full surface is Phase 4.
- Queued follow-up drafts (`Draft.slot='queued'`). Schema stays untouched but the UI and consumer actions for queued drafts are out of scope. Only `slot='next'` is exercised.
- Share tokens, session library search, archive/unarchive. All Phase 4.
- Raising the ECS desired-count above 1 automatically. The channels-redis swap unblocks it; the actual scale-up is a separate post-merge operational step.

## 3. Key decisions

1. **WebSocket is the only chat transport.** `POST /api/sessions/<slug>/messages` is deleted. `apps/sessions/streaming.py` (SSE) is deleted. The consumer owns message creation, streaming, drafts, and presence on a single socket. `GET /api/sessions/<slug>/messages` remains for read-only observation from tests and automation.
2. **Drafts use a soft-lock turn-taking model.** One active drafter at a time. Others see the body update live as a read-only preview. A "Take over" control is available when the current holder is idle >2 s or no longer present. `Draft.version` guards the rare idle race.
3. **Minimal participant surface.** `POST /api/sessions/<slug>/participants` adds an editor by `@dimagi.com` email. A tiny "Add teammate" button lives in the chat header. Role changes and removal are deferred to Phase 4.
4. **Any editor (or owner) can stop an in-flight stream.** Viewers cannot.
5. **Full state replay + live join on reconnect.** On `connect()`, the consumer sends one `session.state` frame with the full message history, active draft, participants list, and live presence, then joins the group so the client receives any further stream events in order.
6. **channels-redis in local dev too.** `docker-compose.yml` gains a `redis:7-alpine` service. `CHANNEL_LAYERS` points at Redis by default in base settings so dev and prod exercise the same code path. Tests use `InMemoryChannelLayer` + `fakeredis` for presence keys.
7. **Redis-backed presence with debounced Postgres writes.** A Redis HASH per session holds `{user_id → expires_at}` with a 60-s TTL per field, refreshed by client heartbeat every 20 s. `SessionParticipant.last_seen_at` is written to Postgres at most once per user per 30 s via a separate Redis debounce key.

## 4. Architecture

### 4.1 Module layout

```
apps/sessions/
├── consumers.py      # NEW  SessionConsumer — protocol only, thin dispatch
├── turn_driver.py    # NEW  drive_assistant_turn(...) — lifted from streaming.py
├── drafts.py         # NEW  draft state machine (soft-lock, commit, discard)
├── presence.py       # NEW  Redis HASH presence + debounced last_seen writer
├── routing.py        # MODIFIED  real websocket_urlpatterns
├── streaming.py      # DELETED
├── views.py          # MODIFIED  send_message removed; GET messages added;
│                     #           POST participants added
├── serializers.py    # MODIFIED  ParticipantSerializer, DraftSerializer,
│                     #           StateSnapshotSerializer
└── tests/
    ├── test_consumers.py   # NEW  WebsocketCommunicator tests
    ├── test_turn_driver.py # NEW  lifted from test_streaming.py
    ├── test_drafts.py      # NEW  state machine unit tests
    ├── test_presence.py    # NEW  fakeredis unit tests
    ├── test_views.py       # MODIFIED  remove send_message tests;
    │                       #           add participants + messages-GET tests
    └── test_streaming.py   # DELETED

apps/common/
├── channels_auth.py  # NEW  ASGI session-cookie auth middleware
├── redis_client.py   # NEW  one place to build the shared Redis pool
└── tests/test_channels_auth.py  # NEW

config/
├── asgi.py                   # MODIFIED  wrap router in channels_auth + origin validator
├── settings/base.py          # MODIFIED  CHANNEL_LAYERS → RedisChannelLayer, REDIS_URL
├── settings/connectlabs.py   # MODIFIED  read REDIS_URL from Secrets Manager env
└── settings/test.py          # MODIFIED  InMemoryChannelLayer for ws tests

docker-compose.yml            # MODIFIED  add redis service, REDIS_URL to web
pyproject.toml                # MODIFIED  + channels-redis, + fakeredis (dev)
deploy/aws/task-definition.json  # MODIFIED  REDIS_URL env from secrets ref

docs/learnings/
├── channels-single-instance.md       # MODIFIED  marked resolved with pointer
├── channels-websocket-auth.md        # NEW
└── redis-presence-hash.md            # NEW
```

### 4.2 Runtime topology

```
Browser (React)
  │  one native WebSocket per open Session
  │  JSON frames: {action, data} ↔ {event, data}
  ▼
ALB (wss://labs.connect.dimagi.com/ace/ws/sessions/<slug>/)
  │
  ▼
nginx sidecar   (proxy_pass with Upgrade/Connection headers for ws)
  │
  ▼
uvicorn ASGI worker(s)
  │  ProtocolTypeRouter → websocket branch
  │    ├─ AllowedHostsOriginValidator
  │    ├─ AceSessionAuthMiddleware  (sessionid_ace cookie → scope['user'])
  │    └─ URLRouter → SessionConsumer
  │
  ▼
SessionConsumer  (AsyncJsonWebsocketConsumer)
  │
  ├─ connect()         auth + participant check, join group,
  │                    presence.touch, send session.state, rejoin live stream
  ├─ receive_json()    dispatch {action} → handler module
  │     ├─ chat.send         → drafts.commit_active_draft → spawn turn task
  │     ├─ chat.stop         → signal stop_event on named turn
  │     ├─ draft.update      → drafts.update_body → group send
  │     ├─ draft.take_over   → drafts.claim_lock → group send
  │     ├─ draft.discard     → drafts.discard → group send
  │     └─ presence.heartbeat → presence.touch
  └─ disconnect()      presence.leave

Redis (shared connect-labs ElastiCache)
  ├─ channels_redis layer            (group_send fan-out across tasks)
  ├─ turn.stop:{message_id}          (string, set by chat.stop, polled by turn driver)
  ├─ presence:{session_slug}         (HASH user_id → expires_at_epoch)
  └─ presence.last_seen:{slug}:{uid} (string, 30 s TTL, presence DB-write debounce)

Postgres (shared connect-labs RDS)
  ├─ messages                (consumer is the sole writer for assistant streaming)
  ├─ drafts                  (consumer is the sole writer; version + body + last_editor)
  ├─ session_participants    (debounced last_seen_at update; add-participant endpoint)
  └─ (rest unchanged)
```

### 4.3 Reuse of Phase 2 streaming code

`apps/sessions/streaming.py` contains the async generator `_generate` and its DB-debounced helpers (`_mark_streaming`, `_update_plaintext`, `_mark_complete`, `_mark_error`, `_create_tool_message`, `_load_last_user_text`). These lift wholesale into `apps/sessions/turn_driver.py` as:

```python
async def drive_assistant_turn(
    assistant_message_id: int,
    stop_event: asyncio.Event,
) -> AsyncIterator[StreamEvent]:
    ...
```

Only the SSE framing layer (`_sse_frame`, `_sse_frame_for`, the `StreamingHttpResponse` wrapper, and the async view itself) is deleted. The `CLIBackend`, the hybrid-resume logic, the 250 ms plaintext debounce, the cancellation path, the circuit breaker, and the auto-title hand-off are all unchanged.

The consumer consumes `drive_assistant_turn` in its own task and fans each yielded event into `self.channel_layer.group_send` rather than writing SSE bytes. The stop signal travels through a Redis string key `turn.stop:{message_id}` (set by any consumer on `chat.stop`) that the turn driver polls on each loop iteration and also before each subprocess read — cross-task cancellation works without needing a dedicated channel.

## 5. Wire protocol

All frames are JSON text. Clients send `{"action": "<namespace.verb>", "data": {...}}`; the server sends `{"event": "<namespace.verb>", "data": {...}}`.

### 5.1 Client → Server actions

| Action | `data` shape | Notes |
|---|---|---|
| `chat.send` | `{}` | Commits the active draft and starts the assistant turn. Consumer ignores the field if there is no open draft. |
| `chat.stop` | `{message_id: int}` | Any editor or owner. Viewer → `session.error code=forbidden`. |
| `draft.update` | `{version: int, body: string}` | `version` mismatch → `session.error code=draft_version_mismatch` carrying the current state. |
| `draft.take_over` | `{}` | Allowed iff current holder is idle >2 s OR not in `presence:{slug}`. Otherwise `session.error code=draft_lock_held`. |
| `draft.discard` | `{}` | Resets `Draft.body` to `""`, bumps `version`, keeps `slot='next'` open. |
| `presence.heartbeat` | `{}` | Every 20 s from the client, refreshes the Redis TTL. |

### 5.2 Server → Client events

| Event | `data` shape | Notes |
|---|---|---|
| `session.state` | `{messages, active_draft, participants, presence_user_ids, current_user_id}` | Sent once immediately after `connect()`. `messages` is the full ordered list (consistent with Phase 2 GET); any in-flight streaming message is included with its current accumulated `plaintext` and `status='streaming'`, so a late joiner starts from the right cursor and then receives subsequent `chat.delta` events from the group. `active_draft` is the open `slot='next'` draft or a freshly created empty one. `current_user_id` is the id of the authenticated user on this socket (the client needs it to identify itself among `participants` and determine whether it is the current draft holder). |
| `session.error` | `{code, message, detail?}` | Non-fatal errors. Codes: `bad_request`, `forbidden`, `draft_version_mismatch`, `draft_lock_held`, `not_found`, `internal`. |
| `chat.stream_start` | `{message_id, turn_index}` | Emitted once when the turn driver marks the message `streaming`. |
| `chat.delta` | `{message_id, text}` | Append-only delta text (same shape as Phase 2 SSE `delta`). |
| `chat.tool_use` | `{parent_message_id, tool_message_id, block}` | A new `Message` row was created with role `tool_use`; clients render it nested under the parent. |
| `chat.tool_result` | `{parent_message_id, tool_message_id, block}` | Same as above with role `tool_result`. |
| `chat.stream_complete` | `{message_id, plaintext}` | Final plaintext for the assistant message. |
| `chat.stream_error` | `{message_id, detail}` | Backend failure or CLI circuit breaker open. The backend also uses this event to surface stop-driven cancellation by setting `detail='cancelled'`. The `chat.stream_cancelled` event listed below is a defensive branch that is not currently reachable. |
| `chat.stream_cancelled` | `{message_id, partial_len}` | **Not emitted in practice** under the current `turn_driver` contract — stop-driven cancellation surfaces as `chat.stream_error` with `detail='cancelled'`. The server and client both retain handlers for this event as a defensive branch in case the turn_driver is refactored to distinguish cancellation from error. |
| `draft.updated` | `{draft_id, version, body, last_editor_id, last_edit_at}` | Broadcast after every accepted `draft.update`, `draft.discard`, or `draft.committed` (for the new empty next draft). |
| `draft.lock_changed` | `{draft_id, holder_user_id \| null, expires_at}` | Broadcast on `draft.take_over` and implicitly when the holder goes idle (the client computes idle-ness from `last_edit_at` — the server does not push idle-expiry ticks). |
| `draft.committed` | `{draft_id, message_id}` | Sent with the draft that just became a user `Message`. |
| `draft.discarded` | `{draft_id}` | |
| `presence.joined` | `{user_id, email, display_name}` | Broadcast when a user's presence hash field is first added. |
| `presence.left` | `{user_id}` | Broadcast on clean `disconnect()`; ungraceful drop relies on the 60 s TTL and is picked up by the next reader. |

### 5.3 Close codes

| Code | Meaning |
|---|---|
| `4001` | Unauthenticated — no valid Django session cookie on the handshake. |
| `4003` | Authenticated but not a participant in this session. |
| `4004` | Session not found. |
| `1011` | Internal error (Redis unavailable, unhandled exception). The `/api/health` HTTP path stays green because it does not touch the channel layer. |

## 6. Draft state machine

State lives entirely in the `Draft` row (`slot`, `status`, `body`, `version`, `last_editor`, `updated_at`). There is no separate in-memory lock.

```
                 chat.send
                commit_active_draft()
   ┌─────────┐  ──────────────────►  ┌──────┐
   │  open   │                       │ sent │
   │(slot=   │                       └──────┘
   │ next)   │                          │
   └─────────┘  ◄────────────          │ creates new
        │       new empty              ▼ open draft
        │         draft           ┌─────────┐
        │                         │  open   │  (freshly created by commit
        │                         │(slot=   │   inside the same transaction)
        │                         │ next)   │
        ▼                         └─────────┘
   ┌───────────┐
   │ discarded │
   └───────────┘
```

The soft lock is derived, not stored. The current "holder" is `Draft.last_editor`, and the lock is **idle** when `now() - Draft.updated_at > 2s` OR `Draft.last_editor` is absent from `presence:{slug}`. The client computes this locally from the broadcast `draft.updated` events and the `presence.joined` / `presence.left` events — no server ticks are required.

`drafts.commit_active_draft(user, session)` runs inside one transaction:
1. `SELECT FOR UPDATE` the session row.
2. Select or create the `open, slot='next'` draft.
3. Compute the next two `turn_index` values.
4. `INSERT` the user `Message` with `sender_user=user`, `plaintext=Draft.body`, `status='complete'`.
5. `INSERT` the assistant placeholder `Message` with `status='pending'`.
6. `UPDATE` the draft: `status='sent', sent_message_id=<assistant>, sent_at=now()`. (The assistant-id is recorded here because the `sent_message` FK is the "turn this draft started" pointer; the user message is reachable through the assistant's `turn_index - 1`.)
7. `INSERT` a new `Draft(session=..., slot='next', status='open', body='', version=0, creator_user=user, last_editor=user)`.
8. Return `(assistant_message_id, old_draft_id, new_draft_id)`.

The consumer then broadcasts `draft.committed`, `draft.updated` (new empty draft), `chat.stream_start`, and spawns the turn driver.

## 7. Presence

### 7.1 Redis HASH layout

Key: `presence:{session_slug}` (HASH)
Field: `{user_id}` (string)
Value: `{expires_at_epoch}` (string, unix seconds)

Operations (in `apps/sessions/presence.py`):

- `touch(user_id, slug)` — `HSET presence:{slug} {user_id} {now + 60}`. If the field was newly added, broadcast `presence.joined` and schedule a debounced `last_seen_at` write (see below). Returns `(was_new: bool, current_user_ids: list[int])` for the consumer.
- `leave(user_id, slug)` — `HDEL presence:{slug} {user_id}` + broadcast `presence.left`.
- `snapshot(slug)` — `HGETALL presence:{slug}`, drop fields where `expires_at < now()` with a lazy `HDEL`, return the remaining user_ids. Used on `connect()` to build `session.state.presence_user_ids`.
- `is_present(user_id, slug)` — used by `drafts.claim_lock` to decide if the current holder is still in the session.

The 60 s TTL per field (not per key) means a crashed client's presence entry ages out on the next reader within ~60 s of its last heartbeat. There is no periodic sweeper task — laziness is sufficient.

### 7.2 Debounced Postgres write

Key: `presence.last_seen:{slug}:{user_id}` (STRING, TTL 30 s)
Value: `1` (presence-only, no payload)

On `touch(...)`, check `SET presence.last_seen:{slug}:{user_id} 1 EX 30 NX`. If the SETNX succeeded (key did not exist), write `SessionParticipant.last_seen_at = now()` to Postgres inside `sync_to_async`. Otherwise skip. Worst case: one DB write per user per 30 s per session.

## 8. ASGI authentication middleware

`apps/common/channels_auth.py` defines `AceSessionAuthMiddleware` — a small async middleware that:

1. Reads the `sessionid_ace` cookie from `scope['headers']`.
2. If missing → `scope['user'] = AnonymousUser()` and delegates.
3. Otherwise calls `sync_to_async(_resolve_user_from_session_key)(session_key)` which loads the Django session row and its associated `User`.
4. Attaches to `scope['user']`.

The cookie name is read from `settings.SESSION_COOKIE_NAME` to stay in sync with the tenant-specific cookie (`sessionid_ace`) configured in `connectlabs.py`.

The consumer's `connect()` checks `scope['user'].is_authenticated`; if not, `await self.accept()` then `await self.close(code=4001)`. Then it checks a `SessionParticipant` row for the `(session, user)` pair; if missing or role=`viewer` for actions that require editor permission, the handshake succeeds but the permission-restricted actions return `session.error code=forbidden`.

The existing HTTP-side `CommCare Connect OAuth` flow (`apps/auth/oauth_views.py`) is unchanged — it sets the standard Django session cookie on the HTTP response, which the browser then sends on the WebSocket handshake.

## 9. Frontend changes

### 9.1 New hook: `useSessionSocket(slug)`

Owns one WebSocket per mounted chat page. Exposes:

```ts
interface SessionSocket {
  state: SessionState           // last session.state + live-applied events
  sendChat(): void              // chat.send
  stopChat(messageId: number): void
  updateDraft(body: string): void  // debounced 150 ms
  takeOverDraft(): void
  discardDraft(): void
  // heartbeat is fire-and-forget internal to the hook
}
```

The hook is the only module that talks to the socket. React components read from `state` and call the imperative methods. Reconnection is automatic with exponential backoff (1 s / 2 s / 5 s / 10 s capped). On reconnect, the next `session.state` replaces local state.

### 9.2 Component updates

- `ChatPage.tsx` — uses `useSessionSocket` instead of `useStreamingMessage` (deleted) and the REST send helper. Renders presence chips in the header.
- `SendBox.tsx` — becomes a controlled `<textarea>` bound to `state.active_draft.body`. On input, calls `socket.updateDraft(nextBody)` (debounced). Editing semantics:
  - **You are the holder** (`active_draft.last_editor_id === currentUser.id`): textarea is editable; the Send button commits.
  - **Holder is idle** (`now - last_edit_at > 2s`) **or holder is absent** (`!presence_user_ids.includes(holder)`): textarea is editable; the first keystroke implicitly takes over the lock because `draft.update` sets `last_editor` server-side. No explicit button click needed in this case.
  - **Holder is active** (idle ≤ 2 s and in presence): textarea is read-only, showing the holder's live body; a "Take over" button appears but is disabled until the hold goes idle, at which point the button becomes a single-click shortcut to focus the textarea (equivalent to the idle-first-keystroke path).
  - Send button is disabled when the draft body is empty or when a turn is already streaming for this session.
- `MessageList.tsx` / `MessageItem.tsx` — unchanged rendering, but the streaming state now comes from `state.messages` rather than a per-message SSE hook. The currently streaming assistant message is the one with `status='streaming'`.
- `PresenceChips.tsx` — NEW. Renders avatars for each user in `state.presence_user_ids`. Tooltip shows display name + "editing…" if this user is the draft holder and the lock is not idle.
- `AddTeammateButton.tsx` — NEW. Tiny modal: email input + confirm. Calls `POST /api/sessions/<slug>/participants`. On success, the server push of `presence.joined` (when the teammate opens the session) is the feedback; the modal just closes on 200.
- `CliAuthBanner.tsx` — unchanged.
- `useStreamingMessage.ts` — DELETED.
- `useRecentSessions.ts` — unchanged.
- `api/messages.ts` — REST send helper deleted; `GET /api/sessions/<slug>/messages` helper remains.

### 9.3 Routes

No new routes. Existing `/chat` and `/chat/<slug>` stay the same.

## 10. Backend REST surface changes

| Route | Method | Change |
|---|---|---|
| `/api/sessions/<slug>/messages` | `POST` | **Deleted.** Sends flow through the WebSocket. |
| `/api/sessions/<slug>/messages` | `GET` | **New.** Ordered list of messages. Read-only; used by automation and for the initial hydration fallback if the WebSocket fails to open. Returns the envelope `{data: [...], error: null}`. |
| `/api/sessions/<slug>/participants` | `POST` | **New.** Body: `{email: string}`. Resolves the `@dimagi.com` email to a `User` row (must already exist — users are created on first OAuth login). Creates `SessionParticipant(role='editor')`. Rejects non-`@dimagi.com` emails and emails that don't match any User with a `validation_error`. Owner only. |
| `/api/messages/<id>/stream` | `GET` | **Deleted.** SSE gone. |

All endpoints continue to use `apps.common.envelope.success_response` / `error_response`.

## 11. Settings and infrastructure

### 11.1 `config/settings/base.py`

- `CHANNEL_LAYERS` changes from `InMemoryChannelLayer` to `channels_redis.core.RedisChannelLayer` pointing at `env("REDIS_URL", default="redis://localhost:6379/0")`.
- Adds `ACE_REDIS_URL` (same default) consumed by `apps/common/redis_client.py` for presence and stop-event keys.
- `MIDDLEWARE` is unchanged (HTTP auth is unchanged).

### 11.2 `config/settings/connectlabs.py`

- Removes the `InMemoryChannelLayer` WARNING comment carried from `production.py` once the base switchover lands.
- No other changes — `REDIS_URL` is read by `base.py` from env, populated by ECS from Secrets Manager.

### 11.3 `config/settings/test.py`

- Overrides `CHANNEL_LAYERS` back to `InMemoryChannelLayer` for speed and isolation.
- Tests that exercise `presence.py` use `fakeredis.aioredis.FakeRedis` via a pytest fixture that patches `apps.common.redis_client.get_redis()`.

### 11.4 `docker-compose.yml`

Adds:

```yaml
  redis:
    image: redis:7-alpine
    ports: ["6380:6379"]
```

Web service env gains `REDIS_URL=redis://redis:6379/0`.

### 11.5 `pyproject.toml`

- Add `channels-redis~=4.2` to main dependencies.
- Add `fakeredis~=2.23` to dev dependencies.
- No other changes.

### 11.6 AWS task definition

`deploy/aws/task-definition.json` gains a `REDIS_URL` env var sourced from an AWS Secrets Manager ARN. No new AWS resources — the connect-labs ElastiCache is already provisioned per `docs/learnings/channels-single-instance.md`.

### 11.7 ECS desired count

This plan **does not** raise the ECS desired count. Landing the consumer with channels-redis unblocks scale-out but the actual increase to 2 tasks is a post-merge operational step with a soak/canary. The `channels-single-instance.md` learning is updated to reflect the new state:

> **Resolved in Phase 3.** The channel layer is now `RedisChannelLayer` pointing at shared ElastiCache. Scale-out is safe; bump the ECS desired count in the task definition separately from the code deploy.

## 12. Error handling

| Case | Behavior |
|---|---|
| Unauthenticated ws connect | `accept()` + `close(4001)` |
| Not a participant | `accept()` + `close(4003)` |
| Session slug not found | `close(4004)` |
| Viewer sends `chat.*` or `draft.*` | `session.error code=forbidden`, socket stays open |
| Unknown `action` | `session.error code=bad_request` |
| `draft.update` with stale `version` | `session.error code=draft_version_mismatch, detail={current_version, current_body}`; client replaces local body |
| `draft.take_over` on a live lock | `session.error code=draft_lock_held, detail={holder_user_id, expires_at}` |
| `chat.send` with no open draft | silently ignored (race with another user's send) |
| CLIBackend circuit breaker open | turn driver yields `ERROR` event → `chat.stream_error` broadcast, Message row set to `status='error'` |
| CLIBackend subprocess hangs on stop | SIGTERM → 2 s grace → SIGKILL (same as Phase 2); partial plaintext preserved; `chat.stream_cancelled` broadcast |
| Two drivers race on one assistant message | Impossible by construction. Only `chat.send` spawns a driver; `commit_active_draft` is under `SELECT FOR UPDATE` on the session row; the driver is the sole writer after `status='streaming'`. |
| Redis unreachable | Consumer logs, closes the socket with `1011`. HTTP `/api/health` stays green (does not touch the channel layer). No in-memory fallback — fail loud is correct here. |

## 13. Testing

New test modules:

- `apps/sessions/tests/test_consumers.py` — one `WebsocketCommunicator` drives the consumer through a full happy path (connect → session.state → draft.update → chat.send → stream deltas → stream_complete). A second test uses two communicators as Alice and Bob and asserts that Alice's `draft.update` is received on Bob's socket with the correct `last_editor_id`. A third test covers `draft.take_over` success and denial paths. A fourth covers `chat.stop` cross-consumer (Alice sends, Bob stops).
- `apps/sessions/tests/test_drafts.py` — unit tests for `commit_active_draft`, `update_body` (version mismatch), `claim_lock` (idle, live, forced-on-absent-holder), `discard`. No WebSocket involved.
- `apps/sessions/tests/test_presence.py` — `fakeredis` tests for `touch`/`leave`/`snapshot`/`is_present`, including the TTL sweep-on-read and the debounced `last_seen_at` write.
- `apps/sessions/tests/test_turn_driver.py` — lifted from `test_streaming.py`. Stubs `ChatBackend` with a scripted sequence and asserts the event stream + DB state. No HTTP.
- `apps/common/tests/test_channels_auth.py` — feeds fake ASGI scopes with and without a valid session cookie, asserts `scope['user']` resolution.

Modified tests:

- `apps/sessions/tests/test_views.py` — drops `send_message` cases; adds `GET /api/sessions/<slug>/messages` and `POST /api/sessions/<slug>/participants` cases (non-`@dimagi.com` rejection, unknown email rejection, duplicate participant, viewer trying to add a participant).

Deleted:

- `apps/sessions/tests/test_streaming.py`.

All tests use `pytest-asyncio`. The `WebsocketCommunicator` tests set `settings.CHANNEL_LAYERS = InMemoryChannelLayer` via the `test.py` override.

## 14. Docs and learnings

- `docs/learnings/channels-single-instance.md` — updated header: `**Status**: Resolved in Phase 3 (<date>, PR #<n>)`. Body gains a "Resolution" section pointing at the new settings and the two new learnings.
- `docs/learnings/channels-websocket-auth.md` — NEW. Captures the ASGI session-cookie auth middleware pattern, the tenant-specific `sessionid_ace` cookie sensitivity, and the `sync_to_async` user-resolution gotcha.
- `docs/learnings/redis-presence-hash.md` — NEW. Captures the HASH-with-TTL-per-field pattern, lazy sweep semantics, and the debounced Postgres writer for `last_seen_at`.
- `CLAUDE.md` — Phase 3 row flipped to `Done` at merge time; new learnings added to the list in the "Learnings" section; "What does NOT ship yet" bullet about WebSocket/drafts/presence removed.

## 15. Rollout

1. Land the channels-redis swap, the consumer, and the frontend hook in one PR (Phase 3 is a coherent unit; fractured landing has no incremental user benefit — see memory "Ship features complete on first pass").
2. Deploy via the existing `deploy-labs.yml` workflow with `run_migrations: false` (no schema changes).
3. Smoke-test: open a session in two browsers as two different `@dimagi.com` accounts, add the second user via "Add teammate", exercise draft editing, hand-off, send, mid-stream stop, and reconnect-during-stream.
4. Separately, raise the ECS desired count to 2 and monitor for group-send correctness over ~30 min of dogfooding.
5. Only then flip the `channels-single-instance.md` learning to `Resolved` and update `CLAUDE.md`.

## 16. Open risks

- **ALB WebSocket idle timeout.** The shared connect-labs ALB has a default 60 s idle timeout on WebSocket connections. The 20 s heartbeat keeps the connection alive, but if the user's tab is backgrounded for >60 s, the ALB closes the socket. The frontend reconnect-with-backoff handles this transparently but we need to verify the reconnect path is smooth in practice.
- **Two sends racing on one session.** Both Alice and Bob could hit Send within the same millisecond. The `SELECT FOR UPDATE` on the session row serializes them; the second committer gets a fresh empty draft and sees no open draft in `slot='next', status='open'` — the consumer silently ignores the second `chat.send`. This is correct behavior but worth verifying in a test.
- **`presence.last_seen_at` debounce across tasks.** With two ECS tasks, two consumers on different tasks can both race on the 30 s debounce SETNX. Redis SETNX is atomic, so only one wins and writes the DB row; the other sees the key exists and skips. Correct.
- **Turn driver cancellation signal.** Using a Redis string key polled on every loop adds ~5 ms latency to every yield. Acceptable (deltas are dozens per second at most). Alternative — a per-turn Channels group the turn driver subscribes to — is more complex for no real benefit.

## 17. References

- Whole-vision spec: `docs/specs/2026-04-08-ace-web-design.md` (§4.3 Multi-player collaboration, §5.2 Streaming transport, §5.3 Persistence).
- Phase 2 plan (reusable streaming code): `docs/plans/2026-04-08-2-conversation-engine.md`.
- Phase 2 SSE implementation (source of `turn_driver.py`): `apps/sessions/streaming.py`.
- Existing learnings: `docs/learnings/channels-single-instance.md`, `docs/learnings/sse-django-async.md`, `docs/learnings/cli-stream-json-format.md`.
- Pattern source for Channels-with-Django-auth: `../canopy-web/` (no direct port; the canopy-web WebSocket consumer shape is the reference for the auth middleware layering).
