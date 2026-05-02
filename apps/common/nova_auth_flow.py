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
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

NOVA_BLOB_KEY = "nova_credentials_blob"
NOVA_CLIENT_KEY = "nova_oauth_client"

# Refresh access tokens this many seconds before they expire so a request
# in flight when we hand over the token doesn't 401 partway through.
NOVA_TOKEN_REFRESH_BUFFER = 300

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
    """
    blob = get_blob()
    if not blob:
        return None

    expires_at = int(blob.get("expires_at", 0))
    if int(time.time()) < expires_at - NOVA_TOKEN_REFRESH_BUFFER:
        return blob.get("access_token")

    refreshed = _refresh(blob)
    if refreshed is None:
        return None
    store_blob(refreshed)
    return refreshed.get("access_token")


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
        return None

    new = resp.json()
    # Some authorization servers omit refresh_token on refresh; preserve
    # the old one so we can still refresh next time.
    new.setdefault("refresh_token", refresh_token)
    return new


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
