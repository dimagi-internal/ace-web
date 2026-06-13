# Learning: ALB → nginx → Django HTTPS + Host-header traps

**Date**: 2026-04-09
**Context**: Discovered during the first live labs deploy and the first live OAuth initiate test. Two bugs in the same ALB → nginx sidecar → Django uvicorn hop. Both live in `config/settings/connectlabs.py` + `frontend/nginx.prod.conf`. Fixes merged in PRs #14 and #16.
**Status**: Resolved — guarded by the two fixes below, but both failure modes are silent until triggered in real infrastructure, so easy to re-introduce when editing nginx config or settings.

## Problem

Two independent breakages in the `ALB → nginx → Django` path that share root causes around TLS termination and Host rewriting:

1. **ALB health checks 400'd with `DisallowedHost`.** The ALB sends `Host: <target-private-ip>` on health checks (e.g. `Host: 10.0.1.133`). nginx was passing the Host header through unchanged. Django's `ALLOWED_HOSTS` (correctly) rejected it with `django.core.exceptions.DisallowedHost`, so every task stayed unhealthy and the first deploy attempt failed.

2. **OAuth initiate generated `http://` callback URLs instead of `https://`.** Django's `request.scheme` returned `http` because (a) `connectlabs.py` did not set `SECURE_PROXY_SSL_HEADER`, and (b) the nginx sidecar was overwriting `X-Forwarded-Proto` with `$scheme` (the internal ALB → nginx hop scheme, which is plain `http`), clobbering the `https` value the ALB correctly set. The result: `request.build_absolute_uri(...)` produced `http://labs.connect.dimagi.com/ace/auth/callback/`, which did not match the `https://...` redirect URI registered with Connect, and OAuth initiate bounced.

## Root Cause

The ALB terminates TLS at its edge. The internal ALB → nginx → Django hop is plain HTTP. Django has no way to know the *original* scheme was HTTPS unless:

- nginx **preserves** the ALB's `X-Forwarded-Proto: https` header (does not overwrite with `$scheme`), AND
- Django is told to **trust** that header via `SECURE_PROXY_SSL_HEADER`.

Separately, the ALB's health-check Host header is an IP, not a hostname, so `ALLOWED_HOSTS` rejects it unless nginx rewrites the Host to a known hostname before proxying to Django.

## Fix / Key Takeaway

Four pieces, all load-bearing:

1. **`config/settings/connectlabs.py` must set `SECURE_PROXY_SSL_HEADER`:**
   ```python
   SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
   ```
   Without this, Django's `request.scheme` is `http` regardless of what upstream sent.

2. **`frontend/nginx.prod.conf` must preserve the ALB's `X-Forwarded-Proto` via a `map` directive** — do NOT use `$scheme` directly:
   ```nginx
   map $http_x_forwarded_proto $real_scheme {
       default $http_x_forwarded_proto;   # preserve ALB's https
       ""      $scheme;                    # fall back for direct requests
   }
   # in every proxy_pass block:
   proxy_set_header X-Forwarded-Proto $real_scheme;
   ```
   The fallback handles direct-to-nginx requests (local curl, etc.) where no upstream header is set.

3. **`frontend/nginx.prod.conf` must rewrite Host to a known hostname in every proxy block:**
   ```nginx
   proxy_set_header Host $backend_host;          # e.g. labs.connect.dimagi.com
   proxy_set_header X-Forwarded-Host $host;      # preserve original for downstream code
   ```
   This keeps ALB health checks (which arrive with `Host: <private-ip>`) from tripping `ALLOWED_HOSTS`. The rewrite is safe because Django only uses the Host header for `ALLOWED_HOSTS` validation and `request.build_absolute_uri()`, both of which are fine with a consistent hostname.

4. **Apply the rewrite to every `proxy_pass` block** (api, auth, admin, static). Missing one means the ALB can still hit a route that 400s.

When adding any new nginx `location` + `proxy_pass` block, copy the full header set above. When adding a new prod settings module (or moving `connectlabs.py`'s responsibilities elsewhere), carry `SECURE_PROXY_SSL_HEADER` with it. The tests will not catch these failures — they only surface against real ALB + real https traffic.
