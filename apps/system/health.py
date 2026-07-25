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


def _cached_probe(key: str, probe) -> bool:
    cached = _cache.get(key)
    if cached is not None:
        valid, ts = cached
        if (time.monotonic() - ts) < _NOVA_PROBE_TTL_SECONDS:
            return valid
    valid = probe()
    _cache[key] = (valid, time.monotonic())
    return valid


def nova_auth_health() -> dict:
    """Return the health of BOTH Nova auth paths.

    ``connected``/``valid``/``expires_at`` describe the OAuth blob;
    ``pat_present``/``pat_valid`` describe the user-scope PAT override
    (the preferred subprocess path); ``usable`` is the run-preflight
    verdict — at least one path yields a working bearer. Probes are
    cached ~60s. ``last_refresh_error`` is the most recent blob-refresh
    failure, cleared on the next success.
    """
    from django.core.cache import cache as django_cache

    from apps.common import nova_auth_flow

    blob = nova_auth_flow.get_blob()
    last_error = django_cache.get(nova_auth_flow.LAST_REFRESH_FAILURE_KEY)
    pat = nova_auth_flow.get_pat_key()
    pat_valid = bool(pat) and _cached_probe(
        "pat_valid", lambda: nova_auth_flow._probe_bearer(pat)
    )

    if not blob:
        blob_valid = False
        expires_at: str | None = None
    else:
        blob_valid = _cached_probe("nova_valid", nova_auth_flow.validate_token)
        raw_expires = blob.get("expires_at")
        if isinstance(raw_expires, (int, float)):
            expires_at = datetime.datetime.fromtimestamp(
                raw_expires, tz=datetime.UTC
            ).isoformat()
        else:
            expires_at = raw_expires
    return {
        "connected": blob is not None,
        "valid": blob_valid,
        "expires_at": expires_at,
        "last_refresh_error": last_error,
        "pat_present": bool(pat),
        "pat_valid": pat_valid,
        "usable": pat_valid or blob_valid,
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
