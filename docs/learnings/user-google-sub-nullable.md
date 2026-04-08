# Learning: `User.google_sub` must be NULL, never empty string

**Date**: 2026-04-08
**Context**: Plan 1A post-execution review (fixes #8 and #9). `apps/auth/managers.py` and `apps/auth/middleware.py`.
**Status**: Resolved — guarded by tests, but the failure mode is easy to re-introduce

## Problem

`User.google_sub` has a `UNIQUE` constraint. If `create_user` stores an empty string `""` instead of `NULL` when no `google_sub` is available, the second user created without a sub collides on the UNIQUE constraint and raises `IntegrityError`.

Separately, the middleware's first-login path is racy: two concurrent requests for a brand-new user both fall through `User.DoesNotExist` and both call `create_user`, and the second one raises `IntegrityError` on the email UNIQUE constraint. Without handling, the second request 500s instead of finding the just-created row.

## Root Cause

In SQL, `NULL != NULL`, so many NULLs coexist under a UNIQUE constraint. Empty strings do not — two `""` values collide. Django's `CharField` stores `""` by default, which flows through to the DB without coercion.

Concurrent first-logins are a known race in any "get-or-create" middleware that does not handle the create-race at the DB layer.

## Fix / Key Takeaway

Two rules, both load-bearing:

1. **Coerce falsy `google_sub` to `None`** inside `UserManager.create_user` (`google_sub or None`). Any caller that passes `""`, `None`, or omits the field ends up with a NULL row. Covered by `test_two_users_without_google_sub_can_coexist`.
2. **Handle `IntegrityError` on the create path** inside `IAPHeaderAuthMiddleware._get_or_create_user`: catch it, re-`get` by email, and return that row. Covered by concurrent-first-login semantics in the existing tests.

When adding any new user-creation path (admin bulk import, management command, future API endpoint), apply both rules. The tests at `apps/auth/tests/test_models.py` are the regression harness — do not weaken them.

**Note (post GCP→AWS migration):** the google_sub field is now a legacy no-op — no IAP middleware populates it. Kept to avoid a schema migration. Will be removed in a future cleanup.
