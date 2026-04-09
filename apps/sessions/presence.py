"""Redis-backed presence for multi-player sessions.

Data layout:

  presence:{session_slug}             HASH
      field: str(user_id)             value: str(expires_at_epoch_seconds)

  presence.last_seen:{slug}:{user_id} STRING (30s TTL)
      presence-only; the existence of the key means "we already wrote
      SessionParticipant.last_seen_at within the last 30s for this
      (slug, user) pair; skip the DB write."

Why a HASH with per-field expires rather than Redis key TTLs:
- One key per session → O(1) connect/disconnect even with many sessions.
- No per-user key explosion.
- Lazy sweep on read is sufficient for our scale (a few team members per
  session at most).

The debounced last_seen_at write is a SETNX on a 30s TTL key. Atomic
across ECS tasks so only one of them writes the DB row even if two
consumers on different tasks receive a heartbeat for the same user in
the same ~30s window.

Note on imports: we import the redis_client module (not the get_redis
function) so tests can monkeypatch apps.common.redis_client.get_redis
and have the patch take effect inside this module. A `from X import Y`
style import would bind get_redis into this module's namespace and
bypass the patch.
"""
from __future__ import annotations

import time

from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.common import redis_client

from .models import SessionParticipant

PRESENCE_TTL_SECONDS = 60
LAST_SEEN_DEBOUNCE_SECONDS = 30


def _hash_key(session_slug: str) -> str:
    return f"presence:{session_slug}"


def _last_seen_key(session_slug: str, user_id: int) -> str:
    return f"presence.last_seen:{session_slug}:{user_id}"


async def touch(session_slug: str, user_id: int) -> bool:
    """Refresh this user's presence entry for this session.

    Returns True if the user was not present before this call (the field
    was newly added), False if they were already present.

    Also refreshes a key-level TTL (2× per-field TTL) so that if every
    participant hard-disconnects without a clean `leave` AND no surviving
    caller ever runs `snapshot`, the hash doesn't linger forever as an
    orphan key. In the normal path this TTL is irrelevant (the hash stays
    alive as long as anyone is present).
    """
    r = await redis_client.get_redis()
    key = _hash_key(session_slug)
    expires_at = int(time.time()) + PRESENCE_TTL_SECONDS
    # HSET returns the number of fields created — 1 for new, 0 for update.
    created = await r.hset(key, str(user_id), str(expires_at))
    await r.expire(key, PRESENCE_TTL_SECONDS * 2)
    return bool(created)


async def leave(session_slug: str, user_id: int) -> None:
    r = await redis_client.get_redis()
    await r.hdel(_hash_key(session_slug), str(user_id))


async def snapshot(session_slug: str) -> list[int]:
    """Return currently-present user_ids for this session.

    Lazily sweeps expired fields while it is reading the hash. O(n) in
    the number of fields per session — fine for our expected size.

    Note: there is a sub-millisecond race between HGETALL and HDEL — if
    a concurrent `touch` refreshes a field after we read but before we
    delete, we will delete the fresh value. The race is self-healing on
    the next heartbeat (~20 s), so users rarely notice and no state is
    lost beyond a single missed `presence.joined` broadcast. Accept it
    at this scale rather than reaching for a Lua script.
    """
    r = await redis_client.get_redis()
    key = _hash_key(session_slug)
    raw = await r.hgetall(key)
    now = int(time.time())
    alive: list[int] = []
    expired: list[str] = []
    for field, value in raw.items():
        try:
            if int(value) > now:
                alive.append(int(field))
            else:
                expired.append(field)
        except (TypeError, ValueError):
            expired.append(field)
    if expired:
        await r.hdel(key, *expired)
    return alive


async def is_present(session_slug: str, user_id: int) -> bool:
    r = await redis_client.get_redis()
    value = await r.hget(_hash_key(session_slug), str(user_id))
    if value is None:
        return False
    try:
        return int(value) > int(time.time())
    except (TypeError, ValueError):
        return False


async def maybe_record_last_seen(
    session_slug: str, user_id: int, *, session_pk: int
) -> bool:
    """Debounced write of SessionParticipant.last_seen_at.

    Returns True if this call wrote to the DB, False if skipped (a
    recent write is still within the debounce TTL).
    """
    r = await redis_client.get_redis()
    key = _last_seen_key(session_slug, user_id)
    # SET NX EX — succeeds only if the key does not already exist.
    acquired = await r.set(key, "1", ex=LAST_SEEN_DEBOUNCE_SECONDS, nx=True)
    if not acquired:
        return False
    await sync_to_async(_write_last_seen)(session_pk, user_id)
    return True


def _write_last_seen(session_pk: int, user_id: int) -> None:
    SessionParticipant.objects.filter(
        session_id=session_pk, user_id=user_id
    ).update(last_seen_at=timezone.now())
