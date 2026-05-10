"""Cross-process singleton lock for the mobile-runner emulator.

Only one ace-web task may drive the (single) emulator instance at a time.
We use Redis ``SET NX EX`` with a 30 min TTL — long enough for the longest
plausible recipe run plus S3 upload, short enough that a stuck holder
clears within one CloudWatch alarm window.

Release uses a Lua compare-and-delete so a stuck holder whose TTL expires
can't accidentally delete a newer holder's lock. Pattern lifted from
``apps.common.nova_auth_flow``'s ``nova:refresh-lock``.

Sync (not async) because DRF function-views are sync. Uses the top-level
``redis`` package — not ``redis.asyncio``. ``apps/common/redis_client.py``
exists but is async-only.
"""
from __future__ import annotations

import secrets

import redis as _redis_sync
from django.conf import settings

LOCK_KEY = "mobile:emulator:lock"
LOCK_TTL_SECONDS = 1800  # 30 minutes

_LOCK_RELEASE_LUA = (
    "if redis.call('get',KEYS[1])==ARGV[1] then "
    "return redis.call('del',KEYS[1]) else return 0 end"
)


_sync_redis: _redis_sync.Redis | None = None


def _get_redis() -> _redis_sync.Redis:
    """Return a cached sync Redis client. Tests monkeypatch this attr."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = _redis_sync.from_url(
            settings.ACE_REDIS_URL, decode_responses=True
        )
    return _sync_redis


def make_owner(task_id: str | None = None, request_uuid: str | None = None) -> str:
    """Build an owner string for the lock value.

    ``task_id`` defaults to a short random hex (single-task dev / tests).
    ``request_uuid`` defaults to a short random hex per call.
    Format: ``<task-id>:<request-uuid>``.
    """
    return f"{task_id or secrets.token_hex(4)}:{request_uuid or secrets.token_hex(4)}"


def try_acquire(owner: str, ttl_seconds: int = LOCK_TTL_SECONDS) -> tuple[bool, str]:
    """Attempt to claim the singleton lock.

    Returns ``(acquired, current_owner)``. If ``acquired`` is True,
    ``current_owner`` is the value we just stored. If False, it's the
    value of the existing lock holder (or ``""`` if it expired between
    SETNX and GET, in which case the caller should treat it as contention
    and try again on the next request).
    """
    r = _get_redis()
    acquired = bool(r.set(LOCK_KEY, owner, nx=True, ex=ttl_seconds))
    if acquired:
        return True, owner
    current = r.get(LOCK_KEY) or ""
    return False, current


def release(owner: str) -> bool:
    """Release the lock iff we still own it. Returns True if released.

    Prefers an atomic Lua compare-and-delete; falls back to a
    ``WATCH`` + ``MULTI`` transaction when the Redis backend does not
    support ``EVAL`` (notably some fakeredis versions used in tests).
    The transactional fallback is also race-safe — Redis aborts the
    EXEC if another client modified the watched key between WATCH and
    EXEC, so we never delete a key whose value we didn't observe.
    """
    r = _get_redis()
    try:
        result = r.eval(_LOCK_RELEASE_LUA, 1, LOCK_KEY, owner)
        return bool(result)
    except Exception:
        # Fallback: WATCH + transactional GET / DEL.
        try:
            with r.pipeline() as pipe:
                pipe.watch(LOCK_KEY)
                current = pipe.get(LOCK_KEY)
                if current != owner:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(LOCK_KEY)
                result = pipe.execute()
                return bool(result and result[0])
        except Exception:
            return False


def current_owner() -> str:
    """Return the current lock holder, or ``""`` if unlocked. Test helper."""
    r = _get_redis()
    return r.get(LOCK_KEY) or ""


def ttl_seconds() -> int:
    """Return remaining TTL on the lock in seconds. ``-2`` if no key exists,
    ``-1`` if no TTL set. Test helper.
    """
    r = _get_redis()
    return int(r.ttl(LOCK_KEY))
