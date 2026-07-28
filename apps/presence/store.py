"""Redis-backed viewer presence: one HASH per page key.

Schema
------
    key    presence:<page_key>              key-level TTL 120s
    field  <user_id>.<connection_id>        per-connection, NOT per-user
    value  {"exp": <epoch>, "name", "email", "loc", "idle"}

Fields are per-connection so that a user with two tabs open on the same
page who closes one is not evicted from their own surviving tab's roster.
The reader dedupes by user id.

Values are denormalised (name and email inline) so building a roster costs
zero database queries.

The key-level TTL is leak insurance: if every client disconnects
ungracefully the hash self-destructs within two minutes rather than
lingering forever.

Every function here treats `redis_client.get_redis()` returning None (no
REDIS_URL configured) as "presence is unavailable" rather than an error:
touch()/forget() become no-ops and roster() returns an empty list. See
apps/common/redis_client.py's module docstring.
"""
from __future__ import annotations

import json
import time

from apps.common import redis_client  # module import — keeps monkeypatch working

FIELD_TTL_SECONDS = 60
KEY_TTL_SECONDS = 120


def _key(page_key: str) -> str:
    return f"presence:{page_key}"


def _field(user_id: int, connection_id: str) -> str:
    return f"{user_id}.{connection_id}"


async def touch(
    page_key: str,
    *,
    user_id: int,
    connection_id: str,
    name: str,
    email: str,
    sub_location: str,
    idle: bool,
) -> None:
    """Write/refresh this connection's presence on a page."""
    redis = await redis_client.get_redis()
    if redis is None:
        return
    payload = json.dumps({
        "exp": int(time.time()) + FIELD_TTL_SECONDS,
        "name": name,
        "email": email,
        "loc": sub_location,
        "idle": bool(idle),
    })
    pipe = redis.pipeline()
    pipe.hset(_key(page_key), _field(user_id, connection_id), payload)
    pipe.expire(_key(page_key), KEY_TTL_SECONDS)
    await pipe.execute()


async def forget(page_key: str, *, user_id: int, connection_id: str) -> None:
    """Remove exactly one connection. Other tabs of the same user survive."""
    redis = await redis_client.get_redis()
    if redis is None:
        return
    await redis.hdel(_key(page_key), _field(user_id, connection_id))


async def roster(page_key: str) -> list[dict]:
    """Current viewers, deduped by user, with a lazy sweep of expired fields.

    Known race (carried over from docs/learnings/redis-presence-hash.md): a
    concurrent touch during the read-then-HDEL window can evict a freshly
    refreshed entry. Self-heals on the next heartbeat; accepted.
    """
    redis = await redis_client.get_redis()
    if redis is None:
        return []
    raw = await redis.hgetall(_key(page_key))
    now = int(time.time())

    stale: list[str] = []
    by_user: dict[int, dict] = {}
    for field, value in (raw or {}).items():
        try:
            data = json.loads(value)
            user_id = int(str(field).split(".", 1)[0])
        except (ValueError, TypeError):
            stale.append(field)
            continue
        if int(data.get("exp", 0)) <= now:
            stale.append(field)
            continue
        entry = {
            "user_id": user_id,
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "sub_location": data.get("loc", ""),
            "idle": bool(data.get("idle")),
        }
        existing = by_user.get(user_id)
        # A user is idle only when EVERY one of their connections is idle:
        # one active tab means they are here.
        if existing is None:
            by_user[user_id] = entry
        elif not entry["idle"]:
            by_user[user_id] = entry

    if stale:
        await redis.hdel(_key(page_key), *stale)

    return sorted(by_user.values(), key=lambda e: (e["name"] or e["email"]).lower())
