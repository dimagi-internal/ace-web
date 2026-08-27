"""Fixed-window rate limiting on the Django cache.

Sized for one job: keeping a PUBLIC, unauthenticated write endpoint from
becoming a spam pipe. That is a different problem from API quota — there
is no account to attribute an over-limit to and no key to revoke — so the
control has to be cheap, per-client, and fail-open on cache trouble
rather than lock a real reviewer out because Redis blipped.

Fixed windows (not a sliding log) because the failure mode is benign: a
client can send up to 2× the limit across a window boundary. The
alternative costs a sorted set per client to defend a page that receives
a handful of comments a week.

The counter lives in the default cache (Redis in prod, locmem in tests).
It is NOT durable, and is not meant to be — a limiter whose state
survives a deploy is a limiter that can lock someone out for an hour
after a restart.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.http import HttpRequest

log = logging.getLogger(__name__)

_PREFIX = "ratelimit:v1:"


def client_ip(request: HttpRequest) -> str:
    """Best-effort client address.

    ace-web sits behind the shared connect-labs ALB, which appends the
    real client to ``X-Forwarded-For``; the FIRST entry is the client the
    ALB saw. This is spoofable by a determined actor (it is a request
    header), which is why it caps abuse rather than authenticating
    anyone — the other ceilings (per-record and per-run item counts) are
    what hold when someone rotates it.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    return str(request.META.get("REMOTE_ADDR") or "unknown")[:64]


def allow(bucket: str, *, limit: int, window_seconds: int) -> bool:
    """Consume one token from ``bucket``. False when the window is spent.

    Fails OPEN: a cache outage must not take the endpoint down with it.
    """
    key = f"{_PREFIX}{bucket}"
    try:
        added = cache.add(key, 1, timeout=window_seconds)
        if added:
            return True
        try:
            count = cache.incr(key)
        except ValueError:
            # Key expired between add and incr — treat as a fresh window.
            cache.set(key, 1, timeout=window_seconds)
            return True
        return count <= limit
    except Exception as exc:  # noqa: BLE001
        log.warning("rate_limit: cache unavailable for %s (%s) — allowing", bucket, exc)
        return True
