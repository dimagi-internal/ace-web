# Learning: All API responses use a `{data, error}` envelope

**Date**: 2026-04-08
**Context**: Plan 1A `apps/common/envelope.py`, inherited from `canopy-web`. Relevant to every endpoint added in Plan 1B and beyond.
**Status**: Active

## Problem

Mixed response shapes across endpoints (bare payload on success, Django's default `{detail: "..."}` on error, ad-hoc fields for validation) make the frontend branch on response shape per endpoint and make error handling inconsistent.

## Root Cause

Django / DRF defaults do not prescribe a single envelope. Without an explicit convention, each endpoint tends to invent one.

## Fix / Key Takeaway

Every response, success or failure, uses this shape:

```python
# apps/common/envelope.py
def success_response(data): return {"data": data, "error": None}
def error_response(message, code="error"): return {"data": None, "error": {"code": code, "message": message}}
```

Rules:

- **Every JSON endpoint** (REST, the health check, and the IAP middleware's 401 reject path) returns this shape. `apps/auth/middleware.py` already does this for `unauthenticated`.
- **Never** return a bare list or raw object; wrap it in `data`.
- **Never** return Django/DRF default error responses — map exceptions to `error_response(...)` in the view or a DRF exception handler.
- Error `code` is a short snake_case slug (e.g., `"unauthenticated"`, `"not_found"`, `"validation_error"`). The frontend branches on `error.code`, not `error.message`.

When Plan 1B adds the chat REST API, every new endpoint must use `success_response` / `error_response`. Any view that touches JSON and bypasses the envelope is a review-blocking defect.
