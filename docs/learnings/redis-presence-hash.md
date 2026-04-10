# Learning: Redis HASH presence with debounced Postgres last_seen writes

**Date**: 2026-04-09
**Context**: Phase 3 `apps/sessions/presence.py` tracks which users are currently connected to each session for live membership broadcasts and Phase 4 "last seen N hours ago" display in the session library.
**Status**: Active

## Problem

Presence has two audiences that pull in different directions:

1. **Live UX.** `SessionConsumer.connect()` needs a cross-task snapshot of
   "who is here right now" within a few milliseconds, and has to broadcast
   joins/leaves to the session group. That argues for an in-memory, shared,
   low-latency store — Redis.
2. **Durable last-seen.** The Phase 4 session library wants to show "Alice
   was here 3 hours ago" next to the session title. That argues for a
   Postgres column that survives the 60 s presence TTL.

Writing both stores on every 20 s heartbeat would DoS Postgres for no
reason, so there needs to be a debounce.

## Solution

### Redis side: HASH per session with per-field TTL

Key schema: `presence:{slug}` — one Redis HASH per session. Fields are
stringified user ids. Values are `expires_at` epoch seconds (not a boolean,
not a timestamp — the absolute expiry so the reader can make its own
decision).

- `touch(user_id)` does `HSET presence:{slug} {user_id} {now + 60}` plus
  `EXPIRE presence:{slug} 120`. The key-level TTL of 120 s (2× per-field)
  is a safety net: if every user disconnects ungracefully, the hash will
  self-destruct within two minutes instead of leaking forever.
- `snapshot()` does `HGETALL`, filters out expired fields, and pipelines an
  `HDEL` for anything it dropped. This "lazy sweep on read" keeps the
  backing store honest without needing a separate janitor job.
- `is_present(user_id)` does `HGET` and returns `False` if the field is
  expired, also pipelining an `HDEL` to clean up.
- Client heartbeat is every 20 s (well inside the 60 s TTL). The 3× ratio
  gives two heartbeats of slack for network jitter before presence drops.

### Postgres side: SETNX+EX debounce

Key schema: `presence.last_seen:{slug}:{user_id}` — one Redis STRING per
`(session, user)` pair. Value is irrelevant (we use `"1"`). The only thing
that matters is whether it exists.

- On every `touch`, try `SET key "1" NX EX 30`. The `NX` means "only set if
  not exists"; the `EX 30` expires the marker after 30 s.
- If `SET` returns success, this process is the winner. It updates
  `SessionParticipant.last_seen_at = timezone.now()` in Postgres.
- If `SET` returns nil, another process (or this process's previous
  heartbeat) already claimed the 30 s window. Postgres write is skipped.

This is atomic across all ECS tasks (Redis `SET NX` is single-threaded
inside the Redis core), so the worst case is one Postgres UPDATE per user
per 30 s regardless of how many heartbeats and how many tasks are in play.
At ten concurrent users that's one UPDATE per 3 s sustained — fine.

## Known race

`snapshot()` has a sub-millisecond window between `HGETALL` and the
pipelined `HDEL`: if a concurrent `touch` refreshes a field the reader was
about to delete, the `HDEL` will evict the freshly-refreshed entry. The
next `touch` from the same user re-adds them within 20 s, and the next
reader sees them again. Self-healing.

We accept this at ace-web's scale (tens of concurrent users per session at
the absolute peak). Fixing it would require a WATCH/MULTI/EXEC loop or a
Lua script, and the worst-case user experience is "presence indicator
flickers for one heartbeat once every blue moon." Not worth the
complexity.

## Testing pattern

Tests use `fakeredis.aioredis.FakeRedis` to stand in for the real Redis
connection, monkeypatched at the `apps.common.redis_client` module level:

```python
monkeypatch.setattr(
    "apps.common.redis_client.get_redis",
    lambda: fake_redis,
)
```

There is a subtle import gotcha. `apps/sessions/presence.py` imports the
module, not the function:

```python
from apps.common import redis_client  # good — references are resolved at call time

# NOT:
# from apps.common.redis_client import get_redis  # would bind locally and defeat the patch
```

The `from apps.common import redis_client` form means `redis_client.get_redis(...)`
is looked up on the module object at every call, so a `monkeypatch.setattr`
on the module attribute takes effect. The direct import form would bind
`get_redis` as a local name at import time, and the patch would have no
effect — leading to tests that hit the real Redis (or time out waiting for
a connection that doesn't exist).

## Key files

- `apps/sessions/presence.py` — the `touch`, `forget`, `snapshot`,
  `is_present` module-level functions.
- `apps/sessions/tests/test_presence.py` — uses `fakeredis.aioredis` with
  the module-level monkeypatch described above.
- `apps/common/redis_client.py` — the `get_redis()` singleton that all
  presence/channels layer usage goes through.
