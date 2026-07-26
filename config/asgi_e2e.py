"""ASGI entry point for Playwright E2E tests.

Two jobs:

1. Wraps the real ``config.asgi.application`` with a tiny prefix-
   stripping wrapper so that the frontend's hardcoded
   ``/ace/ws/opps/<slug>/...`` WebSocket URL reaches the Channels
   router, which registers the bare ``^ws/opps/...$`` pattern.

   In production, nginx strips the ``/ace/`` prefix from WebSocket
   handshakes before proxying to the Django container (see
   ``frontend/nginx.prod.conf``) — a detail documented in
   ``docs/learnings/channels-ws-proxy-path.md``. Vite does the same in
   local dev. Neither nginx nor Vite runs during the E2E suite, so we
   emulate the prefix strip here with a small wrapper that only
   touches ``scope["path"]`` on websocket scopes. (Originally added for
   the now-retired ``ws/sessions/<slug>/`` chat socket — see the PR that
   deleted apps/sessions/{consumers,drafts,presence,routing}.py in favor
   of canopy-hosted chat; the wrapper itself is path-generic and still
   serves the opp-workbench socket unchanged.)

2. Monkey-patches ``apps.common.redis_client.get_redis`` to return a
   process-local ``fakeredis.aioredis.FakeRedis`` instance so Redis-backed
   code (e.g. ``apps.common.nova_auth_flow``, ``apps.videos.service``,
   ``apps.mobile``) works without a real Redis during the E2E suite.
   Channels' channel layer already uses ``InMemoryChannelLayer`` via
   ``config/settings/e2e.py``.

This file is only referenced by ``config/settings/e2e.py`` and is not
imported by any production code path. It is safe to delete in prod.
"""
from __future__ import annotations

# Monkey-patch Redis BEFORE importing the asgi app, so any
# `from apps.common import redis_client` caller picks up the patched
# module reference.
import fakeredis.aioredis

from apps.common import redis_client as _redis_client_module

_FAKE_REDIS = fakeredis.aioredis.FakeRedis(decode_responses=True)


async def _fake_get_redis():
    return _FAKE_REDIS


_redis_client_module.get_redis = _fake_get_redis  # type: ignore[assignment]

from config.asgi import application as _inner_application  # noqa: E402

_WS_PREFIX = "/ace"


async def application(scope, receive, send):
    """ASGI callable that strips /ace from websocket paths before
    dispatching to the inner Channels application.

    HTTP requests pass through unchanged — ``FORCE_SCRIPT_NAME`` already
    handles HTTP routing. Only WebSocket scopes need prefix stripping
    because Channels' URL router operates on the raw ``scope["path"]``
    and ignores ``FORCE_SCRIPT_NAME`` (see the channels-ws-proxy-path
    learning).
    """
    if scope["type"] == "websocket":
        path = scope.get("path", "")
        if path.startswith(_WS_PREFIX + "/"):
            new_scope = dict(scope)
            new_scope["path"] = path[len(_WS_PREFIX):]
            # Also rewrite raw_path (bytes) if present, for consumers
            # that inspect it directly.
            raw = new_scope.get("raw_path")
            if isinstance(raw, bytes) and raw.startswith(_WS_PREFIX.encode() + b"/"):
                new_scope["raw_path"] = raw[len(_WS_PREFIX):]
            scope = new_scope
    await _inner_application(scope, receive, send)
