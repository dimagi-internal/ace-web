# Service Accounts Library + Share Tokens — Design Spec

**Date:** 2026-04-10
**Status:** Approved for execution
**Scope:** A reusable Django service accounts library (`apps/service_accounts/`) with
provider-agnostic credential management, application-layer impersonation policy, and
audit logging. Plus: finishing the share token feature (endpoints, public viewer, UI).

## 1. Problem

ace-web has three kinds of non-human credential access today, built as three
unrelated things:

1. **Google SA key** — hardcoded in `get_drive_client()`, reads `ACE_DRIVE_SA_KEY_JSON`
   from env, cached as a process-lifetime singleton. No impersonation, no audit trail.
2. **PersonalToken** — user-bound bearer tokens for CLI tools. SHA-256 hashed, revocable.
3. **ShareToken** — per-session read-only tokens. Model exists; endpoints and UI do not.

Google's domain-wide delegation lets a service account impersonate *any* user in the
Workspace domain — all or nothing. There is no way to restrict impersonation to
specific subjects at the Google admin layer. This is a real gap for AI-driven products
where agents need scoped, auditable access on behalf of specific users.

## 2. Design

Two deliverables:

1. **`apps/service_accounts/`** — a standalone-ready Django app that models service
   accounts as a first-class concept with credential storage, impersonation grants,
   and audit logging. Provider-agnostic: Google SA is one credential type, not the
   only one.
2. **Share token completion** — REST endpoints, public viewer route, and frontend UI
   for the existing `ShareToken` model. This is a separate, ace-web-specific
   deliverable that does not depend on the service accounts library.

### 2.1 Service accounts library

#### Models

**`ServiceAccount`** — a non-human actor with an identity and credentials.

```python
class ServiceAccount(models.Model):
    name = models.CharField(max_length=100, unique=True)         # e.g. "ace-drive"
    description = models.TextField(blank=True, default="")
    credential_type = models.CharField(
        max_length=50,
        choices=[
            ("google_sa", "Google Service Account"),
            ("api_key", "API Key"),
        ],
    )
    credential_encrypted = models.TextField()                    # Fernet-encrypted JSON
    default_scopes = models.JSONField(default=list)              # ["https://..."]
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="+", null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "service_accounts"
```

The `credential_encrypted` field stores the raw credential material (Google SA key
JSON, an API key string, etc.) encrypted at rest with Fernet derived from Django's
`SECRET_KEY`. The model exposes a `credential_json` property that decrypts on access.

**`ImpersonationGrant`** — who this SA is allowed to act as.

```python
class ImpersonationGrant(models.Model):
    service_account = models.ForeignKey(
        ServiceAccount, on_delete=models.CASCADE, related_name="grants",
    )
    subject_pattern = models.CharField(max_length=200)           # "alice@dimagi.com" or "*@dimagi.com"
    scopes = models.JSONField(default=list)                      # subset of SA's default_scopes
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="+", null=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "impersonation_grants"
```

`subject_pattern` supports two forms:
- Exact match: `"alice@dimagi.com"`
- Domain wildcard: `"*@dimagi.com"`

No regex. These two forms cover every real use case without introducing injection risk.
Matching is case-insensitive (email addresses are case-insensitive per RFC 5321).

**`AccessLog`** — audit trail for every credential use.

```python
class AccessLog(models.Model):
    service_account = models.ForeignKey(
        ServiceAccount, on_delete=models.CASCADE, related_name="access_logs",
    )
    action = models.CharField(max_length=50)                     # "direct_access" | "impersonation"
    subject = models.CharField(max_length=200, blank=True, default="")
    scopes_used = models.JSONField(default=list)
    context = models.JSONField(default=dict)                     # caller metadata
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "service_account_access_log"
        indexes = [
            models.Index(fields=["service_account", "-created_at"]),
        ]
```

Read-only in admin. No TTL or cleanup — the table grows slowly (one row per credential
use, not per request).

#### Registry API

The single entry point for all credential access:

```python
# apps/service_accounts/registry.py

def get_credentials(
    name: str,
    *,
    on_behalf_of: str | None = None,
    scopes: list[str] | None = None,
    context: dict | None = None,
) -> Any:
    """Return provider-specific credentials for the named service account.

    Args:
        name: The ServiceAccount.name to look up.
        on_behalf_of: If provided, impersonate this subject. A matching,
            active ImpersonationGrant must exist or ImpersonationDenied is raised.
        scopes: Override scopes (must be a subset of the SA's default_scopes
            or the grant's scopes). Defaults to the SA's default_scopes.
        context: Caller-provided metadata written to the AccessLog row
            (view name, session slug, etc.).

    Returns:
        Provider-specific credential object. For google_sa: a
        google.oauth2.service_account.Credentials instance.

    Raises:
        ServiceAccountNotFound: SA doesn't exist or is inactive.
        ImpersonationDenied: on_behalf_of provided but no valid grant matches.
        InvalidScope: Requested scopes exceed allowed scopes.
    """
```

The function:
1. Looks up the `ServiceAccount` by name. Raises `ServiceAccountNotFound` if missing
   or `is_active=False`.
2. If `on_behalf_of` is provided, queries `ImpersonationGrant` for the SA where:
   - `subject_pattern` matches the email (exact or `*@domain`)
   - `revoked_at IS NULL`
   - `expires_at IS NULL OR expires_at > now()`
   - If `scopes` are requested, they must be a subset of the grant's `scopes`
   - Raises `ImpersonationDenied` if no grant matches.
3. Validates that requested scopes are a subset of the SA's `default_scopes`.
4. Writes an `AccessLog` row.
5. Dispatches to the credential provider to build the actual credential object.

#### Credential providers

A pluggable backend per `credential_type`:

```python
# apps/service_accounts/providers.py

class CredentialProvider(Protocol):
    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any:
        """Build a provider-specific credential object."""
        ...


class GoogleSAProvider:
    """Wraps google.oauth2.service_account.Credentials."""

    def get_credentials(self, decrypted_credential, subject, scopes):
        import json
        from google.oauth2 import service_account

        info = json.loads(decrypted_credential)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=scopes,
        )
        if subject:
            creds = creds.with_subject(subject)
        return creds


class ApiKeyProvider:
    """Returns the raw key string. For services that just need a key."""

    def get_credentials(self, decrypted_credential, subject, scopes):
        if subject:
            raise ImpersonationDenied("API keys do not support impersonation.")
        return decrypted_credential
```

Providers are registered in settings:

```python
SERVICE_ACCOUNTS = {
    "PROVIDERS": {
        "google_sa": "apps.service_accounts.providers.GoogleSAProvider",
        "api_key": "apps.service_accounts.providers.ApiKeyProvider",
    },
}
```

Only `GoogleSAProvider` is used by ace-web today. `ApiKeyProvider` is included because
it's trivial and demonstrates the extension point.

#### Credential encryption

```python
# apps/service_accounts/encryption.py

import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _derive_key() -> bytes:
    """Derive a stable Fernet key from SECRET_KEY."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns a Fernet token (URL-safe base64)."""
    return Fernet(_derive_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    return Fernet(_derive_key()).decrypt(ciphertext.encode()).decode()
```

The `ServiceAccount` model exposes a `credential_json` property:

```python
@property
def credential_json(self) -> str:
    return decrypt(self.credential_encrypted)

@credential_json.setter
def credential_json(self, value: str):
    self.credential_encrypted = encrypt(value)
```

If `SECRET_KEY` rotates, a management command (`re_encrypt_credentials`) reads each
row, decrypts with the old key, re-encrypts with the new key.

#### Settings integration and bootstrap

```python
# config/settings/base.py

SERVICE_ACCOUNTS = {
    "PROVIDERS": {
        "google_sa": "apps.service_accounts.providers.GoogleSAProvider",
        "api_key": "apps.service_accounts.providers.ApiKeyProvider",
    },
    "BOOTSTRAP_FROM_ENV": {
        "ace-drive": {
            "credential_type": "google_sa",
            "env_var": "ACE_DRIVE_SA_KEY_JSON",
            "default_scopes": ["https://www.googleapis.com/auth/drive"],
        },
    },
}
```

`BOOTSTRAP_FROM_ENV` means: when `registry.get_credentials("ace-drive")` is called
and no `ServiceAccount` named `"ace-drive"` exists in the DB, the registry reads the
env var, creates the row (with `created_by=None` to indicate auto-bootstrap), and
proceeds. This ensures existing deploys that rely on `ACE_DRIVE_SA_KEY_JSON` keep
working without a manual migration step.

Bootstrap only fires on the first call. After that, the DB row is canonical. The env
var can be removed once the SA is provisioned through admin or management commands.

#### Django admin

```python
@admin.register(ServiceAccount)
class ServiceAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "credential_type", "is_active", "created_at")
    readonly_fields = ("created_at", "updated_at")
    # credential_encrypted is excluded from the form — write-only via
    # management command or a custom admin action.
    exclude = ("credential_encrypted",)


@admin.register(ImpersonationGrant)
class ImpersonationGrantAdmin(admin.ModelAdmin):
    list_display = ("service_account", "subject_pattern", "scopes", "revoked_at", "expires_at")
    list_filter = ("service_account",)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("service_account", "action", "subject", "created_at")
    readonly_fields = [f.name for f in AccessLog._meta.fields]
    list_filter = ("service_account", "action")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

#### Management commands

```bash
# Provision a SA:
python manage.py create_service_account \
    --name ace-drive \
    --type google_sa \
    --credential-file /path/to/key.json \
    --scopes "https://www.googleapis.com/auth/drive"

# Grant impersonation:
python manage.py grant_impersonation \
    --sa ace-drive \
    --subject "alice@dimagi.com" \
    --scopes "https://www.googleapis.com/auth/drive"

# Re-encrypt after SECRET_KEY rotation:
python manage.py re_encrypt_credentials --old-key "the-previous-secret-key"
```

### 2.2 Drive client refactor

`apps/opps/drive_client.py` changes:

```python
# Before:
@functools.cache
def get_drive_client() -> GoogleDriveClient:
    raw = settings.ACE_DRIVE_SA_KEY_JSON
    ...
    credentials = service_account.Credentials.from_service_account_info(...)
    return GoogleDriveClient(credentials)

# After:
from apps.service_accounts import registry

def get_drive_client(on_behalf_of: str | None = None) -> GoogleDriveClient:
    creds = registry.get_credentials(
        "ace-drive",
        on_behalf_of=on_behalf_of,
        context={"caller": "opps.drive_client"},
    )
    return GoogleDriveClient(creds)
```

The `functools.cache` goes away. For SA-as-itself calls (no subject), the registry
can cache the `ServiceAccount` DB lookup internally (the credentials object is
lightweight and stateless — Google's library handles token refresh). For impersonation
calls, each subject produces a different credentials object, so no caching.

The `DriveClient` ABC, `GoogleDriveClient`, `FakeDriveClient`, and dataclasses
(`DriveFile`, `FileContent`) are unchanged. Only the factory function changes.

`DriveServiceAccountNotConfigured` maps to `ServiceAccountNotFound` from the
registry. The views catch it the same way.

### 2.3 Share token completion

The `ShareToken` model is unchanged. This section wires up the missing endpoints,
public viewer, and frontend UI.

#### Backend endpoints

All under `apps/sessions/views.py` (or a new `share_views.py` if cleaner):

| Method | URL | Auth | Purpose |
|--------|-----|------|---------|
| `POST` | `/api/sessions/<slug>/share` | Session owner/editor | Create share token. Returns `{token, url}`. |
| `GET` | `/api/sessions/<slug>/share` | Session owner/editor | List active (non-revoked) share tokens for this session. |
| `DELETE` | `/api/sessions/<slug>/share/<token>` | Session owner/editor | Revoke. Sets `revoked_at=now()`. |
| `GET` | `/api/share/<token>` | **None (public)** | Returns session messages (read-only). No participant identities. |

The public endpoint (`/api/share/<token>`) is explicitly exempt from authentication
middleware. It returns the standard envelope `{data: {title, messages[]}, error: null}`.
Messages include `role`, `content`, `turn_index`, `status`, `created_at` — but not
`sender` (no user identities leak through share links).

#### Frontend

**Share button** — added to the ChatPage header bar (alongside the session title and
participant chips). Clicking it:
1. POSTs to create a share token (if none exists) or shows the existing active token.
2. Displays a popover with a copyable URL and a "Revoke" button.

**Share management** — a small section in the session header popover listing active
tokens with creation dates and revoke buttons. Most sessions will have 0-1 active
tokens.

**Public share view** — new route outside the auth guard:

```
/share/:token  →  ShareViewPage
```

`ShareViewPage` is a minimal read-only transcript viewer:
- Fetches `/api/share/<token>` on mount.
- Renders messages in the same `MessageItem` component as the chat page.
- No send box, no sidebar, no participant chips, no draft UI.
- A top banner: "Shared session — read only" with the session title.
- Error states: revoked token → "This link has been revoked", invalid token → 404.

## 3. What does NOT change

- **`PersonalToken`** model and `BearerTokenAuthentication` backend — unchanged.
  These are user-bound bearer tokens for CLI tools, not service accounts.
- **`ShareToken`** model — unchanged. Only gets endpoints and UI.
- **`User`** model — unchanged.
- **Existing tests** — no regressions. The Drive client refactor is a factory-level
  change; the `FakeDriveClient` pattern in tests continues to work.
- **The WebSocket consumer, turn driver, CLI backend** — untouched.

## 4. File plan

New files:
```
apps/service_accounts/
    __init__.py
    apps.py
    models.py              # ServiceAccount, ImpersonationGrant, AccessLog
    registry.py            # get_credentials() — the choke point
    providers.py           # GoogleSAProvider, ApiKeyProvider
    encryption.py          # Fernet encrypt/decrypt
    exceptions.py          # ServiceAccountNotFound, ImpersonationDenied, InvalidScope
    admin.py
    management/
        commands/
            create_service_account.py
            grant_impersonation.py
            re_encrypt_credentials.py
    migrations/
        0001_initial.py
        0002_bootstrap_ace_drive.py   # data migration: env var → DB row
    tests/
        test_models.py
        test_registry.py
        test_providers.py
        test_encryption.py
        test_bootstrap.py
```

Modified files:
```
apps/opps/drive_client.py          # factory refactored to use registry
apps/opps/views.py                 # catch ServiceAccountNotFound instead of DriveServiceAccountNotConfigured
apps/sessions/views.py             # share token endpoints (or new share_views.py)
apps/sessions/urls.py              # share token URL patterns
config/settings/base.py            # SERVICE_ACCOUNTS setting, INSTALLED_APPS
config/urls.py                     # /api/share/<token> public route
frontend/src/api/client.ts         # shareToken API functions
frontend/src/pages/ShareViewPage.tsx       # new: public read-only viewer
frontend/src/pages/ChatPage.tsx            # share button in header
frontend/src/components/SharePopover.tsx   # new: share management UI
frontend/src/router.tsx                    # /share/:token route (outside auth guard)
```

## 5. Test plan

### Service accounts library
- `test_models.py`: CRUD for ServiceAccount, ImpersonationGrant. Encryption
  round-trip. Revocation and expiry.
- `test_registry.py`: Direct access, impersonation with valid grant, impersonation
  denied (no grant, revoked, expired, wrong scope, wrong subject), inactive SA,
  scope validation, access log written on every call.
- `test_providers.py`: GoogleSAProvider returns correct credential type, handles
  `with_subject`. ApiKeyProvider rejects impersonation.
- `test_encryption.py`: encrypt/decrypt round-trip, different keys produce different
  ciphertext, tampered ciphertext raises.
- `test_bootstrap.py`: Bootstrap from env creates SA row, subsequent calls use DB,
  missing env var raises.

### Drive client refactor
- Existing `FakeDriveClient` tests pass unchanged.
- New test: `get_drive_client()` calls `registry.get_credentials("ace-drive")`.
- New test: `get_drive_client(on_behalf_of="alice@...")` passes subject through.

### Share tokens
- Endpoint tests: create, list, revoke, use revoked token (404), use invalid token
  (404), permission checks (only owner/editor can create/revoke).
- Public view: valid token returns messages without user identities, revoked token
  returns error.
- Frontend: ShareViewPage renders messages, shows banner, handles error states.

## 6. Migration strategy

1. Add `"apps.service_accounts"` to `INSTALLED_APPS`.
2. `0001_initial.py` creates the three tables.
3. `0002_bootstrap_ace_drive.py` is a data migration that reads
   `ACE_DRIVE_SA_KEY_JSON` from env (if set), encrypts it, and creates the
   `ace-drive` ServiceAccount row. This is idempotent — if the row already exists,
   it's a no-op.
4. Refactor `drive_client.py` to use the registry.
5. Add share token endpoints and frontend.
6. Deploy with `run_migrations: true`.

No existing tables are modified. No data loss risk.
