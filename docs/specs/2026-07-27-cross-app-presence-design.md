# Cross-app viewer presence — design

**Date**: 2026-07-27
**Status**: Approved, not yet implemented
**Scope**: ace-web + canopy-web (shared frontend, separate backends)

## Problem

There is no way to tell who else is looking at the same thing you are. Two
people can open the same opp run, edit the same decision rows, and never know
the other is there. The Workbench already supports multi-player decision
editing over `OppConsumer`, and interactive chat moved to canopy specifically
to be multi-player — but neither surface answers "who else is here right now?"

Google Docs solves this with a compressed avatar cluster that expands into a
named list. We want the same affordance on every page of both apps.

Note: `frontend/src/components/views/PresenceStrip.tsx` looks like presence but
is not — it renders whoever last *edited* a decision row, sourced from
`decision.edited` events. It is unrelated to this feature and stays as-is.

## Product decisions

| Decision | Choice |
| --- | --- |
| Opt-in unit | Per-user visibility toggle. Feature is ON by default. Turning it off makes you invisible to others; you still see everyone else. |
| Grouping | Normalized logical resource, not exact URL. Everyone on the same opp run is one roster regardless of which step they're on; the expanded panel names each person's sub-location. |
| Apps | Both ace-web and canopy-web, same design. |
| Roster sharing | Separate rosters per app, shared frontend code. A chat session open in both apps shows two independent rosters — accepted blind spot. |
| Collapsed form | Up to 3 stacked initial-avatars + `+N` overflow. Renders nothing when you are alone. |
| Transport | Dedicated presence WebSocket. |

### Why a WebSocket and not HTTP polling

Polling was rejected on one specific ground: it cannot detect departures. A
poller shows a viewer who closed their tab until the TTL expires — up to 30
seconds of a confidently-wrong roster. Presence that is wrong is presence people
stop trusting, and an untrusted badge is worse than no badge.

With a socket, the disconnect *is* the departure signal. Both apps already run
Channels + channels-redis, both already have authenticated WebSocket handshake
middleware, and ace-web already proxies `/ace/ws/`. The infrastructure cost of
choosing the better UX is close to zero.

## Architecture

```
canopy-ui/presence   (authored in canopy-web/frontend/packages/canopy-ui)
   ├── <PresenceBadge />      stacked avatars + expand popover
   ├── usePresence()          one socket per tab, re-keys on navigation
   └── pageKeyFor(route)      pure function — the grouping brain
        │
        ├──> ace-web    apps/presence/  → ws/presence/ → ace-web Redis
        └──> canopy-web apps/realtime/  → ws/presence/ → canopy Redis
```

The badge mounts **once per app, in the shell** — `TopNav` in ace-web, the
canopy-ui `./shell` header in canopy-web. That is how "across all pages" is
satisfied with zero per-page work: no page component knows presence exists.

One socket per browser tab, not per page. Navigation sends a `presence.enter`
frame that re-keys the existing connection; it does not reconnect.

### Build ordering constraint

`canopy-ui` is authored inside canopy-web and consumed by ace-web as a version
pin (`canopy-ui@0.4.0` today; canopy-web is on 0.5.0). Therefore:

1. **canopy-web PR** — the `canopy-ui/presence` module + canopy's backend.
2. **canopy-ui version bump + publish.**
3. **ace-web PR** — backend + bump the `canopy-ui` pin + mount in `TopNav`.

ace-web's backend work does not depend on the frontend and can proceed in
parallel; only the mount step blocks on the bump.

### Where the backend lives

- **canopy-web**: inside the existing `apps/realtime/` app, next to
  `TurnConsumer` / `SupervisorConsumer` / `RunnerConsumer`. It reuses that app's
  `groups.py` and `channels_auth.py` conventions.
- **ace-web**: a new `apps/presence/` app. It does not belong in `apps/opps/`
  (which is opp-specific) and `apps/common/` is a utility grab-bag, not a home
  for consumers with routing.

## Page keys

A page key identifies a roster. It is derived client-side from the route by a
pure function and is app-namespaced even though rosters are separate — the
namespace costs nothing now and means a future merge into one roster is a
transport swap rather than a key migration.

```
ace:dimagi-team:opp:bednet-spot-check/run-001    ← every step of the run
ace:dimagi-team:videos:campaign-overview/run-003
ace:dimagi-team:activity
ace:dimagi-team:opps
ace:~global:settings
canopy:dimagi-team:session:<id>
```

Format: `<app>:<workspace-slug|~global>:<resource-type>[:<resource-id>]`

Every segment is charset-validated on the server before anything is joined
(`apps/presence/keys.py`, and its identical twin in canopy-web):
`app` `^[a-z0-9-]{1,32}$`, `workspace` `^[a-z0-9][a-z0-9_-]{0,63}$`, whole key
`<= 512` chars. The global sentinel is spelled `~global` precisely because the
leading `~` cannot match the workspace charset — workspace CREATION enforces
no charset at all, so a plain `global` sentinel would let anyone who could
name a workspace `global` bypass the membership gate for that tenant.

`pageKeyFor(pathname, search, routeTable)` is pure, takes a per-app route table,
and is the single place grouping correctness lives. It is the most
heavily-tested unit in the feature.

Alongside the key, the client sends a human-readable **sub-location** string
(`"idea-to-pdd"`, `"run overview"`, `"Templates"`) used only for display in the
expanded panel.

### Authorization — do not trust the page key

`page_key` arrives from the client. Without a check, a user could join an
arbitrary key and learn who is viewing a workspace they have no access to, or
announce themselves into one.

The consumer parses the workspace segment out of the page key and verifies
membership before joining the group. Malformed keys and non-member workspaces
are rejected — the enter frame is dropped and no group is joined. Keys in the
`~global` namespace (settings, system) skip the membership check, but only
after confirming no real workspace is named `~global` (charset validation
alone is insufficient, since slugs are unvalidated at creation).

The consumer also pins the `app` segment to its own app. Both apps' Redis
clients come from the same `REDIS_URL` on shared labs ElastiCache, so an
unpinned `app` would let an authenticated user of one app read and write the
sibling's rosters — with no membership check anywhere, since neither app can
see the other's memberships.

This mirrors the existing 404-not-403 posture: a rejected enter is silent, so
key existence is never confirmed.

## State

One Redis HASH per page key, following `docs/learnings/redis-presence-hash.md`.

```
key    presence:<page_key>                  (key-level TTL 120s)
field  <user_id>.<connection_id>            (field TTL 60s, carried in value)
value  {"exp": 1780000000, "name": "...", "email": "...",
        "loc": "idea-to-pdd", "idle": false}
```

- Client heartbeat every **20s**, field expiry **60s** — 3× ratio gives two
  heartbeats of slack for jitter.
- Key-level TTL of 120s is leak insurance: if every client disconnects
  ungracefully, the hash self-destructs rather than lingering.
- **Lazy sweep on read**: the roster read filters expired fields and pipelines
  an `HDEL` for what it dropped. No janitor job.
- Values are **denormalized** (name and email inline) so building a roster costs
  zero database queries.

### Fields are per-connection, not per-user

The field is `<user_id>.<connection_id>`, and the reader groups by user id.

This is deliberate. With a per-user field, a user with two tabs open on the same
page who closes one would `HDEL` themselves and vanish from their own surviving
tab's roster until its next heartbeat — up to 20 seconds of being invisible to
yourself. Per-connection fields make disconnect-cleanup exact.

### What we are NOT building

The `redis-presence-hash.md` pattern also describes a `SETNX`-debounced
Postgres `last_seen` write, for a "last seen 3 hours ago" library display. There
is no such requirement here. That half of the pattern is deliberately omitted.

### Channels group naming

`presence.<sha1(page_key)[:32]>`. Raw page keys contain `:` and `/`, which
Channels group names disallow (ASCII alphanumerics, hyphens, periods,
underscores; max 100 chars).

## Protocol

Client → server:

```jsonc
{"type": "presence.enter", "page_key": "...", "sub_location": "..."}
{"type": "presence.heartbeat", "idle": false}
```

Server → client:

```jsonc
{"event": "presence.roster",
 "data": {"page_key": "...",
          "viewers": [{"email": "...", "name": "...",
                       "sub_location": "...", "idle": false, "self": true}]}}
```

On any change — enter, disconnect, sub-location change, idle transition — the
server recomputes the full roster and broadcasts it to the group. Full-roster
broadcast is chosen over deltas: at a realistic ceiling of tens of viewers per
page the payload is trivial, and it removes an entire class of
client-state-drift bug.

`presence.enter` is idempotent and does double duty:

- **Different page key** than the connection currently holds → leave the old
  group, delete the field from the old page's hash, join the new group. This is
  navigation.
- **Same page key, different sub-location** → no group change; update the
  connection's field value in place and re-broadcast. This is moving between
  steps of the same run, which must not read as a leave-and-rejoin.

Disconnect discards the group and deletes the connection's field.

Idle transitions ride on `presence.heartbeat`, but the client sends an
**immediate** out-of-cycle heartbeat when `idle` flips in either direction
rather than waiting up to 20s for the next scheduled one.

## Visibility, enforced server-side

The per-user preference is read once on connect and held on the consumer.

- Preference **on** (default): normal — written to Redis, appears in rosters.
- Preference **off**: the consumer joins the group and receives every roster
  broadcast, but never writes the user into Redis.

Enforcement is server-side on purpose. A client-side filter would mean a
tampered or stale client could expose a user who opted out. The server is the
only thing that decides whether you are in a roster.

Storage: an identical `PresencePreference` model in each app — a `OneToOneField`
to the user plus a `show_presence` boolean defaulting to `true`. A dedicated
model rather than a user-table field because canopy-web uses Django's stock
`auth.User`, which we do not extend; mirroring the model in ace-web keeps the
two backends symmetric and touches neither user table.

Absence of a row means visible, so no backfill migration is load-bearing for
correctness. Surfaced as a single Settings row: **Show me as viewing**.

## Idle

A roster claiming five viewers when four have the tab buried behind other
windows is the same credibility failure that ruled out polling — it is just
slower to notice.

The client marks itself `idle` when `document.hidden` has been continuously true
for more than 2 minutes, and clears it immediately on visibility return. Idle
viewers render at reduced opacity and are labelled in the expanded panel.

This is intentionally coarse. It reports an observable fact (the tab is not
frontmost) and makes no claim about attention — consistent with the
observable-facts-only discipline in the Workspace Activity view.

## Failure behavior

Presence is an enhancement and never a hard dependency of a page.

- Socket fails to connect, or drops and cannot reconnect → the badge renders
  nothing. No toast, no error state, no retry storm.
- Redis unavailable → roster reads return empty; the page is unaffected.
- Reconnect uses the same backoff shape as `useOppSocket` (2s retry), and
  re-sends `presence.enter` for the current route on open.

This matches canopy's existing `publish()` helper, which degrades to a no-op
when no channel layer is configured — realtime never breaks a write.

## UI

**Collapsed** (in the shell's right-hand utility cluster, left of the workspace
switcher): up to 3 overlapping circular avatars showing initials, each with a
deterministic color derived from a hash of the email so a person is the same
color everywhere. More than 3 viewers collapses the remainder into a `+N`
circle. When you are the only viewer, nothing renders at all.

**Expanded** (click the cluster): a popover listing every viewer — you first,
marked `(you)` — with full name, sub-location, and idle state. Dismisses on
outside click or Escape.

Accessibility: the cluster is a `<button>` with an accessible label carrying the
count ("3 people viewing this page"); the popover is keyboard-navigable. Note
the trap documented in `card-click-and-grid-stretch.md` — do not nest this
button inside a `<Link>`.

## Testing

| Unit | Coverage |
| --- | --- |
| `pageKeyFor()` | vitest. Every route shape per app; step routes collapse to their run; unknown routes produce a stable fallback key. |
| Redis presence module | pytest + `fakeredis`. Touch/expire/lazy-sweep, per-connection field cleanup, two-tabs-one-page dedupe. |
| Consumer | `channels.testing.WebsocketCommunicator`. Unauthenticated reject; **foreign-workspace page key reject**; enter → roster broadcast to group; invisible user absent from roster but still receiving it; disconnect removes exactly one connection's field. |
| Badge | vitest + RTL. Renders nothing when alone; 3-avatar cap with `+N`; expand/collapse; idle styling. |

The `fakeredis` monkeypatch gotcha in `redis-presence-hash.md` applies and must
be followed: import the *module* (`from apps.common import redis_client`), never
the function, or the patch silently misses and tests hit a real Redis.

## Open risks

1. **canopy-ui version coupling.** ace-web pins canopy-ui, so the shared
   component cannot land in ace-web before it is published from canopy-web. The
   build ordering above manages this, but it makes the two PRs sequential at the
   mount step.
2. **Multi-task presence.** ace-web currently runs ECS desired count 1. The
   design is correct across tasks (Redis is the shared store, channels-redis is
   the shared group layer), but it has not been exercised at >1 task.
3. **The known `snapshot()` race** from `redis-presence-hash.md` carries over: a
   concurrent touch during the read-then-`HDEL` window can evict a fresh entry.
   Self-healing within one heartbeat. Accepted, same as before.
