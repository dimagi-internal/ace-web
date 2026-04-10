"""One place to build the shared async Redis client for channels-redis-
adjacent state (presence hashes, turn-stop signals, presence last-seen
debounce). Uses redis.asyncio directly (the same library channels-redis
depends on) so we do not pull in a second Redis client dependency.

Module-level cache: the client owns its own connection pool. Re-creating
it per-call would leak sockets. A single cached instance per process is
fine for ASGI workers.
"""
from __future__ import annotations

import redis.asyncio
from django.conf import settings

_client: redis.asyncio.Redis | None = None


async def get_redis() -> redis.asyncio.Redis:
    global _client
    if _client is None:
        _client = redis.asyncio.from_url(
            settings.ACE_REDIS_URL, decode_responses=True
        )
    return _client


async def close_redis() -> None:
    """Testing hook — close and reset the cached client."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
