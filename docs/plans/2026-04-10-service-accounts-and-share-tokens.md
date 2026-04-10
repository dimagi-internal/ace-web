# Service Accounts Library + Share Tokens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable Django service accounts library with provider-agnostic credentials, application-layer impersonation policy, and audit logging. Then finish the share token feature (REST endpoints, public viewer route, frontend UI).

**Architecture:** Two independent deliverables sharing no code. The service accounts library (`apps/service_accounts/`) is a new Django app with three models (ServiceAccount, ImpersonationGrant, AccessLog), a registry module that is the single entry point for credential access, pluggable credential providers, and Fernet encryption for credential storage. Share token completion wires up the existing `ShareToken` model with REST endpoints, a public viewer route, and frontend UI. The Drive client in `apps/opps/` is refactored to use the new registry instead of reading env vars directly.

**Tech Stack:** Django 5, DRF, `cryptography` (Fernet — already a transitive dep), `google-auth` (already installed), React 19, TypeScript 5, Tailwind 3.4.

**Spec:** `docs/specs/2026-04-10-service-accounts-and-share-tokens-design.md`

---

## File plan

### New files

```
apps/service_accounts/
    __init__.py                          # empty
    apps.py                              # AppConfig (label="service_accounts")
    models.py                            # ServiceAccount, ImpersonationGrant, AccessLog
    registry.py                          # get_credentials() — the single entry point
    providers.py                         # GoogleSAProvider, ApiKeyProvider
    encryption.py                        # Fernet encrypt/decrypt derived from SECRET_KEY
    exceptions.py                        # ServiceAccountNotFound, ImpersonationDenied, InvalidScope
    admin.py                             # Admin registrations
    management/
        __init__.py
        commands/
            __init__.py
            create_service_account.py    # CLI provisioning
            grant_impersonation.py       # CLI grant management
    migrations/                          # auto-generated
    tests/
        __init__.py
        test_encryption.py
        test_models.py
        test_registry.py
        test_providers.py
        test_bootstrap.py

apps/sessions/share_views.py            # Share token endpoints (separate file to keep views.py focused)
frontend/src/api/share.ts               # Share token API client functions
frontend/src/components/SharePopover.tsx # Share management UI component
frontend/src/pages/ShareViewPage.tsx     # Public read-only transcript viewer
```

### Modified files

```
config/settings/base.py                 # INSTALLED_APPS + SERVICE_ACCOUNTS setting
config/urls.py                          # public share route before SPA catch-all
apps/sessions/urls.py                   # share token URL patterns
apps/sessions/serializers.py            # ShareTokenSerializer, ShareMessageSerializer
apps/opps/drive_client.py               # refactor get_drive_client() to use registry
apps/opps/views.py                      # catch ServiceAccountNotFound instead of DriveServiceAccountNotConfigured
frontend/src/router.tsx                  # /share/:token route
frontend/src/api/types.ts               # ShareToken interface
frontend/src/pages/ChatPage.tsx          # SharePopover in header
```

---

## Task 1: Encryption module

**Files:**
- Create: `apps/service_accounts/__init__.py`
- Create: `apps/service_accounts/encryption.py`
- Create: `apps/service_accounts/tests/__init__.py`
- Create: `apps/service_accounts/tests/test_encryption.py`

- [ ] **Step 1: Write the failing test**

Create `apps/service_accounts/tests/__init__.py` (empty).

Create `apps/service_accounts/__init__.py` (empty).

Create `apps/service_accounts/tests/test_encryption.py`:

```python
import pytest

from apps.service_accounts.encryption import decrypt, encrypt


def test_round_trip():
    plaintext = '{"type": "service_account", "project_id": "test"}'
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_different_plaintexts_produce_different_ciphertexts():
    a = encrypt("secret-a")
    b = encrypt("secret-b")
    assert a != b


def test_tampered_ciphertext_raises():
    ciphertext = encrypt("valid")
    tampered = ciphertext[:-4] + "XXXX"
    with pytest.raises(Exception):
        decrypt(tampered)


def test_empty_string_round_trip():
    assert decrypt(encrypt("")) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/service_accounts/tests/test_encryption.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.service_accounts.encryption'`

- [ ] **Step 3: Write the encryption module**

Create `apps/service_accounts/encryption.py`:

```python
"""Fernet encryption for service account credentials.

Derives a stable Fernet key from Django's SECRET_KEY so encrypted values
survive process restarts. If SECRET_KEY rotates, use the
`re_encrypt_credentials` management command to re-encrypt all rows.
"""
import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _derive_key() -> bytes:
    """Derive a 32-byte URL-safe base64-encoded Fernet key from SECRET_KEY."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns a Fernet token (URL-safe base64)."""
    return Fernet(_derive_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    return Fernet(_derive_key()).decrypt(ciphertext.encode()).decode()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/service_accounts/tests/test_encryption.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add apps/service_accounts/__init__.py apps/service_accounts/encryption.py \
       apps/service_accounts/tests/__init__.py apps/service_accounts/tests/test_encryption.py
git commit -m "feat(service_accounts): add Fernet encryption module"
```

---

## Task 2: Exceptions module

**Files:**
- Create: `apps/service_accounts/exceptions.py`

- [ ] **Step 1: Create the exceptions module**

Create `apps/service_accounts/exceptions.py`:

```python
"""Exceptions raised by the service accounts registry."""


class ServiceAccountNotFound(Exception):
    """The requested service account does not exist or is inactive."""


class ImpersonationDenied(Exception):
    """No valid impersonation grant exists for the requested subject."""


class InvalidScope(Exception):
    """Requested scopes exceed the allowed scopes for this SA or grant."""
```

- [ ] **Step 2: Commit**

```bash
git add apps/service_accounts/exceptions.py
git commit -m "feat(service_accounts): add exception types"
```

---

## Task 3: Models

**Files:**
- Create: `apps/service_accounts/apps.py`
- Create: `apps/service_accounts/models.py`
- Create: `apps/service_accounts/tests/test_models.py`
- Modify: `config/settings/base.py:29-44`

- [ ] **Step 1: Write the failing test**

Create `apps/service_accounts/tests/test_models.py`:

```python
import pytest
from django.utils import timezone

from apps.service_accounts.models import (
    AccessLog,
    ImpersonationGrant,
    ServiceAccount,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa():
    return ServiceAccount.objects.create(
        name="test-sa",
        credential_type="api_key",
        credential_encrypted="not-real-encrypted",
        default_scopes=["read"],
    )


def test_create_service_account(sa):
    assert sa.name == "test-sa"
    assert sa.is_active is True
    assert sa.default_scopes == ["read"]


def test_service_account_name_is_unique(sa):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        ServiceAccount.objects.create(
            name="test-sa",
            credential_type="api_key",
            credential_encrypted="x",
        )


def test_credential_json_property():
    from apps.service_accounts.encryption import encrypt

    raw = '{"key": "secret"}'
    sa = ServiceAccount.objects.create(
        name="prop-test",
        credential_type="google_sa",
        credential_encrypted=encrypt(raw),
        default_scopes=["drive"],
    )
    assert sa.credential_json == raw


def test_credential_json_setter():
    sa = ServiceAccount(
        name="setter-test",
        credential_type="api_key",
    )
    sa.credential_json = "my-api-key"
    sa.save()
    # Re-fetch from DB to confirm round-trip
    sa.refresh_from_db()
    assert sa.credential_json == "my-api-key"


def test_create_grant(sa):
    grant = ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    assert grant.revoked_at is None
    assert grant.expires_at is None


def test_grant_revocation(sa):
    grant = ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    grant.revoked_at = timezone.now()
    grant.save()
    grant.refresh_from_db()
    assert grant.revoked_at is not None


def test_access_log_creation(sa):
    log = AccessLog.objects.create(
        service_account=sa,
        action="direct_access",
        scopes_used=["read"],
        context={"caller": "test"},
    )
    assert log.subject == ""
    assert log.context == {"caller": "test"}


def test_cascade_delete(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="*@dimagi.com",
        scopes=["read"],
    )
    AccessLog.objects.create(
        service_account=sa,
        action="direct_access",
        scopes_used=["read"],
    )
    sa.delete()
    assert ImpersonationGrant.objects.count() == 0
    assert AccessLog.objects.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/service_accounts/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.service_accounts.models'`

- [ ] **Step 3: Create the AppConfig**

Create `apps/service_accounts/apps.py`:

```python
from django.apps import AppConfig


class ServiceAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.service_accounts"
    label = "service_accounts"
```

- [ ] **Step 4: Register the app in settings**

In `config/settings/base.py`, add the app to `INSTALLED_APPS` (after `"apps.ingest.apps.IngestConfig"`):

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    # Local apps
    "apps.common",
    "apps.auth.apps.AuthConfig",
    "apps.sessions.apps.SessionsConfig",
    "apps.opps.apps.OppsConfig",
    "apps.ingest.apps.IngestConfig",
    "apps.service_accounts.apps.ServiceAccountsConfig",
]
```

Also add the SERVICE_ACCOUNTS setting at the end of `config/settings/base.py` (before the `# --- Logging ---` section, around line 181):

```python
# --- Service Accounts ---
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

- [ ] **Step 5: Create the models**

Create `apps/service_accounts/models.py`:

```python
"""Service account models: credential storage, impersonation policy, audit log."""
from django.conf import settings
from django.db import models

from .encryption import decrypt, encrypt


class ServiceAccount(models.Model):
    """A non-human actor with credentials, scoped permissions, and
    controlled impersonation rights. Provider-agnostic: the credential_type
    determines which CredentialProvider interprets the stored credential."""

    CREDENTIAL_TYPES = [
        ("google_sa", "Google Service Account"),
        ("api_key", "API Key"),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    credential_type = models.CharField(max_length=50, choices=CREDENTIAL_TYPES)
    credential_encrypted = models.TextField()
    default_scopes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "service_accounts"

    def __str__(self):
        return f"{self.name} ({self.credential_type})"

    @property
    def credential_json(self) -> str:
        """Decrypt and return the stored credential."""
        return decrypt(self.credential_encrypted)

    @credential_json.setter
    def credential_json(self, value: str):
        """Encrypt and store a credential value."""
        self.credential_encrypted = encrypt(value)


class ImpersonationGrant(models.Model):
    """Defines who a service account is allowed to impersonate.

    subject_pattern is either an exact email ("alice@dimagi.com") or a
    domain wildcard ("*@dimagi.com"). Matching is case-insensitive.
    """

    service_account = models.ForeignKey(
        ServiceAccount, on_delete=models.CASCADE, related_name="grants",
    )
    subject_pattern = models.CharField(max_length=200)
    scopes = models.JSONField(default=list)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "impersonation_grants"

    def __str__(self):
        return f"{self.service_account.name} -> {self.subject_pattern}"

    def matches(self, email: str) -> bool:
        """Check if this grant's subject_pattern matches the given email."""
        email_lower = email.lower()
        pattern_lower = self.subject_pattern.lower()
        if pattern_lower.startswith("*@"):
            return email_lower.endswith(pattern_lower[1:])
        return email_lower == pattern_lower


class AccessLog(models.Model):
    """Audit trail for every credential use through the registry."""

    service_account = models.ForeignKey(
        ServiceAccount, on_delete=models.CASCADE, related_name="access_logs",
    )
    action = models.CharField(max_length=50)  # "direct_access" | "impersonation"
    subject = models.CharField(max_length=200, blank=True, default="")
    scopes_used = models.JSONField(default=list)
    context = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "service_account_access_log"
        indexes = [
            models.Index(fields=["service_account", "-created_at"]),
        ]

    def __str__(self):
        target = f" as {self.subject}" if self.subject else ""
        return f"{self.service_account.name}: {self.action}{target}"
```

- [ ] **Step 6: Generate and run the migration**

Run:
```bash
python manage.py makemigrations service_accounts
python manage.py migrate
```
Expected: migration `0001_initial.py` created, applied successfully.

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest apps/service_accounts/tests/test_models.py -v`
Expected: all 9 tests pass

- [ ] **Step 8: Commit**

```bash
git add apps/service_accounts/apps.py apps/service_accounts/models.py \
       apps/service_accounts/migrations/ apps/service_accounts/tests/test_models.py \
       config/settings/base.py
git commit -m "feat(service_accounts): add models — ServiceAccount, ImpersonationGrant, AccessLog"
```

---

## Task 4: Credential providers

**Files:**
- Create: `apps/service_accounts/providers.py`
- Create: `apps/service_accounts/tests/test_providers.py`

- [ ] **Step 1: Write the failing test**

Create `apps/service_accounts/tests/test_providers.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from apps.service_accounts.exceptions import ImpersonationDenied
from apps.service_accounts.providers import ApiKeyProvider, GoogleSAProvider


class TestGoogleSAProvider:
    def test_returns_credentials_without_subject(self):
        fake_key = json.dumps({
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n",
            "client_email": "test@test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        provider = GoogleSAProvider()
        with patch("apps.service_accounts.providers.service_account") as mock_sa:
            mock_creds = MagicMock()
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            result = provider.get_credentials(fake_key, subject=None, scopes=["drive"])
            mock_sa.Credentials.from_service_account_info.assert_called_once_with(
                json.loads(fake_key), scopes=["drive"],
            )
            mock_creds.with_subject.assert_not_called()
            assert result is mock_creds

    def test_returns_delegated_credentials_with_subject(self):
        fake_key = json.dumps({"type": "service_account", "project_id": "test"})
        provider = GoogleSAProvider()
        with patch("apps.service_accounts.providers.service_account") as mock_sa:
            mock_creds = MagicMock()
            mock_delegated = MagicMock()
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_delegated
            result = provider.get_credentials(
                fake_key, subject="alice@dimagi.com", scopes=["drive"],
            )
            mock_creds.with_subject.assert_called_once_with("alice@dimagi.com")
            assert result is mock_delegated


class TestApiKeyProvider:
    def test_returns_raw_key(self):
        provider = ApiKeyProvider()
        result = provider.get_credentials("my-api-key-123", subject=None, scopes=[])
        assert result == "my-api-key-123"

    def test_rejects_impersonation(self):
        provider = ApiKeyProvider()
        with pytest.raises(ImpersonationDenied):
            provider.get_credentials(
                "my-api-key-123", subject="alice@dimagi.com", scopes=[],
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/service_accounts/tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.service_accounts.providers'`

- [ ] **Step 3: Write the providers module**

Create `apps/service_accounts/providers.py`:

```python
"""Credential providers — one per credential_type.

Each provider knows how to take a decrypted credential string and return
a provider-specific credential object (e.g., google.oauth2 Credentials,
a raw API key string).
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from google.oauth2 import service_account

from .exceptions import ImpersonationDenied


class CredentialProvider(Protocol):
    """Interface for credential providers."""

    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any: ...


class GoogleSAProvider:
    """Wraps google.oauth2.service_account.Credentials."""

    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any:
        info = json.loads(decrypted_credential)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=scopes,
        )
        if subject:
            creds = creds.with_subject(subject)
        return creds


class ApiKeyProvider:
    """Returns the raw key string. For services that just need a key."""

    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any:
        if subject:
            raise ImpersonationDenied("API keys do not support impersonation.")
        return decrypted_credential
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/service_accounts/tests/test_providers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add apps/service_accounts/providers.py apps/service_accounts/tests/test_providers.py
git commit -m "feat(service_accounts): add credential providers — GoogleSA + ApiKey"
```

---

## Task 5: Registry

**Files:**
- Create: `apps/service_accounts/registry.py`
- Create: `apps/service_accounts/tests/test_registry.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/service_accounts/tests/test_registry.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.service_accounts.encryption import encrypt
from apps.service_accounts.exceptions import (
    ImpersonationDenied,
    InvalidScope,
    ServiceAccountNotFound,
)
from apps.service_accounts.models import (
    AccessLog,
    ImpersonationGrant,
    ServiceAccount,
)
from apps.service_accounts.registry import get_credentials

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa():
    return ServiceAccount.objects.create(
        name="test-sa",
        credential_type="api_key",
        credential_encrypted=encrypt("my-secret-key"),
        default_scopes=["read", "write"],
    )


@pytest.fixture
def sa_with_grant(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    return sa


# --- direct access ---

def test_direct_access_returns_credential(sa):
    result = get_credentials("test-sa")
    assert result == "my-secret-key"


def test_direct_access_logs(sa):
    get_credentials("test-sa", context={"caller": "test"})
    log = AccessLog.objects.get()
    assert log.action == "direct_access"
    assert log.subject == ""
    assert log.scopes_used == ["read", "write"]
    assert log.context == {"caller": "test"}


def test_missing_sa_raises():
    with pytest.raises(ServiceAccountNotFound):
        get_credentials("nonexistent")


def test_inactive_sa_raises(sa):
    sa.is_active = False
    sa.save()
    with pytest.raises(ServiceAccountNotFound):
        get_credentials("test-sa")


# --- impersonation ---

def test_impersonation_with_valid_grant(sa_with_grant):
    # ApiKeyProvider rejects impersonation, so this tests grant lookup only
    # up to the provider call. Use a google_sa type for a full integration
    # test (see test_bootstrap.py). Here we verify the grant check passes.
    # Since the fixture uses api_key type, impersonation will raise at the
    # provider level — that's expected. The test validates grant matching.
    sa_with_grant.credential_type = "api_key"
    sa_with_grant.save()
    with pytest.raises(ImpersonationDenied, match="API keys do not support"):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")
    # But the access log was written before the provider was called
    # (log-then-dispatch pattern)
    assert AccessLog.objects.filter(action="impersonation").exists()


def test_impersonation_denied_no_grant(sa):
    with pytest.raises(ImpersonationDenied):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")


def test_impersonation_denied_revoked_grant(sa_with_grant):
    grant = sa_with_grant.grants.first()
    grant.revoked_at = timezone.now()
    grant.save()
    with pytest.raises(ImpersonationDenied):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")


def test_impersonation_denied_expired_grant(sa_with_grant):
    grant = sa_with_grant.grants.first()
    grant.expires_at = timezone.now() - timedelta(hours=1)
    grant.save()
    with pytest.raises(ImpersonationDenied):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")


def test_wildcard_grant_matches():
    sa = ServiceAccount.objects.create(
        name="wildcard-sa",
        credential_type="api_key",
        credential_encrypted=encrypt("key"),
        default_scopes=["read"],
    )
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="*@dimagi.com",
        scopes=["read"],
    )
    # Grant matches, but ApiKeyProvider rejects impersonation
    with pytest.raises(ImpersonationDenied, match="API keys do not support"):
        get_credentials("wildcard-sa", on_behalf_of="anyone@dimagi.com")
    # Log written means grant check passed
    assert AccessLog.objects.filter(
        action="impersonation", subject="anyone@dimagi.com"
    ).exists()


def test_wildcard_grant_rejects_wrong_domain():
    sa = ServiceAccount.objects.create(
        name="wildcard-sa-2",
        credential_type="api_key",
        credential_encrypted=encrypt("key"),
        default_scopes=["read"],
    )
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="*@dimagi.com",
        scopes=["read"],
    )
    with pytest.raises(ImpersonationDenied):
        get_credentials("wildcard-sa-2", on_behalf_of="anyone@evil.com")
    # No log — denied before dispatch
    assert not AccessLog.objects.filter(subject="anyone@evil.com").exists()


def test_case_insensitive_grant_match(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="Alice@Dimagi.com",
        scopes=["read"],
    )
    # Grant matches (case-insensitive), provider rejects (api_key)
    with pytest.raises(ImpersonationDenied, match="API keys do not support"):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")
    assert AccessLog.objects.filter(action="impersonation").exists()


# --- scope validation ---

def test_explicit_scopes_subset(sa):
    result = get_credentials("test-sa", scopes=["read"])
    assert result == "my-secret-key"
    log = AccessLog.objects.get()
    assert log.scopes_used == ["read"]


def test_explicit_scopes_exceed_default_raises(sa):
    with pytest.raises(InvalidScope):
        get_credentials("test-sa", scopes=["admin"])


def test_impersonation_scopes_exceed_grant_raises(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    with pytest.raises(InvalidScope):
        get_credentials(
            "test-sa",
            on_behalf_of="alice@dimagi.com",
            scopes=["write"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/service_accounts/tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.service_accounts.registry'`

- [ ] **Step 3: Write the registry module**

Create `apps/service_accounts/registry.py`:

```python
"""Service account credential registry — the single entry point.

Every credential access in the application goes through get_credentials().
It enforces impersonation policy, validates scopes, logs access, and
dispatches to the appropriate credential provider.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from .exceptions import ImpersonationDenied, InvalidScope, ServiceAccountNotFound
from .models import AccessLog, ImpersonationGrant, ServiceAccount

logger = logging.getLogger(__name__)


def _get_provider(credential_type: str):
    """Load and instantiate the credential provider for the given type."""
    sa_settings = getattr(settings, "SERVICE_ACCOUNTS", {})
    providers = sa_settings.get("PROVIDERS", {})
    dotted_path = providers.get(credential_type)
    if not dotted_path:
        raise ServiceAccountNotFound(
            f"No provider configured for credential type: {credential_type}"
        )
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _bootstrap_if_needed(name: str) -> ServiceAccount | None:
    """If the SA doesn't exist in DB but is configured for env bootstrap,
    create it from the environment variable."""
    sa_settings = getattr(settings, "SERVICE_ACCOUNTS", {})
    bootstrap = sa_settings.get("BOOTSTRAP_FROM_ENV", {})
    config = bootstrap.get(name)
    if not config:
        return None

    env_var = config["env_var"]
    import os

    raw = os.environ.get(env_var) or getattr(settings, env_var, "")
    if not raw:
        return None

    from .encryption import encrypt

    sa = ServiceAccount.objects.create(
        name=name,
        credential_type=config["credential_type"],
        credential_encrypted=encrypt(raw),
        default_scopes=config.get("default_scopes", []),
        description=f"Auto-bootstrapped from env var {env_var}",
    )
    logger.info("Bootstrapped service account %r from env var %s", name, env_var)
    return sa


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
        context: Caller-provided metadata written to the AccessLog row.

    Returns:
        Provider-specific credential object.

    Raises:
        ServiceAccountNotFound: SA doesn't exist or is inactive.
        ImpersonationDenied: on_behalf_of provided but no valid grant matches.
        InvalidScope: Requested scopes exceed allowed scopes.
    """
    try:
        sa = ServiceAccount.objects.get(name=name, is_active=True)
    except ServiceAccount.DoesNotExist:
        sa = _bootstrap_if_needed(name)
        if sa is None:
            raise ServiceAccountNotFound(f"Service account {name!r} not found or inactive")

    effective_scopes = scopes if scopes is not None else list(sa.default_scopes)

    # Validate scopes against SA defaults
    allowed = set(sa.default_scopes)
    if not set(effective_scopes).issubset(allowed):
        excess = set(effective_scopes) - allowed
        raise InvalidScope(
            f"Scopes {excess} exceed allowed scopes {allowed} for SA {name!r}"
        )

    if on_behalf_of:
        # Find a matching, active grant
        now = timezone.now()
        grants = ImpersonationGrant.objects.filter(
            service_account=sa,
            revoked_at__isnull=True,
        )
        matched_grant = None
        for grant in grants:
            if grant.expires_at and grant.expires_at < now:
                continue
            if grant.matches(on_behalf_of):
                matched_grant = grant
                break

        if matched_grant is None:
            raise ImpersonationDenied(
                f"No valid impersonation grant for {on_behalf_of!r} on SA {name!r}"
            )

        # Validate scopes against the grant's scopes
        grant_allowed = set(matched_grant.scopes)
        if grant_allowed and not set(effective_scopes).issubset(grant_allowed):
            excess = set(effective_scopes) - grant_allowed
            raise InvalidScope(
                f"Scopes {excess} exceed grant-allowed scopes {grant_allowed}"
            )

        AccessLog.objects.create(
            service_account=sa,
            action="impersonation",
            subject=on_behalf_of,
            scopes_used=effective_scopes,
            context=context or {},
        )
    else:
        AccessLog.objects.create(
            service_account=sa,
            action="direct_access",
            scopes_used=effective_scopes,
            context=context or {},
        )

    provider = _get_provider(sa.credential_type)
    return provider.get_credentials(
        sa.credential_json, subject=on_behalf_of, scopes=effective_scopes,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/service_accounts/tests/test_registry.py -v`
Expected: all 14 tests pass

- [ ] **Step 5: Commit**

```bash
git add apps/service_accounts/registry.py apps/service_accounts/tests/test_registry.py
git commit -m "feat(service_accounts): add registry — get_credentials() with impersonation policy"
```

---

## Task 6: Bootstrap and admin

**Files:**
- Create: `apps/service_accounts/admin.py`
- Create: `apps/service_accounts/tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing bootstrap test**

Create `apps/service_accounts/tests/test_bootstrap.py`:

```python
import os

import pytest

from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.service_accounts.models import ServiceAccount
from apps.service_accounts.registry import get_credentials

pytestmark = pytest.mark.django_db


def test_bootstrap_creates_sa_from_env(settings, monkeypatch):
    """When a SA doesn't exist in DB but BOOTSTRAP_FROM_ENV is configured,
    the registry creates the SA row from the env var on first access."""
    monkeypatch.setenv("ACE_DRIVE_SA_KEY_JSON", "test-key-json")
    settings.SERVICE_ACCOUNTS = {
        "PROVIDERS": {
            "api_key": "apps.service_accounts.providers.ApiKeyProvider",
        },
        "BOOTSTRAP_FROM_ENV": {
            "bootstrap-test": {
                "credential_type": "api_key",
                "env_var": "ACE_DRIVE_SA_KEY_JSON",
                "default_scopes": ["read"],
            },
        },
    }
    result = get_credentials("bootstrap-test")
    assert result == "test-key-json"
    assert ServiceAccount.objects.filter(name="bootstrap-test").exists()


def test_bootstrap_is_idempotent(settings, monkeypatch):
    """Second call uses the DB row, not the env var."""
    monkeypatch.setenv("ACE_DRIVE_SA_KEY_JSON", "first-value")
    settings.SERVICE_ACCOUNTS = {
        "PROVIDERS": {
            "api_key": "apps.service_accounts.providers.ApiKeyProvider",
        },
        "BOOTSTRAP_FROM_ENV": {
            "idempotent-test": {
                "credential_type": "api_key",
                "env_var": "ACE_DRIVE_SA_KEY_JSON",
                "default_scopes": ["read"],
            },
        },
    }
    get_credentials("idempotent-test")
    # Change env var — should not matter, DB row already exists
    monkeypatch.setenv("ACE_DRIVE_SA_KEY_JSON", "second-value")
    result = get_credentials("idempotent-test")
    assert result == "first-value"


def test_bootstrap_missing_env_var_raises(settings, monkeypatch):
    monkeypatch.delenv("ACE_DRIVE_SA_KEY_JSON", raising=False)
    settings.ACE_DRIVE_SA_KEY_JSON = ""
    settings.SERVICE_ACCOUNTS = {
        "PROVIDERS": {},
        "BOOTSTRAP_FROM_ENV": {
            "missing-env": {
                "credential_type": "api_key",
                "env_var": "ACE_DRIVE_SA_KEY_JSON",
                "default_scopes": [],
            },
        },
    }
    with pytest.raises(ServiceAccountNotFound):
        get_credentials("missing-env")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/service_accounts/tests/test_bootstrap.py -v`
Expected: PASS (the registry already has bootstrap logic). If it fails, fix accordingly.

- [ ] **Step 3: Create the admin registrations**

Create `apps/service_accounts/admin.py`:

```python
from django.contrib import admin

from .models import AccessLog, ImpersonationGrant, ServiceAccount


@admin.register(ServiceAccount)
class ServiceAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "credential_type", "is_active", "created_at")
    list_filter = ("credential_type", "is_active")
    readonly_fields = ("created_at", "updated_at")
    exclude = ("credential_encrypted",)


@admin.register(ImpersonationGrant)
class ImpersonationGrantAdmin(admin.ModelAdmin):
    list_display = (
        "service_account", "subject_pattern", "scopes",
        "revoked_at", "expires_at", "created_at",
    )
    list_filter = ("service_account",)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("service_account", "action", "subject", "created_at")
    list_filter = ("service_account", "action")
    readonly_fields = [f.name for f in AccessLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Run all service_accounts tests**

Run: `pytest apps/service_accounts/ -v`
Expected: all tests pass (encryption, models, providers, registry, bootstrap)

- [ ] **Step 5: Commit**

```bash
git add apps/service_accounts/admin.py apps/service_accounts/tests/test_bootstrap.py
git commit -m "feat(service_accounts): add admin registrations and bootstrap tests"
```

---

## Task 7: Management commands

**Files:**
- Create: `apps/service_accounts/management/__init__.py`
- Create: `apps/service_accounts/management/commands/__init__.py`
- Create: `apps/service_accounts/management/commands/create_service_account.py`
- Create: `apps/service_accounts/management/commands/grant_impersonation.py`

- [ ] **Step 1: Create the management command directories**

Create `apps/service_accounts/management/__init__.py` (empty).
Create `apps/service_accounts/management/commands/__init__.py` (empty).

- [ ] **Step 2: Write create_service_account command**

Create `apps/service_accounts/management/commands/create_service_account.py`:

```python
"""Management command to provision a service account from a credential file."""
from django.core.management.base import BaseCommand, CommandError

from apps.service_accounts.encryption import encrypt
from apps.service_accounts.models import ServiceAccount


class Command(BaseCommand):
    help = "Create a service account with credentials from a file."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Unique SA name")
        parser.add_argument(
            "--type", required=True, dest="credential_type",
            choices=["google_sa", "api_key"],
            help="Credential type",
        )
        parser.add_argument(
            "--credential-file", required=True, dest="credential_file",
            help="Path to the credential file (JSON key, API key text, etc.)",
        )
        parser.add_argument(
            "--scopes", nargs="*", default=[],
            help="Default scopes (space-separated)",
        )
        parser.add_argument(
            "--description", default="", help="Human-readable description",
        )

    def handle(self, **options):
        name = options["name"]
        if ServiceAccount.objects.filter(name=name).exists():
            raise CommandError(f"Service account {name!r} already exists.")

        try:
            with open(options["credential_file"]) as f:
                raw = f.read().strip()
        except FileNotFoundError:
            raise CommandError(f"Credential file not found: {options['credential_file']}")

        sa = ServiceAccount.objects.create(
            name=name,
            description=options["description"],
            credential_type=options["credential_type"],
            credential_encrypted=encrypt(raw),
            default_scopes=options["scopes"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Created service account {sa.name!r} (type={sa.credential_type})"
        ))
```

- [ ] **Step 3: Write grant_impersonation command**

Create `apps/service_accounts/management/commands/grant_impersonation.py`:

```python
"""Management command to grant impersonation rights to a service account."""
from django.core.management.base import BaseCommand, CommandError

from apps.service_accounts.models import ImpersonationGrant, ServiceAccount


class Command(BaseCommand):
    help = "Grant impersonation rights to a service account."

    def add_arguments(self, parser):
        parser.add_argument("--sa", required=True, help="Service account name")
        parser.add_argument(
            "--subject", required=True,
            help="Email or pattern (e.g., alice@dimagi.com or *@dimagi.com)",
        )
        parser.add_argument(
            "--scopes", nargs="*", default=[],
            help="Allowed scopes for this grant (space-separated)",
        )

    def handle(self, **options):
        try:
            sa = ServiceAccount.objects.get(name=options["sa"])
        except ServiceAccount.DoesNotExist:
            raise CommandError(f"Service account {options['sa']!r} not found.")

        grant = ImpersonationGrant.objects.create(
            service_account=sa,
            subject_pattern=options["subject"],
            scopes=options["scopes"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Granted {sa.name!r} impersonation of {grant.subject_pattern!r}"
        ))
```

- [ ] **Step 4: Smoke-test the commands**

Run:
```bash
python manage.py create_service_account --help
python manage.py grant_impersonation --help
```
Expected: help text displays without errors.

- [ ] **Step 5: Commit**

```bash
git add apps/service_accounts/management/
git commit -m "feat(service_accounts): add management commands — create_service_account, grant_impersonation"
```

---

## Task 8: Refactor Drive client to use registry

**Files:**
- Modify: `apps/opps/drive_client.py:160-197`
- Modify: `apps/opps/views.py:51-64`

- [ ] **Step 1: Write a test for the new factory**

Add to `apps/opps/tests/test_drive_client.py` (or create it if it doesn't exist):

```python
import pytest
from unittest.mock import patch, MagicMock

from apps.service_accounts.exceptions import ServiceAccountNotFound


@pytest.mark.django_db
def test_get_drive_client_uses_registry():
    """get_drive_client() delegates to the service accounts registry."""
    from apps.opps.drive_client import get_drive_client

    with patch("apps.opps.drive_client.registry") as mock_registry:
        mock_creds = MagicMock()
        mock_registry.get_credentials.return_value = mock_creds
        client = get_drive_client()
        mock_registry.get_credentials.assert_called_once_with(
            "ace-drive",
            on_behalf_of=None,
            context={"caller": "opps.drive_client"},
        )


@pytest.mark.django_db
def test_get_drive_client_passes_on_behalf_of():
    from apps.opps.drive_client import get_drive_client

    with patch("apps.opps.drive_client.registry") as mock_registry:
        mock_creds = MagicMock()
        mock_registry.get_credentials.return_value = mock_creds
        get_drive_client(on_behalf_of="alice@dimagi.com")
        mock_registry.get_credentials.assert_called_once_with(
            "ace-drive",
            on_behalf_of="alice@dimagi.com",
            context={"caller": "opps.drive_client"},
        )


@pytest.mark.django_db
def test_get_drive_client_raises_on_missing_sa():
    from apps.opps.drive_client import get_drive_client

    with patch("apps.opps.drive_client.registry") as mock_registry:
        mock_registry.get_credentials.side_effect = ServiceAccountNotFound("not found")
        with pytest.raises(ServiceAccountNotFound):
            get_drive_client()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/opps/tests/test_drive_client.py -v`
Expected: FAIL — current `get_drive_client()` doesn't use registry

- [ ] **Step 3: Refactor drive_client.py**

Replace the `get_drive_client` function and remove `DriveServiceAccountNotConfigured` usage in `apps/opps/drive_client.py`. The file's bottom section (lines 160-197) becomes:

```python
class DriveServiceAccountNotConfigured(RuntimeError):
    """Kept as a backward-compatible alias. New code should catch
    ServiceAccountNotFound from the registry instead."""


def get_drive_client(on_behalf_of: str | None = None) -> GoogleDriveClient:
    """Return a Drive client backed by the 'ace-drive' service account.

    Args:
        on_behalf_of: Optional email to impersonate via domain-wide delegation.
            Requires a matching ImpersonationGrant in the registry.
    """
    from apps.service_accounts import registry

    creds = registry.get_credentials(
        "ace-drive",
        on_behalf_of=on_behalf_of,
        context={"caller": "opps.drive_client"},
    )
    return GoogleDriveClient(creds)
```

Remove the `import functools`, `import json`, and `from django.conf import settings` imports that were only used by the old `get_drive_client`. Keep the `from google.oauth2 import service_account` import — it's still used by `GoogleDriveClient` indirectly (through the credentials object). Actually, check: `GoogleDriveClient.__init__` only uses `googleapiclient.discovery.build`, and `service_account` is only needed by the old factory. Remove `from google.oauth2 import service_account` too.

- [ ] **Step 4: Update opps/views.py to catch ServiceAccountNotFound**

In `apps/opps/views.py`, update the `_require_drive` function (lines 51-64):

```python
from apps.service_accounts.exceptions import ServiceAccountNotFound


def _require_drive(request):
    """Return (drive_client, error_response). error_response is None on success."""
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    try:
        return get_drive_client(), None
    except ServiceAccountNotFound as exc:
        return None, Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )
```

Remove the old `from .drive_client import DriveServiceAccountNotConfigured` import if it exists.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest apps/opps/tests/test_drive_client.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full opps test suite to check for regressions**

Run: `pytest apps/opps/ -v`
Expected: all existing tests still pass (FakeDriveClient tests don't use the factory)

- [ ] **Step 7: Run the full project test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add apps/opps/drive_client.py apps/opps/views.py \
       apps/opps/tests/test_drive_client.py
git commit -m "refactor(opps): drive client uses service accounts registry"
```

---

## Task 9: Share token backend — serializer and views

**Files:**
- Create: `apps/sessions/share_views.py`
- Modify: `apps/sessions/serializers.py`
- Modify: `apps/sessions/urls.py`
- Modify: `config/urls.py`
- Create: `apps/sessions/tests/test_share_views.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/sessions/tests/test_share_views.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Message, Session, SessionParticipant, ShareToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="alice@dimagi.com", display_name="Alice"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="bob@dimagi.com", display_name="Bob"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def session_with_messages(user):
    s = Session.objects.create(owner=user, title="Test session")
    SessionParticipant.objects.create(session=s, user=user, role="owner")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"type": "text", "text": "Hello"}, plaintext="Hello",
        status="complete",
    )
    Message.objects.create(
        session=s, turn_index=2, role="assistant",
        content={"type": "text", "text": "Hi there"},
        plaintext="Hi there", status="complete",
    )
    return s


# --- create share token ---

def test_create_share_token(client, session_with_messages):
    resp = client.post(f"/api/sessions/{session_with_messages.slug}/share")
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert "token" in body["data"]
    assert "url" in body["data"]
    assert ShareToken.objects.filter(session=session_with_messages).count() == 1


def test_create_share_token_non_participant_404(client, other_user):
    s = Session.objects.create(owner=other_user, title="not mine")
    resp = client.post(f"/api/sessions/{s.slug}/share")
    assert resp.status_code == 404


def test_create_share_token_viewer_forbidden(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="theirs")
    SessionParticipant.objects.create(session=s, user=other_user, role="owner")
    SessionParticipant.objects.create(session=s, user=user, role="viewer")
    resp = client.post(f"/api/sessions/{s.slug}/share")
    assert resp.status_code == 403


# --- list share tokens ---

def test_list_share_tokens(client, session_with_messages):
    ShareToken.objects.create(
        session=session_with_messages, created_by=session_with_messages.owner,
    )
    resp = client.get(f"/api/sessions/{session_with_messages.slug}/share")
    assert resp.status_code == 200
    tokens = resp.json()["data"]
    assert len(tokens) == 1
    assert tokens[0]["revoked_at"] is None


def test_list_share_tokens_excludes_revoked(client, session_with_messages):
    from django.utils import timezone

    ShareToken.objects.create(
        session=session_with_messages,
        created_by=session_with_messages.owner,
        revoked_at=timezone.now(),
    )
    ShareToken.objects.create(
        session=session_with_messages, created_by=session_with_messages.owner,
    )
    resp = client.get(f"/api/sessions/{session_with_messages.slug}/share")
    tokens = resp.json()["data"]
    assert len(tokens) == 1


# --- revoke share token ---

def test_revoke_share_token(client, session_with_messages):
    token = ShareToken.objects.create(
        session=session_with_messages, created_by=session_with_messages.owner,
    )
    resp = client.delete(
        f"/api/sessions/{session_with_messages.slug}/share/{token.token}"
    )
    assert resp.status_code == 200
    token.refresh_from_db()
    assert token.revoked_at is not None


def test_revoke_nonexistent_token_404(client, session_with_messages):
    resp = client.delete(
        f"/api/sessions/{session_with_messages.slug}/share/bogus-token"
    )
    assert resp.status_code == 404


# --- public share view ---

def test_public_share_view(session_with_messages):
    token = ShareToken.objects.create(
        session=session_with_messages,
        created_by=session_with_messages.owner,
    )
    anon_client = APIClient()  # not authenticated
    resp = anon_client.get(f"/api/share/{token.token}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["title"] == "Test session"
    assert len(body["messages"]) == 2
    # Messages should not include sender identity
    for msg in body["messages"]:
        assert "sender" not in msg
        assert "role" in msg
        assert "plaintext" in msg


def test_public_share_view_revoked_token(session_with_messages):
    from django.utils import timezone

    token = ShareToken.objects.create(
        session=session_with_messages,
        created_by=session_with_messages.owner,
        revoked_at=timezone.now(),
    )
    anon_client = APIClient()
    resp = anon_client.get(f"/api/share/{token.token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "revoked"


def test_public_share_view_invalid_token():
    anon_client = APIClient()
    resp = anon_client.get("/api/share/totally-bogus-token")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/sessions/tests/test_share_views.py -v`
Expected: FAIL — URLs not found (404 on all endpoints)

- [ ] **Step 3: Add ShareTokenSerializer and ShareMessageSerializer**

Add to `apps/sessions/serializers.py`:

```python
# Add ShareToken to the model import at line 6:
from .models import Draft, Message, Session, SessionParticipant, ShareToken


class ShareTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareToken
        fields = ["token", "created_at", "revoked_at"]
        read_only_fields = fields


class ShareMessageSerializer(serializers.ModelSerializer):
    """Message serializer for public share views — no sender identity."""

    class Meta:
        model = Message
        fields = [
            "turn_index",
            "role",
            "content",
            "plaintext",
            "status",
            "created_at",
        ]
        read_only_fields = fields
```

- [ ] **Step 4: Create share_views.py**

Create `apps/sessions/share_views.py`:

```python
"""REST endpoints for share token management and public share viewing."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from .models import Session, SessionParticipant, ShareToken
from .serializers import ShareMessageSerializer, ShareTokenSerializer


def _load_session_for_editor(slug: str, user) -> tuple[Session | None, str | None]:
    """Return (session, None) if user is owner or editor, else (None, reason)."""
    try:
        session = Session.objects.get(slug=slug)
    except Session.DoesNotExist:
        return None, "not_found"
    try:
        participant = SessionParticipant.objects.get(session=session, user=user)
    except SessionParticipant.DoesNotExist:
        return None, "not_found"
    if participant.role == "viewer":
        return None, "forbidden"
    return session, None


@api_view(["POST", "GET"])
@permission_classes([IsAuthenticated])
def share_token_collection(request: Request, slug: str) -> Response:
    session, reason = _load_session_for_editor(slug, request.user)
    if session is None:
        if reason == "forbidden":
            return Response(
                error_response("only owners and editors can manage share tokens", code="forbidden"),
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            error_response("session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "POST":
        token = ShareToken.objects.create(session=session, created_by=request.user)
        base_url = request.build_absolute_uri("/").rstrip("/")
        # Build the share URL respecting FORCE_SCRIPT_NAME (e.g., /ace)
        from django.conf import settings
        prefix = settings.FORCE_SCRIPT_NAME or ""
        share_url = f"{base_url}{prefix}/share/{token.token}"
        return Response(
            success_response({
                "token": token.token,
                "url": share_url,
                "created_at": token.created_at.isoformat(),
            }),
            status=status.HTTP_201_CREATED,
        )

    # GET — list active (non-revoked) tokens
    tokens = ShareToken.objects.filter(
        session=session, revoked_at__isnull=True,
    ).order_by("-created_at")
    return Response(success_response(ShareTokenSerializer(tokens, many=True).data))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def share_token_revoke(request: Request, slug: str, token: str) -> Response:
    session, reason = _load_session_for_editor(slug, request.user)
    if session is None:
        if reason == "forbidden":
            return Response(
                error_response("only owners and editors can manage share tokens", code="forbidden"),
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            error_response("session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        share_token = ShareToken.objects.get(
            session=session, token=token, revoked_at__isnull=True,
        )
    except ShareToken.DoesNotExist:
        return Response(
            error_response("share token not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    share_token.revoked_at = timezone.now()
    share_token.save(update_fields=["revoked_at"])
    return Response(success_response(ShareTokenSerializer(share_token).data))


@api_view(["GET"])
@permission_classes([AllowAny])
def public_share_view(request: Request, token: str) -> Response:
    """Public read-only view of a shared session. No auth required."""
    try:
        share_token = ShareToken.objects.select_related("session").get(token=token)
    except ShareToken.DoesNotExist:
        return Response(
            error_response("share link not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if share_token.revoked_at is not None:
        return Response(
            error_response("this share link has been revoked", code="revoked"),
            status=status.HTTP_404_NOT_FOUND,
        )

    session = share_token.session
    messages = session.messages.all().order_by("turn_index")
    return Response(success_response({
        "title": session.title,
        "messages": ShareMessageSerializer(messages, many=True).data,
    }))
```

- [ ] **Step 5: Wire up URLs**

Update `apps/sessions/urls.py`:

```python
from django.urls import path

from . import share_views, views

urlpatterns = [
    path("sessions", views.session_collection, name="session_collection"),
    path("sessions/<slug:slug>", views.session_detail, name="session_detail"),
    path(
        "sessions/<slug:slug>/messages",
        views.messages_list,
        name="messages_list",
    ),
    path(
        "sessions/<slug:slug>/participants",
        views.participant_collection,
        name="participant_collection",
    ),
    path(
        "sessions/<slug:slug>/share",
        share_views.share_token_collection,
        name="share_token_collection",
    ),
    path(
        "sessions/<slug:slug>/share/<str:token>",
        share_views.share_token_revoke,
        name="share_token_revoke",
    ),
]
```

Update `config/urls.py` to add the public share route. Insert before the SPA catch-all (line 22):

```python
from apps.sessions.share_views import public_share_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/", include("apps.sessions.urls")),
    path("api/ingest/", include("apps.ingest.urls")),
    path("api/opps/", include("apps.opps.urls")),
    path("api/auth/", include((token_urlpatterns, "auth_tokens"))),
    path("api/share/<str:token>", public_share_view, name="public_share"),
    path("auth/", include("apps.auth.urls")),
    # SPA catch-all ...
    re_path(
        r"^(?!api/|admin/|auth/|static/|assets/).*$",
        login_required(TemplateView.as_view(template_name="index.html")),
        name="spa",
    ),
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest apps/sessions/tests/test_share_views.py -v`
Expected: all 10 tests pass

- [ ] **Step 7: Run full suite for regressions**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add apps/sessions/share_views.py apps/sessions/serializers.py \
       apps/sessions/urls.py apps/sessions/tests/test_share_views.py \
       config/urls.py
git commit -m "feat(sessions): share token endpoints — create, list, revoke, public view"
```

---

## Task 10: Frontend — share API client and types

**Files:**
- Create: `frontend/src/api/share.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Add ShareToken type**

Add to `frontend/src/api/types.ts` (after the `PersonalTokenCreated` interface, around line 236):

```typescript
export interface ShareTokenInfo {
  token: string;
  url: string;
  created_at: string;
}

export interface ShareTokenListItem {
  token: string;
  created_at: string;
  revoked_at: string | null;
}

export interface SharedSession {
  title: string;
  messages: SharedMessage[];
}

export interface SharedMessage {
  turn_index: number;
  role: MessageRole;
  content: Record<string, unknown>;
  plaintext: string;
  status: MessageStatus;
  created_at: string;
}
```

- [ ] **Step 2: Create share API client**

Create `frontend/src/api/share.ts`:

```typescript
import { apiFetch } from "./client";
import type {
  ShareTokenInfo,
  ShareTokenListItem,
  SharedSession,
} from "./types";

export const createShareToken = (slug: string) =>
  apiFetch<ShareTokenInfo>(`/api/sessions/${slug}/share`, { method: "POST" });

export const listShareTokens = (slug: string) =>
  apiFetch<ShareTokenListItem[]>(`/api/sessions/${slug}/share`);

export const revokeShareToken = (slug: string, token: string) =>
  apiFetch<ShareTokenListItem>(`/api/sessions/${slug}/share/${token}`, {
    method: "DELETE",
  });

export const getSharedSession = (token: string) =>
  apiFetch<SharedSession>(`/api/share/${token}`);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/share.ts frontend/src/api/types.ts
git commit -m "feat(frontend): share token API client and types"
```

---

## Task 11: Frontend — SharePopover component

**Files:**
- Create: `frontend/src/components/SharePopover.tsx`

- [ ] **Step 1: Create the SharePopover component**

Create `frontend/src/components/SharePopover.tsx`:

```tsx
import { useEffect, useState } from "react";

import {
  createShareToken,
  listShareTokens,
  revokeShareToken,
} from "../api/share";
import type { ShareTokenListItem } from "../api/types";

interface Props {
  slug: string;
}

export function SharePopover({ slug }: Props) {
  const [open, setOpen] = useState(false);
  const [tokens, setTokens] = useState<ShareTokenListItem[]>([]);
  const [copyUrl, setCopyUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTokens = async () => {
    try {
      const result = await listShareTokens(slug);
      setTokens(result);
    } catch {
      // Silently fail — the list just stays empty
    }
  };

  useEffect(() => {
    if (open) {
      loadTokens();
    }
  }, [open, slug]);

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await createShareToken(slug);
      setCopyUrl(result.url);
      await navigator.clipboard.writeText(result.url);
      await loadTokens();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to create share link");
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (token: string) => {
    try {
      await revokeShareToken(slug, token);
      setCopyUrl(null);
      await loadTokens();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to revoke");
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
        onClick={() => setOpen(true)}
      >
        share
      </button>
    );
  }

  return (
    <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-md border border-zinc-200 bg-white p-3 shadow-lg">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-700">Share links</span>
        <button
          type="button"
          className="text-xs text-zinc-400 hover:text-zinc-600"
          onClick={() => {
            setOpen(false);
            setCopyUrl(null);
            setError(null);
          }}
        >
          close
        </button>
      </div>

      {copyUrl && (
        <div className="mb-2 rounded bg-emerald-50 px-2 py-1.5 text-xs text-emerald-700">
          Link copied to clipboard
        </div>
      )}

      {error && (
        <div className="mb-2 rounded bg-rose-50 px-2 py-1.5 text-xs text-rose-700">
          {error}
        </div>
      )}

      <button
        type="button"
        disabled={loading}
        className="mb-3 w-full rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-40"
        onClick={handleCreate}
      >
        {loading ? "creating..." : "Create share link"}
      </button>

      {tokens.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-zinc-500">
            Active links
          </span>
          {tokens.map((t) => (
            <div
              key={t.token}
              className="flex items-center justify-between rounded border border-zinc-100 px-2 py-1"
            >
              <span className="font-mono text-xs text-zinc-500">
                ...{t.token.slice(-8)}
              </span>
              <button
                type="button"
                className="text-xs text-rose-500 hover:text-rose-700"
                onClick={() => handleRevoke(t.token)}
              >
                revoke
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/SharePopover.tsx
git commit -m "feat(frontend): SharePopover component — create, copy, revoke share links"
```

---

## Task 12: Frontend — ShareViewPage and routing

**Files:**
- Create: `frontend/src/pages/ShareViewPage.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Create ShareViewPage**

Create `frontend/src/pages/ShareViewPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getSharedSession } from "../api/share";
import { ApiError } from "../api/client";
import { MessageItem } from "../components/MessageItem";
import type { SharedSession } from "../api/types";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; session: SharedSession }
  | { kind: "error"; code: string; message: string };

export default function ShareViewPage() {
  const { token = "" } = useParams();
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!token) return;
    getSharedSession(token)
      .then((session) => setState({ kind: "loaded", session }))
      .catch((e) => {
        if (e instanceof ApiError) {
          setState({ kind: "error", code: e.code, message: e.message });
        } else {
          setState({ kind: "error", code: "unknown", message: "Failed to load" });
        }
      });
  }, [token]);

  if (state.kind === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-zinc-500">Loading shared session...</p>
      </div>
    );
  }

  if (state.kind === "error") {
    const message =
      state.code === "revoked"
        ? "This share link has been revoked."
        : state.code === "not_found"
          ? "This share link is invalid or has expired."
          : state.message;
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-medium text-zinc-700">{message}</p>
        </div>
      </div>
    );
  }

  const { session } = state;

  return (
    <div className="mx-auto max-w-3xl py-6">
      <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700">
        Shared session — read only
      </div>
      <h1 className="mb-4 text-xl font-semibold text-zinc-800">
        {session.title || "Untitled session"}
      </h1>
      <div className="space-y-1">
        {session.messages.map((msg) => (
          <MessageItem
            key={msg.turn_index}
            message={{
              ...msg,
              id: msg.turn_index,
              error_detail: null,
              started_at: null,
              completed_at: null,
            }}
          />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the share route to router.tsx**

Update `frontend/src/router.tsx`. Add the import and the route:

```typescript
import { createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import HealthPage from "./pages/HealthPage";
import HomePage from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";
import LibraryPage from "./pages/LibraryPage";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import OppComparePage from "./pages/OppComparePage";
import SettingsPage from "./pages/SettingsPage";
import ShareViewPage from "./pages/ShareViewPage";

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
        { path: "library", element: <LibraryPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "opps", element: <OppListPage /> },
        { path: "opps/:slug", element: <OppWorkbenchPage /> },
        { path: "opps/:slug/runs/:runId", element: <OppWorkbenchPage /> },
        {
          path: "opps/:slug/runs/:runId/steps/:skill",
          element: <OppWorkbenchPage />,
        },
        { path: "opps/:slug/compare", element: <OppComparePage /> },
        { path: "share/:token", element: <ShareViewPage /> },
      ],
    },
  ],
  { basename: "/ace" },
);
```

**Note:** The `/share/:token` route is inside the `<App />` layout but the SPA catch-all in Django's `config/urls.py` wraps non-API routes in `login_required`. The share page will be served by the SPA catch-all and will require authentication at the Django level. This is intentional — the *data* is public via `/api/share/<token>` (AllowAny), but the React app itself requires login. If anonymous users need to see share pages without logging in, that's a future enhancement (serve a separate HTML entry point for `/share/*`). For now, share links work for any authenticated team member, which matches the "internal tool" scope.

- [ ] **Step 3: Add SharePopover to ChatPage header**

Update `frontend/src/pages/ChatPage.tsx`. Add the import (after line 5):

```typescript
import { SharePopover } from "../components/SharePopover";
```

Add the component in the header's flex container (after `<AddTeammateButton>`, around line 78). The containing div needs `relative` for the popover's absolute positioning:

Replace the header section (lines 69-80):

```tsx
<header className="flex items-center justify-between border-b border-zinc-200 px-4 py-2">
  <InlineTitleEdit value={meta.title} onSave={handleTitleSave} />
  <div className="relative flex items-center gap-3">
    <PresenceChips
      participants={socket.state.participants}
      presenceUserIds={socket.state.presence_user_ids}
      draftHolderId={holderId}
      draftHolderIdle={isDraftIdle(socket.state.active_draft)}
    />
    <AddTeammateButton slug={slug} />
    <SharePopover slug={slug} />
  </div>
</header>
```

The only changes: `relative` added to the inner div's className, and `<SharePopover slug={slug} />` added after `<AddTeammateButton>`.

- [ ] **Step 4: Verify frontend builds**

Run:
```bash
cd frontend && npx tsc --noEmit && cd ..
```
Expected: no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ShareViewPage.tsx frontend/src/router.tsx \
       frontend/src/pages/ChatPage.tsx frontend/src/components/SharePopover.tsx
git commit -m "feat(frontend): share view page, popover, and routing"
```

---

## Task 13: Full integration test

**Files:**
- Run all tests end-to-end

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest -v`
Expected: all tests pass, including:
- `apps/service_accounts/tests/` (encryption, models, providers, registry, bootstrap)
- `apps/sessions/tests/test_share_views.py` (10 share token tests)
- All existing tests (sessions, opps, auth, common, ingest)

- [ ] **Step 2: Run the linter**

Run: `ruff check .`
Expected: no errors

- [ ] **Step 3: Run the frontend type check**

Run: `cd frontend && npx tsc --noEmit && cd ..`
Expected: no errors

- [ ] **Step 4: Verify Django migrations are clean**

Run: `python manage.py makemigrations --check --dry-run`
Expected: "No changes detected"

- [ ] **Step 5: Final commit (if any fixups needed)**

If any fixups were needed, commit them:
```bash
git add -A
git commit -m "fix: integration test cleanup"
```
