"""Smoke tests for the shared Redis client factory."""
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_get_redis_returns_same_instance_on_repeat_calls(settings):
    """The module caches one client per process so we don't leak pools."""
    settings.ACE_REDIS_URL = "redis://localhost:6379/0"
    from apps.common import redis_client

    # Reset the module-level cache to avoid leaking state from other tests.
    redis_client._client = None

    with patch("apps.common.redis_client.redis.asyncio.from_url") as from_url:
        fake = object()
        from_url.return_value = fake
        first = await redis_client.get_redis()
        second = await redis_client.get_redis()
        assert first is fake
        assert second is fake
        assert from_url.call_count == 1


@pytest.mark.asyncio
async def test_get_redis_reads_ace_redis_url(settings):
    settings.ACE_REDIS_URL = "redis://example:6379/7"
    from apps.common import redis_client

    redis_client._client = None
    with patch("apps.common.redis_client.redis.asyncio.from_url") as from_url:
        await redis_client.get_redis()
        from_url.assert_called_once_with(
            "redis://example:6379/7", decode_responses=True
        )
