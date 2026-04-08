# Learning: SSE in Django async views

**Date**: 2026-04-08
**Context**: Phase 2 implements `GET /api/messages/<id>/stream` as a Django async view returning `StreamingHttpResponse` with `text/event-stream`. There are several non-obvious gotchas.
**Status**: Active

## Problem

Streaming responses from Django async views to a browser via SSE has several layers that can buffer or break the stream.

## Root Cause

ASGI server defaults, proxy buffering, and HTTP middleware can all buffer or close streaming responses.

## Fix / Key Takeaway

For SSE to work end-to-end:

1. **Set `Cache-Control: no-cache` and `X-Accel-Buffering: no` on the response.** These tell intermediate proxies (Cloud Run's edge, nginx if you ever add one) not to buffer chunks.
2. **The middleware must allow streaming.** `IAPHeaderAuthMiddleware` does, because it's a thin wrapper around `get_response(request)`. Be careful adding any middleware that wraps the response body.
3. **uvicorn streams chunks immediately** by default.
4. **Use `sync_to_async` for ALL ORM access** inside the async view. A bare `Message.objects.get(...)` raises `SynchronousOnlyOperation`.
5. **Handle `asyncio.CancelledError` in the streaming generator.** It fires when the client disconnects. Catch it, mark the message as `error` with `cancelled` detail, wrap the cleanup DB write in `asyncio.shield` + `contextlib.suppress(CancelledError)` so it survives re-delivered cancellation during ASGI shutdown, then re-raise.
6. **Browser EventSource auto-reconnects on connection loss.** The reconnect semantics in `apps/sessions/streaming.py` handle this gracefully: `complete`/`error` messages replay and close; `streaming` messages replay and close (do NOT start a second backend drive — that would duplicate inference).
7. **Tests that consume `resp.streaming_content` from an async view** may see either a sync iterable or an async generator depending on Django's test client internals. The test helper in `apps/sessions/tests/test_streaming.py::_consume` handles both via `inspect.isasyncgen`.
8. **Django test client + async view + `sync_to_async` DB calls** can deadlock on SQLite's single-writer lock when wrapped in the default transactional test. Mark such tests with `@pytest.mark.django_db(transaction=True)`. PostgreSQL in production has no such issue.
9. **Monotonic `turn_index` allocation** under concurrent sends requires `Session.objects.select_for_update()` inside the transaction, or two concurrent POSTs will collide on the `unique_session_turn` constraint.
