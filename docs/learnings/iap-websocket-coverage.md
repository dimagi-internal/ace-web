# Learning: IAP middleware does not cover WebSocket handshakes

**Date**: 2026-04-08
**Context**: Plan 1A post-execution review (fix #11). Will become load-bearing in Plan 1C when the Sessions WebSocket consumer ships.
**Status**: Active — deferred to Plan 1C

## Problem

`apps.auth.middleware.IAPHeaderAuthMiddleware` reads `X-Goog-Authenticated-User-Email` and `X-Goog-Authenticated-User-ID` from the request and populates `request.user`. It works only on Django's HTTP middleware stack.

Django Channels' WebSocket handshake does not go through `__call__`. It goes through ASGI scope, via the Channels middleware pipeline (`ProtocolTypeRouter` / `AuthMiddlewareStack`). Without a parallel ASGI middleware, a WebSocket consumer in Plan 1C would receive an unauthenticated scope even though the user passed IAP at the edge.

## Root Cause

Two separate middleware pipelines in a Django + Channels ASGI app. Fixing only the HTTP one covers the REST API but silently leaves WebSockets unauthenticated.

## Fix / Key Takeaway

When Plan 1C adds the sessions consumer, also add an ASGI middleware that does the same IAP header extraction for WebSocket scopes (or mount it via a custom `AuthMiddlewareStack`-style wrapper). Without this, the WebSocket consumer will not have an authenticated user and session-scoped authorization checks will be impossible.

A `NOTE` comment already exists in `apps/auth/middleware.py:24-29` as a forward reference. Don't remove it until the ASGI path is covered.
