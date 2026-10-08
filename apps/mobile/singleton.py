"""Cross-process singleton lock for the mobile-runner emulator.

Only one ace-web task may drive the (single) emulator instance at a time.
We use Redis ``SET NX EX`` with a 30 min TTL — long enough for the longest
plausible recipe run plus S3 upload, short enough that a stuck holder
clears within one CloudWatch alarm window.

The lock itself is ``canopy_sdk.ondemand.Lease`` (compare-and-act release and
refresh, Lua with a WATCH/MULTI fallback); this module keeps the original
function names and the original Redis key so locks held across a deploy still
count. Release uses a Lua compare-and-delete so a stuck holder whose TTL expires
can't accidentally delete a newer holder's lock. Pattern lifted from
``apps.common.nova_auth_flow``'s ``nova:refresh-lock``.

Sync (not async) because DRF function-views are sync. Uses the top-level
``redis`` package — not ``redis.asyncio``. ``apps/common/redis_client.py``
exists but is async-only.
"""
from __future__ import annotations

import secrets

import redis as _redis_sync
from canopy_sdk.ondemand import Lease
from django.conf import settings

LOCK_KEY = "mobile:emulator:lock"
LOCK_TTL_SECONDS = 1800  # 30 minutes

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


def _lease(ttl_seconds: int = LOCK_TTL_SECONDS) -> Lease:
    # Built per call so tests that monkeypatch ``_get_redis`` are honoured.
    # ``key=`` pins the pre-extraction key name (the SDK default differs).
    return Lease(_get_redis(), "mobile", ttl_s=ttl_seconds, key=LOCK_KEY)


def try_acquire(owner: str, ttl_seconds: int = LOCK_TTL_SECONDS) -> tuple[bool, str]:
    """Attempt to claim the singleton lock.

    Returns ``(acquired, current_owner)``. If ``acquired`` is True,
    ``current_owner`` is the value we just stored. If False, it's the
    value of the existing lock holder (or ``""`` if it expired between
    SETNX and GET, in which case the caller should treat it as contention
    and try again on the next request).
    """
    lease = _lease(ttl_seconds)
    if lease.acquire(owner):
        return True, owner
    return False, lease.holder()


def release(owner: str) -> bool:
    """Release the lock iff we still own it. Returns True if released."""
    return _lease().release(owner)


def refresh(owner: str, ttl_seconds: int = LOCK_TTL_SECONDS) -> bool:
    """Reset the TTL on a lock we still own. Returns True if refreshed.

    Use case: a long ``ensure_running`` cold boot (3+ min budget) can
    eat a meaningful fraction of the 30-min default TTL before the
    actual recipe even starts. Refreshing after the cold boot returns
    gives the recipe its own fresh window so the lock doesn't
    silently expire mid-run and let a concurrent caller race in.
    """
    return _lease(ttl_seconds).refresh(owner)


def current_owner() -> str:
    """Return the current lock holder, or ``""`` if unlocked. Test helper."""
    return _lease().holder()


def ttl_seconds() -> int:
    """Return remaining TTL on the lock in seconds. ``-2`` if no key exists,
    ``-1`` if no TTL set. Test helper.
    """
    return int(_get_redis().ttl(LOCK_KEY))
