# Drive Service Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-user Google OAuth flow that backs the ACE opportunity Workbench with a single shared service account credential, delivered via AWS Secrets Manager in prod and a local `.env` in dev. Full delete of the old flow — no soft migration.

**Architecture:** Introduce a `get_drive_client()` factory in `apps/opps/drive_client.py` that reads a full SA key JSON from `settings.ACE_DRIVE_SA_KEY_JSON`, constructs `google.oauth2.service_account.Credentials` at the full `drive` scope, and caches the resulting `GoogleDriveClient` at module level via `functools.cache`. Every opps view calls this factory instead of the old per-user `get_drive_client_for(user)`. The old per-user OAuth files, the `RequireDriveToken` permission, the two `User` token columns, the frontend `DriveReconnectGuard`, and the user-OAuth learning doc are all deleted.

**Tech Stack:** Python 3.11, Django 5, DRF, `google-auth`, `google-api-python-client`, pytest-django, React 19 + TypeScript, AWS ECS Fargate, AWS Secrets Manager.

**Spec:** `docs/specs/2026-04-09-drive-service-account-design.md`

---

## File Structure

**Files created:**
- `apps/auth/migrations/0003_drop_drive_token_fields.py` — Django migration removing `drive_token_cache` and `drive_token_refreshed_at` from the `users` table.
- `docs/learnings/drive-service-account.md` — new learning doc explaining the SA approach, rotation procedure, and Shared Drive dependency.

**Files modified:**
- `config/settings/base.py` — delete 5 Google OAuth settings, add `ACE_DRIVE_SA_KEY_JSON`.
- `apps/opps/drive_client.py` — add `DriveServiceAccountNotConfigured`, `get_drive_client()`, imports for `json`/`functools`/`service_account`.
- `apps/opps/views.py` — replace `get_drive_client_for` and `CredentialsRefreshFailed`/`DriveTokenMissing` imports with `get_drive_client` and `DriveServiceAccountNotConfigured`; collapse `_require_drive`.
- `apps/opps/urls.py` — remove `drive_auth_views` import and `auth_urlpatterns`.
- `apps/auth/models.py` — remove `drive_token_cache`, `drive_token_refreshed_at`, and `has_drive_token()`.
- `apps/opps/tests/test_drive_client.py` — add factory unit tests.
- `apps/opps/tests/test_views_opp_list.py` — patch target swap, fixture cleanup, replace drive-token-gate case with drive-not-configured case.
- `apps/opps/tests/test_views_workbench.py` — same shape of edits.
- `apps/opps/tests/test_views_step_detail.py` — same.
- `apps/opps/tests/test_views_artifact.py` — same.
- `apps/opps/tests/test_views_compare.py` — same.
- `apps/opps/tests/test_views_discuss.py` — same (uses `patch.multiple`, lambda signature changes).
- `apps/opps/tests/test_e2e_workflow.py` — same (uses `patch.multiple`, lambda signature changes).
- `frontend/src/router.tsx` — remove `DriveReconnectGuard` import, unwrap 5 opps routes.
- `frontend/src/api/client.ts` — remove `drive-token-missing` 401 branch and `DriveReconnectRequired` import.
- `frontend/src/api/types.ts` — remove `DriveReconnectRequired` class.
- `config/urls.py` — remove the `drive_auth_urlpatterns` import and its spread.
- `deploy/aws/task-definition.json` — add `ACE_DRIVE_SA_KEY_JSON` to the `secrets` array.
- `docs/deploy.md` — add Secrets Manager creation command and SA key handling guidance.
- `CLAUDE.md` — update "ACE opportunity visualization" to drop "Two OAuth flows" language, point at new learning; add new learning to Learnings index.

**Files deleted:**
- `apps/opps/drive_for_request.py`
- `apps/opps/drive_credentials.py`
- `apps/opps/drive_auth_views.py`
- `apps/opps/encryption.py`
- `apps/opps/middleware.py`
- `apps/opps/tests/test_drive_auth_views.py`
- `apps/opps/tests/test_drive_credentials.py`
- `apps/opps/tests/test_encryption.py`
- `apps/opps/tests/test_middleware.py`
- `frontend/src/components/opps/DriveReconnectGuard.tsx`
- `docs/learnings/drive-oauth-two-flow.md`

---

## Task 1: Add `get_drive_client()` factory and setting (additive, nothing breaks)

**Files:**
- Modify: `config/settings/base.py:128-165` (settings block — delete 5, add 1 additional)
  - *Correction:* In this task, **only add** `ACE_DRIVE_SA_KEY_JSON`. The deletions happen in Task 3, after views and tests have been rewired.
- Modify: `apps/opps/drive_client.py` (append to existing file)
- Modify: `apps/opps/tests/test_drive_client.py` (append to existing file)

- [ ] **Step 1: Baseline — run the full test suite to confirm green starting state**

Run: `pytest -v`
Expected: all existing tests pass.

- [ ] **Step 2: Add the new setting in `config/settings/base.py`**

Insert the following block immediately after the `ACE_DRIVE_ROOT_FOLDER_ID = env(...)` definition (around line 165). The old settings above it stay untouched for now — they get deleted in Task 3 once they're unused.

```python
# --- Google Drive service account ---
# SA JSON key for the shared ACE Drive (read/write on the Shared Drive
# the SA has been granted access to). The whole JSON blob lives as a
# single string — parsed by apps.opps.drive_client.get_drive_client at
# first use. Sourced from AWS Secrets Manager in prod, .env in dev.
# Empty default: opps views return a 500 with code="drive-not-configured".
ACE_DRIVE_SA_KEY_JSON = env("ACE_DRIVE_SA_KEY_JSON", default="")
```

- [ ] **Step 3: Write the failing factory tests**

Append the following to `apps/opps/tests/test_drive_client.py`:

```python
# --- get_drive_client() factory tests ---

import json
from unittest.mock import MagicMock, patch

from django.test import override_settings

from apps.opps.drive_client import (
    DriveServiceAccountNotConfigured,
    GoogleDriveClient,
    get_drive_client,
)


@pytest.fixture(autouse=True)
def _clear_drive_client_cache():
    """Every test starts with an empty cache so settings patches apply."""
    get_drive_client.cache_clear()
    yield
    get_drive_client.cache_clear()


def _fake_sa_key_json() -> str:
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "ace-web@example.iam.gserviceaccount.com",
            "private_key": "FAKE",
            "project_id": "fake-project",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def test_get_drive_client_raises_when_setting_is_empty():
    with override_settings(ACE_DRIVE_SA_KEY_JSON=""):
        with pytest.raises(DriveServiceAccountNotConfigured):
            get_drive_client()


def test_get_drive_client_constructs_credentials_and_client():
    fake_creds = MagicMock(name="fake-creds")
    with override_settings(ACE_DRIVE_SA_KEY_JSON=_fake_sa_key_json()), \
         patch(
             "apps.opps.drive_client.service_account.Credentials.from_service_account_info",
             return_value=fake_creds,
         ) as mk_from_info, \
         patch.object(GoogleDriveClient, "__init__", return_value=None) as mk_init:
        client = get_drive_client()

    assert isinstance(client, GoogleDriveClient)
    mk_from_info.assert_called_once()
    args, kwargs = mk_from_info.call_args
    assert args[0]["type"] == "service_account"
    assert args[0]["client_email"] == "ace-web@example.iam.gserviceaccount.com"
    assert kwargs["scopes"] == ["https://www.googleapis.com/auth/drive"]
    mk_init.assert_called_once_with(fake_creds)


def test_get_drive_client_caches_client():
    fake_creds = MagicMock(name="fake-creds")
    with override_settings(ACE_DRIVE_SA_KEY_JSON=_fake_sa_key_json()), \
         patch(
             "apps.opps.drive_client.service_account.Credentials.from_service_account_info",
             return_value=fake_creds,
         ) as mk_from_info, \
         patch.object(GoogleDriveClient, "__init__", return_value=None):
        first = get_drive_client()
        second = get_drive_client()

    assert first is second
    # Second call should hit the cache; the SA constructor ran exactly once.
    assert mk_from_info.call_count == 1
```

- [ ] **Step 4: Run the factory tests — verify they fail with import errors**

Run: `pytest apps/opps/tests/test_drive_client.py -v -k "get_drive_client or not_configured"`
Expected: FAIL with `ImportError` because `DriveServiceAccountNotConfigured` and `get_drive_client` do not exist yet.

- [ ] **Step 5: Implement the factory in `apps/opps/drive_client.py`**

Add these imports near the top of `apps/opps/drive_client.py`, alongside the existing `import base64`:

```python
import functools
import json

from django.conf import settings
from google.oauth2 import service_account
```

Then append the following to the bottom of the file, after the `GoogleDriveClient` class:

```python
class DriveServiceAccountNotConfigured(RuntimeError):
    """Raised when ACE_DRIVE_SA_KEY_JSON is empty or unparseable.

    Bubbles up to the view layer, which converts it to a 500 response with
    error code "drive-not-configured". This is a deploy-config failure, not
    a user-recoverable state — there is no reconnect URL.
    """


@functools.cache
def get_drive_client() -> GoogleDriveClient:
    """Return the shared service-account-backed Drive client.

    Reads the SA key JSON from settings.ACE_DRIVE_SA_KEY_JSON at first
    call, constructs credentials scoped to the full 'drive' scope, and
    caches the resulting client for the lifetime of the worker process.
    Service account credentials do not mutate per-request (unlike OAuth
    access tokens), so a module-level cache is safe.

    Tests that patch ACE_DRIVE_SA_KEY_JSON must call
    get_drive_client.cache_clear() to force a rebuild.
    """
    raw = settings.ACE_DRIVE_SA_KEY_JSON
    if not raw:
        raise DriveServiceAccountNotConfigured(
            "ACE_DRIVE_SA_KEY_JSON is not set"
        )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DriveServiceAccountNotConfigured(
            f"ACE_DRIVE_SA_KEY_JSON is not valid JSON: {exc}"
        ) from exc
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"],
    )
    return GoogleDriveClient(credentials)
```

- [ ] **Step 6: Run the factory tests — verify they pass**

Run: `pytest apps/opps/tests/test_drive_client.py -v`
Expected: all tests in this file pass, including the three new ones.

- [ ] **Step 7: Run the full test suite — verify nothing else broke**

Run: `pytest -v`
Expected: all tests pass. The old per-user OAuth code path is still wired up and working; the new factory exists alongside it without being called from anywhere yet.

- [ ] **Step 8: Commit**

```bash
git add config/settings/base.py apps/opps/drive_client.py apps/opps/tests/test_drive_client.py
git commit -m "feat(opps): add service-account-backed Drive client factory

Additive: introduces get_drive_client() and ACE_DRIVE_SA_KEY_JSON setting.
Views still call the legacy per-user get_drive_client_for; the factory is
wired up in the next task."
```

---

## Task 2: Rewire views + view tests atomically

This is one commit because the views and their tests have to change together. After this task, `get_drive_client_for` is no longer called by any live code (though the file still exists — Task 3 deletes it).

**Files:**
- Modify: `apps/opps/views.py:1-96` (imports + `_require_drive` helper)
- Modify: `apps/opps/tests/test_views_opp_list.py` (patch target, fixture, gate case)
- Modify: `apps/opps/tests/test_views_workbench.py` (same)
- Modify: `apps/opps/tests/test_views_step_detail.py` (same)
- Modify: `apps/opps/tests/test_views_artifact.py` (same)
- Modify: `apps/opps/tests/test_views_compare.py` (same)
- Modify: `apps/opps/tests/test_views_discuss.py` (same; `patch.multiple` shape)
- Modify: `apps/opps/tests/test_e2e_workflow.py` (same; `patch.multiple` shape)

- [ ] **Step 1: Rewrite the imports block in `apps/opps/views.py`**

Replace lines 10-13:

```python
from apps.opps.drive_client import DriveClient
from apps.opps.drive_credentials import CredentialsRefreshFailed
from apps.opps.drive_for_request import DriveTokenMissing, get_drive_client_for
from apps.opps.middleware import RequireDriveToken
```

with:

```python
from apps.opps.drive_client import (
    DriveClient,
    DriveServiceAccountNotConfigured,
    get_drive_client,
)
```

- [ ] **Step 2: Rewrite `_require_drive` in `apps/opps/views.py`**

Replace the entire `_require_drive` function (currently lines 50-96) with:

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

- [ ] **Step 3: Update `apps/opps/tests/test_views_opp_list.py`**

Three changes to this file:

**3a.** Replace the `user_with_token` fixture (lines 15-20) with a fixture named `authed_user` (the "with_token" naming no longer makes sense):

```python
@pytest.fixture
def authed_user(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    return u
```

**3b.** In the `authed_client` fixture (lines 23-27), change `user_with_token` to `authed_user`:

```python
@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c
```

**3c.** Replace every `patch("apps.opps.views.get_drive_client_for", return_value=fake)` with `patch("apps.opps.views.get_drive_client", return_value=fake)`. There are two such lines in this file (around lines 42 and 56).

**3d.** Delete `test_opp_list_requires_drive_token` entirely (lines 67-75 — the one that asserts `response.json()["data"] == {"reconnect_url": "/auth/drive/start"}`). Replace it with:

```python
def test_opp_list_drive_not_configured_returns_500(authed_client):
    with override_settings(ACE_DRIVE_SA_KEY_JSON=""):
        from apps.opps.drive_client import get_drive_client
        get_drive_client.cache_clear()
        response = authed_client.get("/api/opps/")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "drive-not-configured"
```

And add at the top of the file, alongside the other imports:

```python
from django.test import override_settings
```

- [ ] **Step 4: Apply the same 4 changes to `test_views_workbench.py`, `test_views_step_detail.py`, `test_views_artifact.py`, `test_views_compare.py`**

For each of these four files, apply the same shape of changes:

a. Replace `user_with_token` fixture with `authed_user` (drop the `drive_token_cache = "ciphertext"` line — the fixture becomes two lines).
b. Update `authed_client` to take `authed_user`.
c. Replace every `get_drive_client_for` patch with `get_drive_client`.
d. Delete any `test_*_requires_drive_token` test case in that file (grep for `requires_drive_token` in the file; if present, delete it).
e. Add `from django.test import override_settings` to the imports if any of these files gains a `drive_not_configured` case.

**Note:** not every file has a `requires_drive_token` case. Only `test_views_opp_list.py` has one explicitly (confirmed via grep). For the other four files, (d) is a no-op.

After each file edit, there is no separate drive-not-configured case — the one in `test_views_opp_list.py` covers the 500 path for all six view functions (they all call the same `_require_drive`).

- [ ] **Step 5: Update `test_views_discuss.py`**

This file uses `patch.multiple` with a `get_drive_client_for=lambda user: fake` arg. The lambda signature changes because `get_drive_client` takes no args.

Changes:

**5a.** Replace the `authed_client` fixture (lines 16-23) with:

```python
@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(u)
    return c
```

**5b.** Replace the `_with_fake` helper (lines 26-31) with:

```python
def _with_fake(authed_client, fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client=lambda: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )
```

- [ ] **Step 6: Update `test_e2e_workflow.py`**

Same shape as Step 5.

**6a.** Replace the `authed_client` fixture (lines 20-27):

```python
@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(u)
    return c
```

**6b.** Replace `_patch_drive` (lines 35-40):

```python
def _patch_drive(fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client=lambda: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )
```

- [ ] **Step 7: Run the opps test suite**

Run: `pytest apps/opps/tests/ -v`
Expected: all tests pass. The old `get_drive_client_for` import in `drive_for_request.py` still exists but nothing in the live code path references it.

If any test fails with an `ImportError` referencing `get_drive_client_for` in a file you didn't update, grep again:
```
Run: grep -rn get_drive_client_for apps/opps/tests/
Expected: empty output after Step 6.
```

- [ ] **Step 8: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add apps/opps/views.py apps/opps/tests/test_views_opp_list.py \
        apps/opps/tests/test_views_workbench.py apps/opps/tests/test_views_step_detail.py \
        apps/opps/tests/test_views_artifact.py apps/opps/tests/test_views_compare.py \
        apps/opps/tests/test_views_discuss.py apps/opps/tests/test_e2e_workflow.py
git commit -m "refactor(opps): views call get_drive_client() service-account factory

All six Workbench views now build the Drive client from the shared SA
credential via get_drive_client() instead of per-user OAuth tokens via
get_drive_client_for(user). _require_drive collapses to ~10 lines;
drive-token-missing/reconnect paths are gone. Legacy per-user OAuth
modules are dead code after this commit — deleted in the next task."
```

---

## Task 3: Delete dead backend code, URL routes, and old settings

**Files:**
- Delete: `apps/opps/drive_for_request.py`
- Delete: `apps/opps/drive_credentials.py`
- Delete: `apps/opps/drive_auth_views.py`
- Delete: `apps/opps/encryption.py`
- Delete: `apps/opps/middleware.py`
- Delete: `apps/opps/tests/test_drive_auth_views.py`
- Delete: `apps/opps/tests/test_drive_credentials.py`
- Delete: `apps/opps/tests/test_encryption.py`
- Delete: `apps/opps/tests/test_middleware.py`
- Modify: `apps/opps/urls.py` (drop `drive_auth_views` import, drop `auth_urlpatterns`)
- Modify: `config/urls.py` (drop `drive_auth_urlpatterns` import and spread)
- Modify: `config/settings/base.py` (delete the 5 old Google OAuth settings)

- [ ] **Step 1: Delete the five backend module files**

```bash
git rm apps/opps/drive_for_request.py
git rm apps/opps/drive_credentials.py
git rm apps/opps/drive_auth_views.py
git rm apps/opps/encryption.py
git rm apps/opps/middleware.py
```

- [ ] **Step 2: Delete the four dead test files**

```bash
git rm apps/opps/tests/test_drive_auth_views.py
git rm apps/opps/tests/test_drive_credentials.py
git rm apps/opps/tests/test_encryption.py
git rm apps/opps/tests/test_middleware.py
```

- [ ] **Step 3: Update `apps/opps/urls.py`**

Change the imports line (line 4) from:

```python
from . import drive_auth_views, views
```

to:

```python
from . import views
```

Then delete the entire `auth_urlpatterns = [...]` block (lines 33-36, the three lines plus the trailing `]`).

- [ ] **Step 4: Update `config/urls.py`**

Remove the `drive_auth_urlpatterns` import (line 6) and its spread (line 13).

Before:
```python
from apps.opps.urls import auth_urlpatterns as drive_auth_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/", include("apps.sessions.urls")),
    path("api/opps/", include("apps.opps.urls")),
    *drive_auth_urlpatterns,
    path("auth/", include("apps.auth.urls")),
```

After (delete the `drive_auth_urlpatterns` import and its spread):
```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/", include("apps.sessions.urls")),
    path("api/opps/", include("apps.opps.urls")),
    path("auth/", include("apps.auth.urls")),
```

- [ ] **Step 5: Delete the five old settings in `config/settings/base.py`**

Delete the entire "Google Drive OAuth (secondary flow for the Workbench)" block — the header comment plus the five settings definitions:

```python
# --- Google Drive OAuth (secondary flow for the Workbench) ---
# Encryption key for the per-user Drive token cache. Rotated via AWS Secrets
# Manager / SSM Parameter Store in prod. In dev, a static key is fine.
ACE_DRIVE_TOKEN_ENCRYPTION_KEY = env(
    "ACE_DRIVE_TOKEN_ENCRYPTION_KEY",
    default="dev-insecure-drive-token-key-change-me",
)
# Google OAuth client credentials (registered in the dimagi GCP console with
# redirect URIs for both dev and prod). Same OAuth project connect-search uses
# unless there is a reason to mint a new one.
ACE_GOOGLE_OAUTH_CLIENT_ID = env("ACE_GOOGLE_OAUTH_CLIENT_ID", default="")
ACE_GOOGLE_OAUTH_CLIENT_SECRET = env("ACE_GOOGLE_OAUTH_CLIENT_SECRET", default="")
# Redirect URI the callback view builds. Relative to SITE_URL — dev default
# is local Django, prod is the AWS tenant under /ace/.
ACE_DRIVE_OAUTH_REDIRECT_URI = env(
    "ACE_DRIVE_OAUTH_REDIRECT_URI",
    default="http://localhost:8000/auth/drive/callback",
)
# Scopes requested for Drive access. Read-only — the Workbench never writes.
ACE_DRIVE_OAUTH_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
```

After the delete, the `# --- Google Drive service account ---` block from Task 1 should sit directly under the `ACE_DRIVE_ROOT_FOLDER_ID = env(...)` block. The `ACE_DRIVE_ROOT_FOLDER_NAME` and `ACE_DRIVE_ROOT_FOLDER_ID` settings stay — they still pin the shared folder.

- [ ] **Step 6: Verify no stragglers reference the deleted modules**

```
Run: grep -rn "drive_auth_views\|drive_for_request\|drive_credentials\|RequireDriveToken\|get_drive_client_for\|apps.opps.encryption\|ACE_DRIVE_TOKEN_ENCRYPTION_KEY\|ACE_GOOGLE_OAUTH\|ACE_DRIVE_OAUTH" apps/ config/ tests/
```
Expected: empty output (no references).

If anything lights up, it's a missed reference — fix it before moving on. The most likely candidate is an `__init__.py` that re-exports from a deleted module, though in this codebase none do.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass. The test count drops by ~25 (the four deleted test files).

- [ ] **Step 8: Commit**

```bash
git add -A apps/opps/ config/settings/base.py config/urls.py
git commit -m "refactor(opps): delete legacy per-user Drive OAuth flow

Removes drive_auth_views, drive_credentials, drive_for_request, encryption,
and middleware modules and their tests. Drops /auth/drive/{start,callback}
URL routes and the five ACE_GOOGLE_OAUTH / ACE_DRIVE_OAUTH settings. The
new service-account factory is the only path to Drive."
```

---

## Task 4: Drop User.drive_token_cache and drive_token_refreshed_at columns

**Files:**
- Modify: `apps/auth/models.py:14-19, 35-36` (remove fields + `has_drive_token` method)
- Create: `apps/auth/migrations/0003_drop_drive_token_fields.py` (auto-generated by `makemigrations`)

- [ ] **Step 1: Edit `apps/auth/models.py`**

Remove lines 14-19 (the comment block and the two field definitions):

```python
    # Per-user Google Drive OAuth token cache for the ACE opp Workbench
    # (apps/opps). Encrypted via apps.opps.encryption.encrypt_token; decrypted
    # on demand in drive_credentials.ensure_fresh. TextField because the
    # ciphertext is an opaque string, not JSON.
    drive_token_cache = models.TextField(blank=True, default="")
    drive_token_refreshed_at = models.DateTimeField(null=True, blank=True)
```

Also remove lines 35-36 (the `has_drive_token` method):

```python
    def has_drive_token(self) -> bool:
        return bool(self.drive_token_cache)
```

- [ ] **Step 2: Generate the migration**

Run: `python manage.py makemigrations ace_auth -n drop_drive_token_fields`
Expected: new file `apps/auth/migrations/0003_drop_drive_token_fields.py` created. The operations list should contain two `RemoveField` operations for `drive_token_cache` and `drive_token_refreshed_at`.

- [ ] **Step 3: Review the generated migration**

Open `apps/auth/migrations/0003_drop_drive_token_fields.py` and confirm it looks like:

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ace_auth", "0002_drive_token_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="drive_token_cache",
        ),
        migrations.RemoveField(
            model_name="user",
            name="drive_token_refreshed_at",
        ),
    ]
```

Field order in `operations` may differ — that's fine.

- [ ] **Step 4: Verify migrations still load cleanly**

Run: `python manage.py makemigrations --check --dry-run`
Expected: exit code 0 (no more pending changes).

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass. Tests use in-memory SQLite, so the fresh schema reflects the post-migration model.

- [ ] **Step 6: Commit**

```bash
git add apps/auth/models.py apps/auth/migrations/0003_drop_drive_token_fields.py
git commit -m "refactor(auth): drop User.drive_token_cache and drive_token_refreshed_at

Migration 0003_drop_drive_token_fields removes the two columns introduced
in 0002 for the old per-user Drive OAuth flow. The service-account approach
needs no per-user state, so these columns become dead schema."
```

---

## Task 5: Frontend cleanup

**Files:**
- Delete: `frontend/src/components/opps/DriveReconnectGuard.tsx`
- Modify: `frontend/src/router.tsx` (unwrap 5 routes, drop import)
- Modify: `frontend/src/api/client.ts` (drop drive-token-missing branch, drop import)
- Modify: `frontend/src/api/types.ts` (drop `DriveReconnectRequired` class)

- [ ] **Step 1: Delete the guard component**

```bash
git rm frontend/src/components/opps/DriveReconnectGuard.tsx
```

- [ ] **Step 2: Rewrite `frontend/src/router.tsx`**

Replace the entire file contents with:

```tsx
import { createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import HealthPage from "./pages/HealthPage";
import HomePage from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import OppComparePage from "./pages/OppComparePage";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <App />,
      children: [
        { index: true, element: <HomePage /> },
        { path: "health", element: <HealthPage /> },
        { path: "chat", element: <ChatRedirectPage /> },
        { path: "chat/:slug", element: <ChatPage /> },
        { path: "auth/cli", element: <AuthCliPage /> },
        { path: "opps", element: <OppListPage /> },
        { path: "opps/:slug", element: <OppWorkbenchPage /> },
        { path: "opps/:slug/runs/:runId", element: <OppWorkbenchPage /> },
        {
          path: "opps/:slug/runs/:runId/steps/:skill",
          element: <OppWorkbenchPage />,
        },
        { path: "opps/:slug/compare", element: <OppComparePage /> },
      ],
    },
  ],
  { basename: "/ace" },
);
```

- [ ] **Step 3: Update `frontend/src/api/client.ts`**

Two changes:

**3a.** Change the first line from:

```typescript
import { DriveReconnectRequired, type ApiEnvelope } from "./types";
```

to:

```typescript
import { type ApiEnvelope } from "./types";
```

**3b.** Delete lines 73-77 (the drive-token-missing branch):

```typescript
  if (resp.status === 401 && envelope.error?.code === "drive-token-missing") {
    const data = envelope.data as { reconnect_url: string } | null;
    const reconnectUrl = data?.reconnect_url ?? "/auth/drive/start";
    throw new DriveReconnectRequired(reconnectUrl);
  }
```

After the delete, the `request<T>` function body flows directly from the `envelope` parse into the `if (envelope.error)` check — same as `apiFetch` above it.

Also update the docstring above `request<T>` (lines 51-56). It currently says it "surfaces drive-token-missing 401 responses as DriveReconnectRequired". Replace the whole docstring with:

```typescript
/**
 * Lower-level fetch helper used by the opps API client.
 * Same envelope handling as apiFetch, but prefixes the path with /api.
 */
```

- [ ] **Step 4: Update `frontend/src/api/types.ts`**

Delete the `DriveReconnectRequired` class declaration and its preceding comment — lines 174-184 inclusive:

```typescript
// Custom error class the client throws when the server returns a
// drive-token-missing 401 with a reconnect_url in the data field.
export class DriveReconnectRequired extends Error {
  reconnectUrl: string;

  constructor(reconnectUrl: string) {
    super("Google Drive access is not connected");
    this.name = "DriveReconnectRequired";
    this.reconnectUrl = reconnectUrl;
  }
}
```

- [ ] **Step 5: Run the frontend type-check and build**

Run: `cd frontend && bun run build`
Expected: clean build, no TypeScript errors, no unused-import warnings.

If the build complains about any remaining references to `DriveReconnectGuard` or `DriveReconnectRequired`, grep for them:

```
Run: grep -rn "DriveReconnect" frontend/src
Expected: empty after Step 4.
```

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(frontend): remove DriveReconnectGuard and related 401 handling

The opps pages no longer need a reconnect boundary — the service account
approach removes per-user Drive consent. Router unwraps opps routes,
api/client.ts drops the drive-token-missing branch, api/types.ts drops
the DriveReconnectRequired class."
```

---

## Task 6: Docs, deploy config, and learning

**Files:**
- Delete: `docs/learnings/drive-oauth-two-flow.md`
- Create: `docs/learnings/drive-service-account.md`
- Modify: `deploy/aws/task-definition.json` (add secret entry)
- Modify: `docs/deploy.md` (add Secrets Manager setup command)
- Modify: `CLAUDE.md` (update ACE opportunity visualization section, add learning to index)

- [ ] **Step 1: Delete the old learning doc**

```bash
git rm docs/learnings/drive-oauth-two-flow.md
```

- [ ] **Step 2: Create `docs/learnings/drive-service-account.md`**

Write the following to the new file:

```markdown
# Drive access via a shared service account

## Context

The ACE opportunity Workbench (`apps/opps`) reads (and is permitted to
write) Google Drive on behalf of every Dimagi user who opens it. It used
to do this via a per-user OAuth flow ported from connect-search: each
user granted Drive read scopes through a second Google consent screen,
and tokens were encrypted and cached on the `User` row.

That was replaced on 2026-04-09 with a single shared Google **service
account** that has been granted access to the team's ACE Shared Drive.
See `docs/specs/2026-04-09-drive-service-account-design.md` for the full
rationale.

## How the credentials flow

- **Prod:** AWS Secrets Manager stores the SA key JSON as a SecretString
  at `labs-jj-ace-web-drive-sa-key-json`. ECS delivers it to the task as
  env var `ACE_DRIVE_SA_KEY_JSON` via the `secrets` array in
  `deploy/aws/task-definition.json`.
- **Dev:** `.env` holds the same key as `ACE_DRIVE_SA_KEY_JSON` on a
  single line. `.env.example` shows the shape with a placeholder.
- **Code:** `apps/opps/drive_client.get_drive_client()` parses the JSON
  blob, constructs `google.oauth2.service_account.Credentials` at the
  full `drive` scope, and caches the resulting `GoogleDriveClient` via
  `functools.cache`. Every opps view calls this factory.

## Scope

The credentials are scoped to `https://www.googleapis.com/auth/drive`
— the full Drive scope, not `drive.readonly`. The `GoogleDriveClient`
surface stays read-only for now (the Workbench does not write), but
auth permits writes so a future feature can add a write method without
touching credentials.

## Shared Drive dependency

The SA can only access what the Shared Drive's ACLs grant it. If
someone removes the SA from the Shared Drive's members, the Workbench
breaks with opaque 403s from the Drive API. The SA email lives in
the SA key JSON under `client_email` — it is also the identity
`ace` CLI uses, so both tools break together if the SA loses access.

## Rotation

1. Generate a new key JSON in the GCP console for the same SA.
2. Update the Secrets Manager secret value (`aws secretsmanager
   put-secret-value --secret-id labs-jj-ace-web-drive-sa-key-json
   --secret-string file://new-key.json`).
3. Force a new ECS task (new deployment or `aws ecs update-service
   --force-new-deployment`). The new task picks up the rotated secret
   on boot; there is no in-process reload — `functools.cache` holds the
   old client for the lifetime of the old worker.
4. Revoke the old key in GCP.

## Why not Workload Identity Federation

WIF is Google's recommended pattern for non-GCP workloads and the right
long-term target. It was deferred to the Phase 5 security review:
setting up the Workload Identity Pool + provider binding is a
half-day of GCP IAM work and would split the auth story between
ace-web (WIF) and the `ace` CLI (SA key). Keeping both on the same
SA key is the simpler short-term posture.

## Failure mode

If `ACE_DRIVE_SA_KEY_JSON` is empty or unparseable, every opps API
request returns HTTP 500 with `error.code == "drive-not-configured"`.
This is deliberately loud — a missing SA key is a deploy configuration
bug, not a user-recoverable state.
```

- [ ] **Step 3: Update `deploy/aws/task-definition.json`**

Find the `secrets` array (around line 26) and append the new secret entry. The array currently ends at line 30 with the `CONNECT_OAUTH_CLIENT_SECRET` entry. Change:

```json
      "secrets": [
        {"name": "DJANGO_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-django-secret-key-2XSt10"},
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-database-url-5KLKYs"},
        {"name": "CONNECT_OAUTH_CLIENT_ID", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-connect-oauth-client-id-jzsNCM"},
        {"name": "CONNECT_OAUTH_CLIENT_SECRET", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-connect-oauth-client-secret-kXQI9s"}
      ],
```

to:

```json
      "secrets": [
        {"name": "DJANGO_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-django-secret-key-2XSt10"},
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-database-url-5KLKYs"},
        {"name": "CONNECT_OAUTH_CLIENT_ID", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-connect-oauth-client-id-jzsNCM"},
        {"name": "CONNECT_OAUTH_CLIENT_SECRET", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-connect-oauth-client-secret-kXQI9s"},
        {"name": "ACE_DRIVE_SA_KEY_JSON", "valueFrom": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-drive-sa-key-json"}
      ],
```

**Note:** the `valueFrom` ARN ends without the `-XXXXXX` suffix because the real suffix is only known after the secret is created in AWS Secrets Manager (Task 7 step 1). The implementer creating the secret must update this ARN to match the actual suffix after running `aws secretsmanager create-secret`. Call this out in the commit message.

- [ ] **Step 4: Update `docs/deploy.md`**

Add a section for the SA key secret setup. Find an existing "Secrets" or "Initial setup" section in `docs/deploy.md` and insert the following under it (or append as a new subsection if no such section exists):

```markdown
### Google Drive service account secret

The opportunity Workbench reads Google Drive via a shared service
account. The SA JSON key is stored in AWS Secrets Manager as a
SecretString and delivered to ECS as env var `ACE_DRIVE_SA_KEY_JSON`.

**One-time setup:**

1. Download the SA key JSON from the GCP console for the
   `ace-<project>@<project>.iam.gserviceaccount.com` service account
   (the same SA used by the `ace` CLI plugin).
2. Create the secret:
   ```bash
   aws secretsmanager create-secret \
     --name labs-jj-ace-web-drive-sa-key-json \
     --description "Google service account key JSON for the ACE Drive access" \
     --secret-string file:///path/to/sa-key.json \
     --region us-east-1
   ```
3. Update `deploy/aws/task-definition.json` — the `valueFrom` ARN for
   `ACE_DRIVE_SA_KEY_JSON` needs the 6-character suffix that Secrets
   Manager generates on create (e.g.
   `...-drive-sa-key-json-AbCdEf`). Grab it with:
   ```bash
   aws secretsmanager describe-secret \
     --secret-id labs-jj-ace-web-drive-sa-key-json \
     --query ARN --output text
   ```
4. Confirm the task execution role's resource policy covers the new
   secret ARN. The existing policy uses a `labs-jj-ace-web-*` wildcard
   which should match.
5. Delete the downloaded JSON file from local disk.

**Rotation:** see `docs/learnings/drive-service-account.md`.
```

- [ ] **Step 5: Update `CLAUDE.md` — ACE opportunity visualization section**

Replace the "Two OAuth flows" paragraph (lines 142-145):

```markdown
**Two OAuth flows:** identity via a hand-rolled CommCare Connect OAuth
flow with PKCE (`apps/auth/oauth_views.py`, pattern from connect-labs);
Drive access via a separate Google OAuth grant per-user (pattern from
`../connect-search/`). See `docs/learnings/drive-oauth-two-flow.md`.
```

with:

```markdown
**Identity + Drive access:** identity via a hand-rolled CommCare Connect
OAuth flow with PKCE (`apps/auth/oauth_views.py`, pattern from
connect-labs). Drive access is via a single shared Google service
account (the same one the `ace` CLI uses), delivered through
`ACE_DRIVE_SA_KEY_JSON` in AWS Secrets Manager. No per-user Drive
consent. See `docs/learnings/drive-service-account.md`.
```

- [ ] **Step 6: Update `CLAUDE.md` — Learnings index**

In the "Learnings (read before touching the relevant area)" section, add a new bullet under a suitable subheading. The existing subheadings are "Infra & scaling", "Auth & identity", "API conventions", "Conversation engine (Phase 2)", "Deploy & infrastructure". Add under "Auth & identity" (currently only has `user-google-sub-nullable`):

```markdown
- [drive-service-account](docs/learnings/drive-service-account.md) — the opps Workbench talks to Drive via a shared Google service account (not per-user OAuth); the SA key JSON lives in AWS Secrets Manager as `ACE_DRIVE_SA_KEY_JSON`.
```

Also update the file-count comment in the `## Project structure` tree (around line 73):

```
│   ├── learnings/   # 6 load-bearing gotchas (see below)
```

Change the `6` to `7`. (6 existing + 1 new = 7, since `drive-oauth-two-flow.md` was previously unlisted and is now deleted; the net change to the index count is +1.)

- [ ] **Step 7: Verify no remaining references to the deleted learning**

```
Run: grep -rn "drive-oauth-two-flow" .
Expected: empty output.
```

- [ ] **Step 8: Run full test suite one final time**

Run: `pytest -v && cd frontend && bun run build && cd ..`
Expected: all tests pass, frontend builds clean.

- [ ] **Step 9: Commit**

```bash
git add docs/learnings/drive-service-account.md docs/deploy.md CLAUDE.md deploy/aws/task-definition.json
git commit -m "docs+deploy: service-account setup runbook and CLAUDE.md updates

- New learning doc: drive-service-account.md with rotation procedure,
  Shared Drive dependency, and rationale for deferring WIF.
- docs/deploy.md: one-time Secrets Manager creation command.
- deploy/aws/task-definition.json: ACE_DRIVE_SA_KEY_JSON secret entry.
  NOTE: the valueFrom ARN needs its 6-char suffix appended once the
  real secret is created in AWS.
- CLAUDE.md: opp visualization section updated, new learning indexed."
```

---

## Task 7: Manual one-time ops (NOT agent-executable)

These steps require AWS access and a live Drive SA key. They run outside the agent loop, as part of the deploy rollout for this change.

- [ ] **Step 1 (manual):** Obtain the SA key JSON from the GCP console (or wherever the `ace` CLI's current SA key is kept). The SA must already have access to the team's ACE Shared Drive.

- [ ] **Step 2 (manual):** Create the AWS Secrets Manager secret using the command documented in `docs/deploy.md` under "Google Drive service account secret."

- [ ] **Step 3 (manual):** Fetch the real ARN (with the 6-character suffix) and update `deploy/aws/task-definition.json`'s `ACE_DRIVE_SA_KEY_JSON` `valueFrom` entry to match. Commit with a message like `deploy: wire real Secrets Manager ARN for ACE_DRIVE_SA_KEY_JSON`.

- [ ] **Step 4 (manual):** Verify the task execution role's resource policy covers the new secret ARN. If the existing `labs-jj-ace-web-*` wildcard doesn't match, widen the policy or add a specific resource entry.

- [ ] **Step 5 (manual):** Trigger a deploy via the GitHub Actions "Deploy to Labs (AWS)" workflow with `run_migrations: true` so migration `0003_drop_drive_token_fields` applies. Watch the ECS task come up in the AWS console and confirm the new task enters RUNNING state without falling into a restart loop.

- [ ] **Step 6 (manual):** Smoke-test against real Drive: hit `/ace/opps` in the browser, confirm the opp list returns real entries (not empty), click through to an opp, confirm `/ace/opps/<slug>` renders the workbench with real data. This is the Workbench's first real-prod smoke test, so expect unrelated bugs to surface — they are out of scope for this PR and get logged as follow-ups.

- [ ] **Step 7 (manual):** Delete the local SA key JSON file from disk.

---

## Self-Review Notes

Completed inline during plan writing:

- **Spec coverage:** All 9 sections of `2026-04-09-drive-service-account-design.md` map to tasks above. §4.1 credentials loading → Task 1. §4.2 views → Task 2. §4.3 data model → Task 4. §4.4 settings & secrets → Tasks 1, 3, 6. §4.5 frontend → Task 5. §5 deletions → distributed across Tasks 3, 5, 6. §6 tests → Tasks 1, 2, 3. §7 execution order → Tasks 1-7. §8 risks (SA rotation, cache clear for tests, Shared Drive dependency) → captured in the learning doc Task 6 writes.
- **Placeholder scan:** no TBDs, TODOs, or "add error handling" placeholders. The only deferred item is the manual ARN suffix in Task 6 Step 3, which is explicitly called out as requiring real AWS access in Task 7 Step 3.
- **Type consistency:** `get_drive_client` (no args) is the factory name used consistently across Tasks 1, 2, 5 (in patch targets). `DriveServiceAccountNotConfigured` is the exception class used consistently between `drive_client.py` and `views.py`. `ACE_DRIVE_SA_KEY_JSON` is the setting name used across settings, factory, tests, task-definition, learning doc, and deploy.md.
