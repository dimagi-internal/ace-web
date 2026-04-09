# Learning: FORCE_SCRIPT_NAME doesn't cover Channels URL routing

**Date**: 2026-04-09
**Context**: Phase 3 WebSocket handshake has to reach `SessionConsumer` through the `/ace/*` path prefix that the connect-labs ALB routes to this tenant.
**Status**: Active

## Problem

ace-web runs behind the shared connect-labs ALB under the path prefix
`/ace/*`. For HTTP traffic, `FORCE_SCRIPT_NAME = "/ace"` in
`config/settings/connectlabs.py` makes Django reverse URLs with the prefix,
so `{% url %}` tags and `reverse(...)` calls produce `/ace/api/...` without
the application code having to know.

That setting applies to Django's HTTP URL resolver. It does **not** apply
to Channels' WebSocket URL routing. A WebSocket handshake arrives at the
`ProtocolTypeRouter` with `scope["path"]` set to the raw path the server
received — `/ace/ws/sessions/<slug>/` if the ALB forwards the prefix,
`/ws/sessions/<slug>/` if something strips it first.

`apps/sessions/routing.py` registers:

```python
websocket_urlpatterns = [
    re_path(r"^ws/sessions/(?P<slug>[-\w]+)/$", SessionConsumer.as_asgi()),
]
```

If `scope["path"]` is `/ace/ws/sessions/foo/`, that pattern does not match
and the handshake closes with a 404-equivalent.

## Why this bites late

Every `SessionConsumer` test in the suite uses
`WebsocketCommunicator(application, "/ws/sessions/<slug>/")` — no prefix,
because there's no ALB in tests. The test suite therefore passes even when
prod is broken. The mismatch only manifests when a browser connects to
`wss://labs.connect.dimagi.com/ace/ws/sessions/<slug>/`.

Local dev through Vite exposes the same gap: the dev server mounts the
frontend at `/ace/` to mirror prod, and the browser connects to
`/ace/ws/...`.

## Fix

Strip the `/ace` prefix at the proxy layer. Django and Channels stay
deployment-agnostic — they keep thinking their WebSocket root is `/ws/`.

### nginx sidecar (`frontend/nginx.prod.conf`)

```nginx
location /ace/ws/ {
    proxy_pass http://127.0.0.1:8000/ws/;   # trailing slash rewrites the prefix
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $real_scheme;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

The trailing slash on `proxy_pass http://127.0.0.1:8000/ws/` is
load-bearing: it tells nginx to replace the matched `/ace/ws/` prefix with
`/ws/` rather than appending. The `Upgrade`/`Connection: upgrade` pair plus
`proxy_http_version 1.1` is required for WebSocket handshakes; without
them, nginx will send HTTP/1.0 and the Channels server will refuse to
upgrade. Long read/send timeouts keep idle connections alive across the
20 s heartbeat cadence.

### Vite dev proxy (`frontend/vite.config.ts`)

```ts
proxy: {
  "/ace/ws": {
    target: "ws://127.0.0.1:8000",
    ws: true,
    rewrite: (p) => p.replace(/^\/ace\/ws/, "/ws"),
  },
  // ...other /ace/api rules
}
```

Same rewrite, different syntax. `ws: true` tells Vite to proxy the
handshake instead of treating it as a plain HTTP request.

## Alternative approaches considered

1. **Mount the Channels router under `/ace/ws/...`.** Works, but couples
   the application routing to deployment topology. The moment the path
   prefix changes (e.g., a second deployment under `/ace2/`) the routing
   file has to change with it. The proxy approach keeps the server
   deployment-agnostic and mirrors how HTTP already works via
   `FORCE_SCRIPT_NAME`.
2. **An ASGI middleware that strips the prefix from `scope["path"]`.**
   Works and is localized to ASGI code, but adds a moving part inside the
   Python process that has to stay in sync with nginx's routing. If we
   ever need to add a second tenant prefix, we'd be editing two places.
3. **Channels URL patterns that accept both prefixed and bare forms.**
   Works until someone adds a new consumer and forgets the dual form.

The nginx/vite rewrite keeps the mapping in exactly one place per
environment and matches how HTTP is already handled.

## Key files

- `frontend/nginx.prod.conf` — the `location /ace/ws/` block.
- `frontend/vite.config.ts` — the dev proxy entry for `/ace/ws`.
- `apps/sessions/routing.py` — the `^ws/sessions/...$` pattern (note: NO
  `/ace` prefix in the regex).
- `config/asgi.py` — `ProtocolTypeRouter` + `AllowedHostsOriginValidator` wiring.
- `config/settings/connectlabs.py` — where `FORCE_SCRIPT_NAME = "/ace"` is set.
