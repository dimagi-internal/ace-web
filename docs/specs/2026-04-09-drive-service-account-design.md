# Drive Service Account — Design Spec

**Date:** 2026-04-09
**Status:** Approved for execution. Follow-up: implementation plan via writing-plans skill.
**Scope:** Replace the per-user Google OAuth flow that backs the ACE opportunity Workbench (`apps/opps/`) with a single shared service-account credential. Full delete of the old flow — no soft migration.

## 1. Overview

The ACE opportunity Workbench currently authenticates against Google Drive via a hand-rolled per-user OAuth flow ported from `../connect-search/`. Each Dimagi user grants Drive readonly + Sheets readonly scopes through a separate Google consent screen after signing into ace-web via CommCare Connect. Tokens are encrypted with a Fernet key and cached on the `User` row; a refresh loop runs on every Workbench request.

This spec replaces that whole flow with a single Google service account credential. The SA has already been granted read/write access to the shared ACE Shared Drive (the same drive the `ace` CLI uses), so every ace-web user sees the same Drive view regardless of which Google account they personally have. The SA key JSON is delivered to the process as a single environment variable, sourced from AWS Secrets Manager in production and a local `.env` file in development.

## 2. Motivation

- **The opps Workbench has never been smoke-tested against real Drive in production** (per `CLAUDE.md`). The user-OAuth flow is merged but the code path is cold. Replacing it now costs nothing in rollback risk.
- **`ace` (the sibling CLI plugin) already uses this SA** to read and write the same Shared Drive. Running two auth stories against the same data is a maintenance tax and a source of subtle permission drift.
- **The per-user flow adds substantial surface area** — a second OAuth callback, Fernet encryption, per-request token refresh, a frontend reconnect guard, a dedicated DRF permission, two User columns — for no user-facing benefit over "the Workbench shows the team's ACE folders."
- **One auth story is simpler to reason about.** CommCare Connect remains the identity boundary (`@dimagi.com` filter enforced in `apps/auth/oauth_views.py`); Drive is just "what the app reads" and needs no per-user consent.

## 3. Non-goals

- **Workload Identity Federation.** Google's published best practice for non-GCP workloads is WIF (no long-lived SA keys, short-lived tokens exchanged via ECS task role). It's the right long-term answer and should be picked up during the Phase 5 security review, but is explicitly out of scope here. The SA JSON key approach matches what `ace` CLI already does, so the short-term cost of a second auth pattern is avoided.
- **Write features in `GoogleDriveClient`.** The SA credentials are scoped to the full `drive` scope (not `drive.readonly`), so writes are *permitted* by auth. But the `GoogleDriveClient` surface stays read-only until a concrete feature needs to ship. No speculative API.
- **Multi-tenant SA support.** One SA, one shared drive, one set of credentials. No per-user, per-project, or per-environment SA distinction.
- **Rollback path.** The old `drive_token_cache` columns are dropped via migration; rolling back requires reverting the migration and the code. This is acceptable because the feature was never prod-active.

## 4. Architecture

### 4.1 Credentials loading

A single factory function in `apps/opps/drive_client.py`:

```python
@functools.cache
def get_drive_client() -> GoogleDriveClient:
    """Return the shared service-account-backed Drive client.

    Reads the SA key JSON from settings.ACE_DRIVE_SA_KEY_JSON at first
    call, constructs credentials scoped to the full 'drive' scope, and
    caches the client for the process lifetime. SA credentials do not
    mutate per-request, so a module-level cache is safe and eliminates
    the per-request overhead of constructing a fresh service object.
    """
    raw = settings.ACE_DRIVE_SA_KEY_JSON
    if not raw:
        raise DriveServiceAccountNotConfigured(
            "ACE_DRIVE_SA_KEY_JSON is not set"
        )
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"],
    )
    return GoogleDriveClient(creds)


class DriveServiceAccountNotConfigured(RuntimeError):
    pass
```

**Key design points:**

- **One client, process-wide.** SA credentials don't refresh per-request the way OAuth tokens do. `@functools.cache` gives a single shared `GoogleDriveClient` for the lifetime of the worker process. This removes the entire per-request decrypt → refresh → re-encrypt → instantiate sequence that `drive_for_request.py` used to perform.
- **Full `drive` scope.** Not `drive.readonly`. Matches the `ace` CLI's posture so a future write feature (e.g. ace-web creating a new run folder, writing a chat-seed artifact, moving files) doesn't need another auth change.
- **Factory lives next to the class.** `drive_client.py` becomes the single module for "how does the app talk to Drive." `drive_for_request.py`, `drive_credentials.py`, `drive_auth_views.py`, `encryption.py` all go away.
- **Failure mode is loud.** If the SA key is missing or malformed, `DriveServiceAccountNotConfigured` bubbles up to the view, which returns HTTP 500 with `error.code = "drive-not-configured"`. Not a user-recoverable state — it's a deploy-config bug and should be immediately visible to whoever shipped it. No reconnect URL, no retry UI.

### 4.2 Views and permissions

`apps/opps/views.py::_require_drive(request)` collapses from ~45 lines to ~10:

```python
def _require_drive(request):
    """Return (drive_client, error_response). error_response is None on success."""
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    try:
        return get_drive_client(), None
    except DriveServiceAccountNotConfigured as exc:
        return None, Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )
```

All seven opps view functions (`opp_list`, `workbench`, `step_detail`, `artifact_body`, `opp_compare`, `discuss`, `step_chats`) keep their exact shape — they still call `_require_drive(request)` and get back a client. Only the failure modes shrink.

The `RequireDriveToken` DRF permission (`apps/opps/middleware.py`) is deleted entirely. Authentication via CommCare Connect is the only gate; if you're logged in and you're `@dimagi.com`, you see the Workbench. The `@dimagi.com` filter remains enforced in `apps/auth/oauth_views.py`, unchanged.

### 4.3 Data model

Two columns on `apps.auth.User` go away:

- `drive_token_cache: TextField`
- `drive_token_refreshed_at: DateTimeField`

Plus the `has_drive_token()` method.

Migration: `apps/auth/migrations/0003_drop_drive_token_fields.py`, `RemoveField` for both columns. No data migration — the columns were never populated against real prod users.

### 4.4 Settings & secrets delivery

**`config/settings/base.py` delete:**

```python
ACE_DRIVE_TOKEN_ENCRYPTION_KEY
ACE_GOOGLE_OAUTH_CLIENT_ID
ACE_GOOGLE_OAUTH_CLIENT_SECRET
ACE_DRIVE_OAUTH_REDIRECT_URI
ACE_DRIVE_OAUTH_SCOPES
```

**`config/settings/base.py` add:**

```python
# --- Google Drive service account ---
# SA JSON key for the shared ACE Drive (read/write on the Shared Drive
# the SA has been granted access to). The whole JSON blob lives as a
# single string — parsed by apps.opps.drive_client.get_drive_client at
# first use. Sourced from AWS Secrets Manager in prod, .env in dev.
# Empty default: opps views return a 500 with code="drive-not-configured".
ACE_DRIVE_SA_KEY_JSON = env("ACE_DRIVE_SA_KEY_JSON", default="")
```

`ACE_DRIVE_ROOT_FOLDER_ID` and `ACE_DRIVE_ROOT_FOLDER_NAME` are unchanged — they still pin which folder the Workbench reads from.

**Local dev:** developer drops the SA key JSON into `.env` as a single-line JSON string. `.env.example` gets a placeholder showing the shape but no real key. `.env` is already in `.gitignore`.

**Prod deploy:**

1. One-time: create AWS Secrets Manager secret `labs-jj-ace-web-drive-sa-key-json` containing the SA JSON blob as a SecretString. Command added to `docs/deploy.md` under "Secrets setup."
2. Add one entry to `deploy/aws/task-definition.json`'s `secrets` array, referencing the new secret's ARN as `ACE_DRIVE_SA_KEY_JSON`.
3. Task execution role: verify the existing `labs-jj-ace-web-*` wildcard in the Secrets Manager resource policy covers the new secret name. Widen if not.
4. No new IAM roles, no new ECS infra.

### 4.5 Frontend

Delete:

- `frontend/src/components/opps/DriveReconnectGuard.tsx` — error boundary no longer needed.
- `DriveReconnectRequired` class and export in `frontend/src/api/types.ts`.
- The `drive-token-missing` 401 branch in `frontend/src/api/client.ts` (reverts the helper to a plain envelope parser).
- Five `<DriveReconnectGuard>` wrappers in `frontend/src/router.tsx` — the opps routes render their page components directly.

No replacement UI. A 500 from the opps API surfaces through the existing generic error handling. That's deliberately unfriendly because a missing SA key is a deploy bug, not a user-recoverable state.

## 5. Deletions

Full list for cross-reference during execution:

**Backend files deleted:**
- `apps/opps/drive_for_request.py`
- `apps/opps/drive_credentials.py`
- `apps/opps/drive_auth_views.py`
- `apps/opps/encryption.py`
- `apps/opps/middleware.py`

**Test files deleted:**
- `apps/opps/tests/test_drive_auth_views.py`
- `apps/opps/tests/test_drive_credentials.py`
- `apps/opps/tests/test_encryption.py`
- `apps/opps/tests/test_middleware.py`

**Frontend files deleted:**
- `frontend/src/components/opps/DriveReconnectGuard.tsx`

**Docs deleted:**
- `docs/learnings/drive-oauth-two-flow.md`

**URL routes removed from `apps/opps/urls.py`:**
- `auth/drive/start`
- `auth/drive/callback`

**Model fields removed (via migration `0003_drop_drive_token_fields`):**
- `User.drive_token_cache`
- `User.drive_token_refreshed_at`

**Settings removed:**
- `ACE_DRIVE_TOKEN_ENCRYPTION_KEY`
- `ACE_GOOGLE_OAUTH_CLIENT_ID`
- `ACE_GOOGLE_OAUTH_CLIENT_SECRET`
- `ACE_DRIVE_OAUTH_REDIRECT_URI`
- `ACE_DRIVE_OAUTH_SCOPES`

## 6. Tests

**Deleted:** `test_drive_auth_views.py`, `test_drive_credentials.py`, `test_encryption.py`, `test_middleware.py`.

**Updated — view test suites** (`test_views_opp_list`, `test_views_workbench`, `test_views_step_detail`, `test_views_artifact`, `test_views_compare`, `test_views_discuss`, `test_e2e_workflow`):

- Patch target switches from `apps.opps.views.get_drive_client_for` to `apps.opps.views.get_drive_client`.
- `user_with_token` fixtures collapse — no more `u.drive_token_cache = "ciphertext"`.
- The per-suite `test_*_requires_drive_token` cases are deleted and replaced with a single `test_*_unauthenticated_returns_401` case per file (the only remaining auth failure mode).
- One new case per suite (or a shared case in `test_drive_client.py`): `test_drive_not_configured_returns_500` that uses `override_settings(ACE_DRIVE_SA_KEY_JSON="")` and asserts `response.status_code == 500` and `error.code == "drive-not-configured"`.

**Updated — `test_drive_client.py`:** existing `GoogleDriveClient` method tests are unchanged. Add a new test class for `get_drive_client()`:

- Valid JSON key → returns a `GoogleDriveClient` (mock `service_account.Credentials.from_service_account_info` to avoid needing a real key file).
- Empty `ACE_DRIVE_SA_KEY_JSON` → raises `DriveServiceAccountNotConfigured`.
- Two calls return the same cached instance (verify `functools.cache` behavior; remember to `get_drive_client.cache_clear()` in test setup).

**Frontend tests:** there are no dedicated `DriveReconnectGuard` unit tests. The frontend deletions are covered by type-checking and the build.

## 7. Execution order

Seven sequential steps; each leaves the repo green.

1. **Add the new factory and settings.** Add `ACE_DRIVE_SA_KEY_JSON` to `config/settings/base.py`. Add `get_drive_client()` and `DriveServiceAccountNotConfigured` to `apps/opps/drive_client.py`. Add the factory unit tests in `test_drive_client.py`. Run `pytest` — green.
2. **Rewire views.** Update `apps/opps/views.py::_require_drive()` to call `get_drive_client()`. Update all six view test files: patch target, fixture cleanup, replace drive-token-gate cases with the drive-not-configured case. Run `pytest` — green.
3. **Delete the old backend flow.** Remove `drive_for_request.py`, `drive_credentials.py`, `drive_auth_views.py`, `encryption.py`, `middleware.py`. Remove their test files. Remove the two URL routes from `apps/opps/urls.py`. Remove the five old settings from `base.py`. Run `pytest` — green.
4. **User model migration.** Remove `drive_token_cache`, `drive_token_refreshed_at`, `has_drive_token()` from `apps/auth/models.py`. Generate `apps/auth/migrations/0003_drop_drive_token_fields.py` (`makemigrations`). Run `pytest` — green. Verify the migration applies cleanly against a Postgres dev instance.
5. **Frontend cleanup.** Delete `DriveReconnectGuard.tsx`, unwrap the five router routes, remove the `drive-token-missing` 401 branch in `api/client.ts`, delete the `DriveReconnectRequired` class in `api/types.ts`. Run the frontend build — green.
6. **Docs and deploy config.** Delete `docs/learnings/drive-oauth-two-flow.md`. Write `docs/learnings/drive-service-account.md`. Update the "ACE opportunity visualization" section of `CLAUDE.md` to remove the two-OAuth-flows language and point at the new learning. Add the `ACE_DRIVE_SA_KEY_JSON` secret entry to `deploy/aws/task-definition.json`. Update `docs/deploy.md` with the one-time Secrets Manager setup command.
7. **One-time ops** (manual — called out in the implementation plan, not performed by the agent): create the Secrets Manager secret, confirm task-role resource policy covers it, trigger a deploy with `run_migrations: true` to land the `0003` migration.

## 8. Risks and open questions

- **SA key rotation.** The JSON key is long-lived until manually rotated. Mitigation: Phase 5 security review should flag it and drive the migration to Workload Identity Federation. Rotation procedure: generate a new key in GCP console, update the Secrets Manager secret, force a task restart. Document in `drive-service-account.md`.
- **Shared Drive dependency.** The SA can only access what the Shared Drive's ACLs grant it. If someone accidentally removes the SA from the Shared Drive's members, the Workbench breaks with opaque 403s. Mitigation: the `drive-service-account.md` learning doc explicitly notes the Shared Drive membership requirement, and the existing `get_content` / `list_files` error handling surfaces Google API errors clearly enough to diagnose.
- **`functools.cache` and worker restarts.** The cache is per-process. Uvicorn workers recycle periodically; each new worker re-parses the JSON key on first opps request. This is fine (microsecond-scale work) but worth knowing for performance triage.
- **Test isolation with `functools.cache`.** Any test that patches `settings.ACE_DRIVE_SA_KEY_JSON` must call `get_drive_client.cache_clear()` in setup/teardown, otherwise a prior test's cached client leaks. Easy to get wrong — the test pattern in `test_drive_client.py` should demonstrate it once so other tests can copy.
- **Task-role Secrets Manager wildcard.** The assumption that `labs-jj-ace-web-*` in the task execution role policy covers the new secret needs verification before the deploy. If the policy is tighter, the Secrets Manager call at task startup will fail with a clear IAM error and the deploy will roll back cleanly.

## 9. References

- Current user-OAuth implementation: `apps/opps/drive_*.py`, `apps/opps/middleware.py`, `apps/opps/encryption.py`
- Existing learning being replaced: `docs/learnings/drive-oauth-two-flow.md`
- ACE-web design spec (context): `docs/specs/2026-04-08-ace-web-design.md`
- ACE opportunity visualization spec: `docs/specs/2026-04-08-ace-opp-visualization-design.md`
- Workbench implementation plan: `docs/plans/2026-04-08-ace-opp-workbench.md`
- Pattern source (service account usage): the `ace` CLI plugin at `../ace/`
- AWS deploy runbook: `docs/deploy.md`
- Task definition: `deploy/aws/task-definition.json`
