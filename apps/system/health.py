"""Operational health probes surfaced via ``GET /api/system/version``.

ace-web#636: a month of headless seeded runs silently died at Phase 3
because both Nova auth sources were dead and nothing surfaced it where
operators look. These helpers expose (a) Nova OAuth blob health and
(b) the container's ``op inject`` outcome so the iterate loop / doctor
can gate on them.

The Nova probe hits the live MCP endpoint, so its verdict is cached for
a short TTL (module-level, like ``version.py``'s remote lookup).
"""

from __future__ import annotations

import datetime
import time

# Module-level cache: {"nova_valid": (bool, monotonic_timestamp)}.
# Exposed so tests can clear it.
_cache: dict[str, tuple[bool, float]] = {}

_NOVA_PROBE_TTL_SECONDS = 60


def _cached_validate() -> bool:
    from apps.common import nova_auth_flow

    cached = _cache.get("nova_valid")
    if cached is not None:
        valid, ts = cached
        if (time.monotonic() - ts) < _NOVA_PROBE_TTL_SECONDS:
            return valid
    valid = nova_auth_flow.validate_token()
    _cache["nova_valid"] = (valid, time.monotonic())
    return valid


def nova_auth_health() -> dict:
    """Return ``{connected, valid, expires_at, last_refresh_error}``.

    ``connected`` — a credential blob is stored at all; ``valid`` — a live
    probe (cached ~60s) confirmed the token works; ``last_refresh_error``
    — the most recent refresh failure, cleared on the next success.
    """
    from django.core.cache import cache as django_cache

    from apps.common import nova_auth_flow

    blob = nova_auth_flow.get_blob()
    last_error = django_cache.get(nova_auth_flow.LAST_REFRESH_FAILURE_KEY)
    if not blob:
        return {
            "connected": False,
            "valid": False,
            "expires_at": None,
            "last_refresh_error": last_error,
        }
    raw_expires = blob.get("expires_at")
    if isinstance(raw_expires, (int, float)):
        expires_at: str | None = datetime.datetime.fromtimestamp(
            raw_expires, tz=datetime.UTC
        ).isoformat()
    else:
        expires_at = raw_expires
    return {
        "connected": True,
        "valid": _cached_validate(),
        "expires_at": expires_at,
        "last_refresh_error": last_error,
    }


def env_inject_health() -> dict:
    """Return ``{status, error}`` from the entrypoint's op-inject status file.

    ``docker-entrypoint.sh`` writes ``ok`` / ``failed`` / ``skipped`` (plus
    detail lines) to the status file at container start. No file (local dev,
    pre-upgrade tasks) → ``unknown``.
    """
    from django.conf import settings

    path = getattr(settings, "ACE_OP_INJECT_STATUS_PATH", "/tmp/op-inject.status")
    try:
        with open(path) as f:
            content = f.read(2000)
    except OSError:
        return {"status": "unknown", "error": None}
    first, _, rest = content.partition("\n")
    status = first.strip() or "unknown"
    detail = rest.strip() or None
    return {"status": status, "error": detail if status == "failed" else None}
