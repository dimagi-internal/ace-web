"""ASGI middleware that resolves `scope['user']` from a Django session
cookie on WebSocket handshake.

Channels ships its own `channels.auth.AuthMiddlewareStack` that does
something similar, but it hard-codes `settings.SESSION_COOKIE_NAME`
resolution through Django's session framework, which is fine — we
could use it directly. We define our own thin wrapper for two reasons:

1. Explicit control over the cookie-parsing step. The ace-web AWS
   deployment uses a tenant-specific cookie name (`sessionid_ace`) set
   in `connectlabs.py`. Wrapping the resolution in our own module makes
   that dependency visible and testable.
2. A single place to extend later (e.g., share-token fallbacks,
   per-session membership pre-checks before the consumer's connect()).

Usage (in config/asgi.py):

    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    })
"""
from __future__ import annotations

import logging
from http.cookies import SimpleCookie

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore

logger = logging.getLogger(__name__)


def _parse_cookie_header(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    """Parse all `cookie` headers from the ASGI scope into a single dict.

    HTTP/2 allows multiple Cookie headers and some proxies split them, so
    we accumulate across every matching header rather than returning on
    the first hit.
    """
    cookie = SimpleCookie()
    for name, value in headers:
        if name == b"cookie":
            cookie.load(value.decode("latin-1"))
    return {k: morsel.value for k, morsel in cookie.items()}


def _resolve_user_sync(session_key: str | None):
    """Resolve the session key to a User object (or AnonymousUser).

    Runs inside sync_to_async because it hits the DB. Any exception
    during session load or user resolution (corrupted session data,
    transient DB failure, auth-model mismatch) falls through to
    AnonymousUser so the WebSocket handshake can close cleanly from
    the consumer instead of crashing with a stack trace.
    """
    if not session_key:
        return AnonymousUser()
    try:
        session = SessionStore(session_key=session_key)
        # A fake sync HttpRequest-ish shim that get_user() can introspect.
        # django.contrib.auth.get_user reads `request.session` and checks
        # `_auth_user_id` + `_auth_user_backend` + `_auth_user_hash`.
        class _Req:
            pass

        req = _Req()
        req.session = session
        return get_user(req)
    except Exception:
        logger.warning(
            "channels_auth: failed to resolve session key; "
            "falling through to AnonymousUser",
            exc_info=True,
        )
        return AnonymousUser()


class AceSessionAuthMiddleware:
    """One-shot ASGI middleware. Attaches scope['user']."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        cookies = _parse_cookie_header(scope.get("headers", []))
        session_key = cookies.get(settings.SESSION_COOKIE_NAME)
        user = await sync_to_async(_resolve_user_sync)(session_key)
        scope = {**scope, "user": user}
        return await self.inner(scope, receive, send)
