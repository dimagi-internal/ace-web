"""Nova MCP OAuth credential storage + refresh.

Nova is a remote HTTP MCP server (https://mcp.commcare.app/mcp) protected
by OAuth 2.1 + PKCE per the late-2025 MCP spec. Unlike the Claude
subscription where the CLI handles its own OAuth dance, here ace-web
runs the dance itself and injects bearer tokens into staged
``.mcp.json`` ``headers`` for each ``claude -p`` subprocess.

We use a single shared identity (``ace@dimagi-ai.com``), so this module
intentionally has no per-user tier — just one global blob in
``SystemConfig['nova_credentials_blob']``. RFC 8707 ``resource``
parameter is mandatory at both ``/authorize`` and ``/token`` — without it
the AS issues an opaque token and the MCP server rejects it as having
"no token payload".

Blob shape::

    {
      "access_token":  "<jwt>",
      "refresh_token": "<opaque>",
      "expires_at":    1234567890,   # unix seconds
      "scope":         "openid profile email offline_access nova.read ...",
      "token_type":    "Bearer",
      "obtained_at":   1234567890,
    }
"""
from __future__ import annotations

import json
import logging
import secrets
import time

import httpx
import redis as _redis_sync
from django.conf import settings

logger = logging.getLogger(__name__)

NOVA_BLOB_KEY = "nova_credentials_blob"
NOVA_CLIENT_KEY = "nova_oauth_client"

# Refresh access tokens this many seconds before they expire so a request
# in flight when we hand over the token doesn't 401 partway through.
NOVA_TOKEN_REFRESH_BUFFER = 300

# Concurrent-refresh serialization. Better-Auth (commcare.app's OAuth
# server) rotates refresh_tokens on every refresh, so two ECS tasks
# racing to refresh the same blob would burn each other's tokens — the
# loser gets `400 invalid_grant: session not found` and that user's
# Nova chat 401s. Serialize via a Redis SETNX lock; the loser polls
# the DB instead of POSTing /token itself.
NOVA_REFRESH_LOCK_KEY = "nova:refresh-lock"

# Django-cache key recording the most recent refresh failure so operators
# can see it (surfaced via /api/system/version — ace-web#636). Cleared on
# the next successful refresh.
LAST_REFRESH_FAILURE_KEY = "nova:last-refresh-failure"
NOVA_REFRESH_LOCK_TTL = 30  # seconds — /token RTT is sub-second normally
NOVA_REFRESH_WAIT_TIMEOUT = 5.0  # max wall-clock to wait for another task

_sync_redis = None


def _get_redis():
    """Return a cached sync Redis client. Tests monkeypatch this module attr.

    Uses the same connection URL as the async client (channels-redis) so
    everything talks to one Redis instance. Sync because get_fresh_token
    runs from CLIBackend._stage_env_for, which is called via sync_to_async.
    """
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = _redis_sync.from_url(
            settings.ACE_REDIS_URL, decode_responses=True
        )
    return _sync_redis

NOVA_DEFAULT_ISSUER = "https://commcare.app/api/auth"
NOVA_DEFAULT_RESOURCE = "https://mcp.commcare.app/mcp"
NOVA_DEFAULT_SCOPES = (
    "openid profile email offline_access "
    "nova.read nova.write nova.hq.read nova.hq.write"
)


def issuer() -> str:
    return getattr(settings, "NOVA_OAUTH_ISSUER", NOVA_DEFAULT_ISSUER)


def resource() -> str:
    return getattr(settings, "NOVA_MCP_RESOURCE", NOVA_DEFAULT_RESOURCE)


def scopes() -> str:
    return getattr(settings, "NOVA_OAUTH_SCOPES", NOVA_DEFAULT_SCOPES)


def authorize_url() -> str:
    return f"{issuer()}/oauth2/authorize"


def token_url() -> str:
    return f"{issuer()}/oauth2/token"


def register_url() -> str:
    return f"{issuer()}/oauth2/register"


# ── OAuth client (RFC 7591 dynamic registration) ──────────────────


def get_client(redirect_uri: str) -> dict:
    """Return the registered OAuth client, registering one if needed.

    Re-registers when the stored ``redirect_uris`` doesn't include the
    one we'd use now — registrations are bound to redirect URIs and the
    deploy URL can change between dev / labs / prod.
    """
    from .models import SystemConfig

    row = SystemConfig.objects.filter(key=NOVA_CLIENT_KEY).first()
    if row:
        try:
            client = json.loads(row.value)
            if redirect_uri in client.get("redirect_uris", []):
                return client
        except ValueError:
            pass

    body = {
        "client_name": "ace-web",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": scopes(),
    }
    resp = httpx.post(register_url(), json=body, timeout=10)
    resp.raise_for_status()
    client = resp.json()
    SystemConfig.objects.update_or_create(
        key=NOVA_CLIENT_KEY,
        defaults={"value": json.dumps(client)},
    )
    logger.info(
        "nova: registered OAuth client_id=%s for %s",
        client.get("client_id"),
        redirect_uri,
    )
    return client


def get_stored_client() -> dict | None:
    from .models import SystemConfig

    row = SystemConfig.objects.filter(key=NOVA_CLIENT_KEY).first()
    if not row:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


# ── Blob persistence ─────────────────────────────────────────────


def store_blob(blob: dict) -> None:
    """Persist the token blob, normalizing ``expires_at`` from ``expires_in``.

    Token endpoints return ``expires_in`` (seconds-from-now); we store
    ``expires_at`` (unix seconds) so the refresh check is a simple
    timestamp compare instead of having to remember when we fetched it.
    """
    from .models import SystemConfig

    blob = dict(blob)
    now = int(time.time())
    blob.setdefault("obtained_at", now)
    if "expires_in" in blob and "expires_at" not in blob:
        blob["expires_at"] = now + int(blob["expires_in"])

    SystemConfig.objects.update_or_create(
        key=NOVA_BLOB_KEY,
        defaults={"value": json.dumps(blob)},
    )
    logger.info(
        "nova: stored credential blob (expires_at=%s, scope=%s)",
        blob.get("expires_at"),
        blob.get("scope"),
    )


def get_blob() -> dict | None:
    from .models import SystemConfig

    row = SystemConfig.objects.filter(key=NOVA_BLOB_KEY).first()
    if not row:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def clear_blob() -> None:
    from .models import SystemConfig

    SystemConfig.objects.filter(key=NOVA_BLOB_KEY).delete()


# ── Refresh + access ─────────────────────────────────────────────


def get_fresh_token() -> str | None:
    """Return a non-expired access token, refreshing if needed.

    Returns None if no blob is stored or refresh fails. Callers staging
    a ``.mcp.json`` should treat None as "skip Nova MCP this spawn".

    Concurrency: serializes refresh across processes via Redis SETNX so
    Better-Auth's refresh_token rotation doesn't burn tokens between
    racing ECS tasks. See ``_refresh_with_lock`` for the algorithm.
    """
    blob = get_blob()
    if not blob:
        return None
    if _is_token_fresh(blob):
        return blob.get("access_token")
    return _refresh_with_lock()


def _is_token_fresh(blob: dict) -> bool:
    expires_at = int(blob.get("expires_at", 0))
    return int(time.time()) < expires_at - NOVA_TOKEN_REFRESH_BUFFER


def _refresh_with_lock() -> str | None:
    """Acquire the cross-process refresh lock, then refresh + persist.

    Two-phase race-resilient algorithm:
      1. Try to claim ``nova:refresh-lock`` via ``SET NX EX``. If we get
         it: re-read the blob (someone else may have just rotated it),
         and only POST /token if we still need to. Persist the rotated
         blob, release the lock.
      2. If the lock is held by another task, poll the DB at
         ``poll_interval`` until either (a) the holder rotates the blob
         and we can return its fresh access_token without refreshing,
         or (b) ``NOVA_REFRESH_WAIT_TIMEOUT`` elapses.

    Lock release uses a Lua compare-and-delete so a stuck holder whose
    TTL expires can't accidentally delete a newer holder's lock.

    Redis unavailability degrades to lockless refresh — strictly worse
    than the lock for multi-task deploys, but better than no Nova at all
    for single-task / dev. Logged at WARNING so it surfaces.
    """
    try:
        r = _get_redis()
    except Exception:
        logger.warning("nova: redis unavailable for refresh lock", exc_info=True)
        return _refresh_blob_then_store(get_blob())

    lock_token = secrets.token_hex(8)
    deadline = time.time() + NOVA_REFRESH_WAIT_TIMEOUT
    poll_interval = 0.2

    while time.time() < deadline:
        blob = get_blob()
        if not blob:
            return None
        if _is_token_fresh(blob):
            return blob.get("access_token")

        try:
            acquired = r.set(
                NOVA_REFRESH_LOCK_KEY, lock_token,
                nx=True, ex=NOVA_REFRESH_LOCK_TTL,
            )
        except Exception:
            logger.warning("nova: redis SET NX failed", exc_info=True)
            return _refresh_blob_then_store(blob)

        if acquired:
            try:
                # Re-read inside the lock — covers the race against a
                # task that JUST released and DB now has fresh tokens.
                blob = get_blob()
                if blob and _is_token_fresh(blob):
                    return blob.get("access_token")
                return _refresh_blob_then_store(blob)
            finally:
                _release_refresh_lock(r, lock_token)

        time.sleep(poll_interval)

    blob = get_blob()
    if blob and _is_token_fresh(blob):
        return blob.get("access_token")
    logger.warning("nova: refresh lock wait timeout — returning stale/no token")
    return None


def _refresh_blob_then_store(blob: dict | None) -> str | None:
    """POST /token, persist the rotated blob. Caller MUST hold the lock."""
    if not blob:
        return None
    refreshed = _refresh(blob)
    if refreshed is None:
        return None
    store_blob(refreshed)
    return refreshed.get("access_token")


# Lua script: delete the lock IFF its value is still the token we wrote.
# Prevents a task whose TTL has expired from deleting a newer holder's
# lock after it eventually wakes up.
_LOCK_RELEASE_LUA = (
    "if redis.call('get',KEYS[1])==ARGV[1] then "
    "return redis.call('del',KEYS[1]) else return 0 end"
)


def _release_refresh_lock(r, lock_token: str) -> None:
    try:
        r.eval(_LOCK_RELEASE_LUA, 1, NOVA_REFRESH_LOCK_KEY, lock_token)
    except Exception:
        logger.warning("nova: refresh-lock release failed", exc_info=True)


def _refresh(blob: dict) -> dict | None:
    refresh_token = blob.get("refresh_token")
    if not refresh_token:
        logger.warning("nova: stored blob has no refresh_token — can't refresh")
        return None

    client = get_stored_client()
    if not client:
        logger.warning("nova: no registered OAuth client — can't refresh")
        return None

    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client["client_id"],
        "resource": resource(),
    }
    if client.get("client_secret"):
        body["client_secret"] = client["client_secret"]

    try:
        resp = httpx.post(token_url(), data=body, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("nova: refresh failed — %s", e)
        _record_refresh_failure(str(e))
        return None

    new = resp.json()
    # Some authorization servers omit refresh_token on refresh; preserve
    # the old one so we can still refresh next time.
    new.setdefault("refresh_token", refresh_token)
    _clear_refresh_failure()
    return new


def _record_refresh_failure(error: str) -> None:
    """Persist the failure where /api/system/version can surface it (#636)."""
    from django.core.cache import cache

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        cache.set(LAST_REFRESH_FAILURE_KEY, f"{stamp}: {error}", None)
    except Exception:
        logger.debug("nova: could not record refresh failure", exc_info=True)


def _clear_refresh_failure() -> None:
    from django.core.cache import cache

    try:
        cache.delete(LAST_REFRESH_FAILURE_KEY)
    except Exception:
        logger.debug("nova: could not clear refresh-failure marker", exc_info=True)


# ── Validation ───────────────────────────────────────────────────


def validate_token() -> bool:
    """Probe the Nova MCP endpoint with the current token.

    Uses ``stream=True`` so the SSE response body doesn't block waiting for
    the keep-alive connection to close — we only care about the HTTP
    status of the initial response, not the event payload.
    """
    token = get_fresh_token()
    if not token:
        return False

    try:
        with httpx.stream(
            "POST",
            resource(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "ace-web", "version": "0.1"},
                },
            },
            timeout=10,
        ) as resp:
            return resp.status_code == 200
    except httpx.HTTPError as e:
        logger.info("nova: validate probe failed — %s", e)
        return False
