# Learning: ASGI session-cookie auth for WebSocket handshakes

**Date**: 2026-04-09
**Context**: Phase 3 `SessionConsumer` needs `self.scope["user"]` populated on the WebSocket handshake so it can enforce participant-only access and attribute draft edits to the right user.
**Status**: Active

## Problem

Django's `AuthenticationMiddleware` only runs on HTTP requests. On a WebSocket
handshake, the ASGI `scope` goes straight from the server to the Channels
`URLRouter` — no HTTP middleware touches it. Without an explicit ASGI-layer
middleware, `scope["user"]` is `AnonymousUser` even for users with a perfectly
valid session cookie, and the consumer's `connect()` has no identity to
authorize against.

This is documented in the Channels guide but it is easy to miss, and the
symptom (every WebSocket closes with `4001 unauthenticated`) looks at first
like a cookie or CORS problem.

## Why not `channels.auth.AuthMiddlewareStack`

Channels ships a ready-made `AuthMiddlewareStack` that does exactly this job.
We could have used it and the consumer tests would have passed. We wrote our
own thin wrapper (`apps/common/channels_auth.py::AceSessionAuthMiddleware`)
for two reasons:

1. **Tenant-specific cookie name.** Phase 2.5 renamed the Django session
   cookie to `sessionid_ace` in `config/settings/connectlabs.py` so scout and
   ace can share `labs.connect.dimagi.com` without colliding. The stock
   `AuthMiddlewareStack` reads `settings.SESSION_COOKIE_NAME`, which is
   correct — but having our own middleware makes the dependency on the
   tenant cookie name explicit and surfaces the `sessionid_ace` literal in
   the test file, so a future rename won't silently break WebSocket auth
   while HTTP continues to work.
2. **A seam for future extensions.** Phase 4 plans to allow share-token
   access to public read-only sessions. The auth middleware is the natural
   place to hook that in, alongside a participant pre-check that can reject
   with a 4003 close code before `connect()` even runs. Having our own
   middleware means we don't have to fork Channels later.

## Implementation pattern

`AceSessionAuthMiddleware.__call__` does:

1. Parse the `Cookie` header out of `scope["headers"]`. Cookie headers are
   bytes tuples (`(b"cookie", b"...")`) and HTTP/2 is allowed to split a
   single logical cookie across multiple headers, so accumulate all of them
   with `"; ".join(...)` before handing to `http.cookies.SimpleCookie`.
2. Read `settings.SESSION_COOKIE_NAME` and look up the matching value.
3. Instantiate `SessionStore(session_key)` (the configured session engine —
   database-backed for ace-web) and call `django.contrib.auth.get_user` on a
   tiny `_Req` shim whose only attribute is `session`. This is safe because
   `get_user` only touches `request.session`; reusing Django's helper means
   we inherit its `auth_user_model` lookups and any future changes to the
   auth framework's session handling.
4. Set `scope["user"]` to the resolved user (or `AnonymousUser()`), then
   delegate to the inner ASGI app.

## Robustness

Session stores can raise for a surprising variety of reasons: a stale cookie
pointing at a deleted row, a transient database hiccup, a corrupted session
blob from a partial write. The middleware wraps `SessionStore(...)` and
`get_user(...)` in a broad `try/except Exception` and falls through to
`AnonymousUser`. The consumer will then close the socket with `4001`, which
the client can react to (re-login redirect). This is intentional — a
WebSocket handshake is a bad place to surface a 500, and making the auth
middleware optimistic keeps presence/drafts resilient against intermittent
DB issues.

## Ordering in the ASGI stack

```python
# config/asgi.py
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))
    ),
})
```

`AllowedHostsOriginValidator` is outside the auth middleware on purpose:
cross-origin probes should be rejected before we hit the DB to look up a
session. This matters more under load than at steady state — a misconfigured
client hammering the handshake shouldn't also hammer the session store.

## Key files

- `apps/common/channels_auth.py` — the middleware + `AceSessionAuthMiddlewareStack` helper.
- `apps/common/tests/test_channels_auth.py` — covers valid cookie, missing
  cookie, bad session key, wrong cookie name, HTTP/2 split headers, and the
  corrupted-session fallback.
- `config/asgi.py` — the `ProtocolTypeRouter` wiring and ordering.
- `config/settings/connectlabs.py` — where `SESSION_COOKIE_NAME = "sessionid_ace"` lives.
