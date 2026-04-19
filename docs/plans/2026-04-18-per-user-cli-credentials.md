# Per-user CLI credentials — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each ace-web user stores their own Claude CLI credential blob (encrypted at rest); web chat runs `claude -p` using the session owner's blob, falling back to the existing global `SystemConfig` blob when the owner hasn't uploaded one.

**Architecture:** New `UserCredential` table with a Fernet-encrypted blob column; `apps/common/auth_flow.py::get_stored_token` becomes user-aware; `CLIBackend` stages each subprocess's credentials in a per-invocation temp `HOME` so concurrent sessions for different owners don't cross-contaminate. Upload endpoint learns a `scope=user|global` switch (global is admin-only). Settings UI gets a two-panel credentials section.

**Tech Stack:** Django 5 + DRF + Channels (existing), `django-cryptography` (new — Fernet-backed `encrypt()` field adapter). pytest + pytest-django for tests. React/Vite/Tailwind/shadcn for the UI.

**Spec:** `docs/specs/2026-04-18-per-user-cli-credentials-design.md`

---

## Working branch

Branch off `origin/main`: `feat/per-user-cli-credentials`. One commit per task. PR at the end.

---

### Task 1: Encryption dependency and key plumbing

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/settings/base.py`
- Modify: `config/settings/prod.py` (verify key required)
- Modify: `deploy/aws/task-definition.json` (stub — real secret rotation done separately)
- Modify: `.env.example` if present; else skip

- [ ] **Step 1: Add django-cryptography to dependencies**

In `pyproject.toml` under `[project.dependencies]` (or the existing dependency list), add:

```
"django-cryptography-django5>=2.2",
```

Reason: `django-cryptography` (the original package) is unmaintained for Django 5; the `django-cryptography-django5` fork publishes identical APIs and supports Django 5.

- [ ] **Step 2: Install and lock**

Run:
```bash
pip install -e .
pip freeze | grep -i django-cryptography
```
Expected: `django-cryptography-django5==2.2.x` present. Commit whatever lock file the repo uses (if it has one — check `uv.lock` / `requirements.txt` first).

- [ ] **Step 3: Wire the encryption key setting**

In `config/settings/base.py`, after the `SECRET_KEY` declaration, add:

```python
# Field-level encryption key for UserCredential.blob_encrypted (and any
# future EncryptedTextField columns). Prod REQUIRES a dedicated key via
# ACE_FIELD_ENCRYPTION_KEY; dev/CI falls back to SECRET_KEY for ergonomics.
# django-cryptography expects the key to be a 32+ byte bytes-like object.
_explicit_field_key = env("ACE_FIELD_ENCRYPTION_KEY", default="")
if _explicit_field_key:
    FIELD_ENCRYPTION_KEY = _explicit_field_key.encode("utf-8")
else:
    FIELD_ENCRYPTION_KEY = SECRET_KEY.encode("utf-8")
```

And add `"django_cryptography"` to `INSTALLED_APPS` only if the library documentation for `django-cryptography-django5` requires it — check the package README. The fork typically does NOT require an app entry; if in doubt, leave it out and verify the model migration works.

- [ ] **Step 4: Fail-fast in prod when the dedicated key is missing**

In `config/settings/prod.py`, add after the module-level imports:

```python
import os

if not os.environ.get("ACE_FIELD_ENCRYPTION_KEY"):
    raise RuntimeError(
        "ACE_FIELD_ENCRYPTION_KEY must be set in production. "
        "Dev/CI may fall back to SECRET_KEY but prod must not."
    )
```

- [ ] **Step 5: Write the prod-fail test**

Create `config/tests/test_prod_settings.py`:

```python
import importlib
import os
import pytest


def test_prod_settings_require_field_encryption_key(monkeypatch):
    monkeypatch.delenv("ACE_FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    # Force a fresh import
    import sys
    for mod in list(sys.modules):
        if mod.startswith("config.settings"):
            del sys.modules[mod]
    with pytest.raises(RuntimeError, match="ACE_FIELD_ENCRYPTION_KEY"):
        importlib.import_module("config.settings.prod")
```

Run: `pytest config/tests/test_prod_settings.py -v`

Expected: PASS. If it errors because the prod settings also require a real DB URL etc., adjust the test to mock or set minimal env and keep the assertion on `RuntimeError`.

- [ ] **Step 6: Add task-definition placeholder**

In `deploy/aws/task-definition.json`, add to the `secrets` array (not `environment` — this is sensitive):

```json
{
  "name": "ACE_FIELD_ENCRYPTION_KEY",
  "valueFrom": "arn:aws:secretsmanager:us-east-1:<account>:secret:ace-web/field-encryption-key"
}
```

Do not create the secret in this task — a follow-up operational step writes the value to Secrets Manager. Deploy-time failure is handled by the prod-fail check in step 4.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml config/settings/base.py config/settings/prod.py config/tests/ deploy/aws/task-definition.json
# Include lock file if present
git commit -m "feat(auth): field encryption key plumbing for per-user credentials

Adds django-cryptography-django5 dep, FIELD_ENCRYPTION_KEY setting
(ACE_FIELD_ENCRYPTION_KEY env > SECRET_KEY fallback), prod startup
check that refuses to boot without the dedicated key, and a
task-definition secrets entry placeholder."
```

---

### Task 2: UserCredential model and data migration

**Files:**
- Modify: `apps/common/models.py`
- Create: `apps/common/migrations/0002_user_credential.py`
- Create: `apps/common/tests/test_models_user_credential.py`

- [ ] **Step 1: Write the model test first**

Create `apps/common/tests/__init__.py` if it doesn't exist (check first with `ls apps/common/tests/`), then create `apps/common/tests/test_models_user_credential.py`:

```python
import json

import pytest
from django.contrib.auth import get_user_model

from apps.common.models import UserCredential


@pytest.mark.django_db
def test_user_credential_stores_blob_and_prefix():
    user = get_user_model().objects.create_user(
        email="test@dimagi.com", password="x"
    )
    blob = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-abcdefghijklmno",
            "refreshToken": "r-token",
            "expiresAt": 1700000000,
            "scopes": ["user:inference"],
        }
    }
    cred = UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix="sk-ant-oat01-ab",
    )
    cred.refresh_from_db()
    loaded = json.loads(cred.blob_encrypted)
    assert loaded["claudeAiOauth"]["accessToken"].startswith("sk-ant-oat01-")
    assert cred.token_prefix == "sk-ant-oat01-ab"


@pytest.mark.django_db
def test_user_credential_is_unique_per_user():
    user = get_user_model().objects.create_user(
        email="a@dimagi.com", password="x"
    )
    UserCredential.objects.create(
        user=user, blob_encrypted="{}", token_prefix="sk-ant-oat01-aa"
    )
    with pytest.raises(Exception):  # IntegrityError
        UserCredential.objects.create(
            user=user, blob_encrypted="{}", token_prefix="sk-ant-oat01-bb"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/common/tests/test_models_user_credential.py -v`

Expected: FAIL with `ImportError: cannot import name 'UserCredential'`.

- [ ] **Step 3: Add the model**

In `apps/common/models.py`:

```python
from django.conf import settings
from django.db import models
from django_cryptography.fields import encrypt


class SystemConfig(models.Model):
    # ... existing definition unchanged ...


class UserCredential(models.Model):
    """Per-user Claude CLI credential blob, encrypted at rest.

    `blob_encrypted` holds the full JSON-serialized ``{"claudeAiOauth": {...}}``
    shape. ``token_prefix`` is the first 15 chars of the access token for
    display in the Settings UI (no full token ever re-exposed).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cli_credential",
    )
    blob_encrypted = encrypt(models.TextField())
    token_prefix = models.CharField(max_length=20)
    uploaded_at = models.DateTimeField(auto_now=True)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_validation_ok = models.BooleanField(null=True)

    class Meta:
        db_table = "common_user_credential"

    def __str__(self):
        return f"{self.user.email} ({self.token_prefix}…)"
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations common`

Expected: creates `apps/common/migrations/0002_usercredential.py` (or similar name). Rename to `0002_user_credential.py` for readability. Verify the migration adds the table and the FK to `settings.AUTH_USER_MODEL`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest apps/common/tests/test_models_user_credential.py -v`

Expected: PASS.

- [ ] **Step 6: Verify round-trip encryption manually**

Run a one-off smoke check (not a permanent test — this hits the real encryption):

```bash
python manage.py shell -c "
from apps.common.models import UserCredential
from django.contrib.auth import get_user_model
U = get_user_model()
u, _ = U.objects.get_or_create(email='smoke@dimagi.com', defaults={'password': 'x'})
c, _ = UserCredential.objects.update_or_create(
    user=u,
    defaults={'blob_encrypted': '{\"claudeAiOauth\":{\"accessToken\":\"sk-ant-oat01-aaa\"}}', 'token_prefix': 'sk-ant-oat01-aa'},
)
from django.db import connection
with connection.cursor() as cur:
    cur.execute('SELECT blob_encrypted FROM common_user_credential WHERE id=%s', [c.id])
    raw = cur.fetchone()[0]
print('raw bytes (should NOT look like JSON):', raw[:60])
c.refresh_from_db()
print('round-tripped:', c.blob_encrypted[:60])
u.delete()  # cascade cleans up UserCredential
"
```

Expected: raw bytes are opaque (base64-looking `gAAAAAB...`), round-tripped value is the original JSON string.

- [ ] **Step 7: Commit**

```bash
git add apps/common/models.py apps/common/migrations/ apps/common/tests/
git commit -m "feat(auth): UserCredential model with encrypted blob column

One-to-one with User, stores the full Claude CLI OAuth blob encrypted at
rest via django-cryptography. token_prefix kept plaintext for UI display."
```

---

### Task 3: User-aware `get_stored_token` resolver

**Files:**
- Modify: `apps/common/auth_flow.py`
- Create: `apps/common/tests/test_auth_flow_resolver.py`

Resolution order: user's `UserCredential` → global `SystemConfig` blob → `CLAUDE_CODE_OAUTH_TOKEN` env var → `None`. Returns `(token, source)` where source is `"user" | "global" | "env"`.

- [ ] **Step 1: Write the resolver test**

Create `apps/common/tests/test_auth_flow_resolver.py`:

```python
import json

import pytest
from django.contrib.auth import get_user_model

from apps.common import auth_flow
from apps.common.models import SystemConfig, UserCredential

REAL_TOKEN = "sk-ant-oat01-" + "x" * 40  # token_looks_real() needs len>=40 + prefix


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="resolver@dimagi.com", password="x"
    )


@pytest.fixture
def clear_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


@pytest.mark.django_db
def test_resolver_prefers_user_blob(user, clear_env):
    blob = {"claudeAiOauth": {"accessToken": REAL_TOKEN}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL_TOKEN[:15],
    )
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-global" + "y" * 30}}),
    )
    result = auth_flow.get_stored_token(user=user)
    assert result is not None
    token, source = result
    assert token == REAL_TOKEN
    assert source == "user"


@pytest.mark.django_db
def test_resolver_falls_back_to_global(user, clear_env):
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    result = auth_flow.get_stored_token(user=user)
    assert result == (global_token, "global")


@pytest.mark.django_db
def test_resolver_env_is_last_resort(user, monkeypatch):
    env_token = "sk-ant-oat01-" + "e" * 40
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", env_token)
    result = auth_flow.get_stored_token(user=user)
    assert result == (env_token, "env")


@pytest.mark.django_db
def test_resolver_returns_none_when_empty(user, clear_env):
    assert auth_flow.get_stored_token(user=user) is None


@pytest.mark.django_db
def test_resolver_without_user_skips_user_table(clear_env):
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    result = auth_flow.get_stored_token(user=None)
    assert result == (global_token, "global")


@pytest.mark.django_db
def test_resolver_skips_user_blob_marked_invalid(user, clear_env):
    """Live-invalidated user blob should fall through to global."""
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": REAL_TOKEN}}),
        token_prefix=REAL_TOKEN[:15],
        last_validation_ok=False,  # marked bad at upload time
    )
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    assert auth_flow.get_stored_token(user=user) == (global_token, "global")


@pytest.mark.django_db
def test_resolver_skips_unreal_user_token(user, clear_env):
    """User blob with a too-short token should be ignored, fall through to global."""
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-short"}}),
        token_prefix="sk-ant-oat01-sh",
    )
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    result = auth_flow.get_stored_token(user=user)
    assert result == (global_token, "global")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/common/tests/test_auth_flow_resolver.py -v`

Expected: FAIL — `TypeError: get_stored_token() got an unexpected keyword argument 'user'` on the first test.

- [ ] **Step 3: Refactor `get_stored_token`**

In `apps/common/auth_flow.py`, replace the existing `get_stored_token` (~line 161) with:

```python
def get_stored_token(user=None) -> tuple[str, str] | None:
    """Return (access_token, source) where source in {"user", "global", "env"}, or None.

    Resolution order (first real token wins):
      1. UserCredential for ``user`` (if provided and present).
      2. Global SystemConfig[claude_credentials_blob].
      3. ``CLAUDE_CODE_OAUTH_TOKEN`` env var.
    """
    # 1. per-user
    if user is not None:
        try:
            from .models import UserCredential  # local import to avoid app-loading order issues

            cred = UserCredential.objects.filter(user=user).first()
            if cred and cred.blob_encrypted and cred.last_validation_ok is not False:
                # last_validation_ok=False means the last upload-time live check
                # failed; skip to global fallback so chat still works. The user
                # sees "Uploaded but failing" in the Settings UI and can re-upload.
                try:
                    blob = json.loads(cred.blob_encrypted)
                except ValueError:
                    logger.warning("UserCredential blob for user=%s is not valid JSON", user.pk)
                    blob = None
                if blob:
                    token = _extract_access_token(blob)
                    if token_looks_real(token):
                        return (token, "user")
        except Exception:
            logger.debug("UserCredential lookup failed for user=%s", getattr(user, "pk", None))

    # 2. global
    token = load_stored_token()  # existing: reads global blob, writes creds file, sets env
    if token_looks_real(token):
        # load_stored_token() may have returned an env-provided token when the DB has no row;
        # distinguish by checking whether the env var was already set BEFORE the call.
        return (token, "global") if _global_row_exists() else (token, "env")

    # 3. explicit env fallback (covers the case where load_stored_token didn't run)
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if token_looks_real(env_token):
        return (env_token, "env")

    return None


def _global_row_exists() -> bool:
    try:
        from .models import SystemConfig
        return SystemConfig.objects.filter(key=_BLOB_DB_KEY).exists()
    except Exception:
        return False
```

Keep the old public name `get_stored_token` but the new shape. Any caller that did `get_stored_token()` → `str | None` must be updated — we'll do that in Task 7 where CLIBackend consumes the resolver. Until then grep for callers to make sure we catch them:

```bash
grep -rn "get_stored_token" apps/ scripts/
```

Expected callers to audit: `apps/common/auth_flow.py` itself (`validate_stored_token` calls `get_stored_token()` internally — update it in this task).

Inside `auth_flow.py`, update `validate_stored_token` (~line 189):

```python
def validate_stored_token(user=None) -> bool:
    """Return True only if the stored token for ``user`` (or global) passes a live CLI check."""
    resolved = get_stored_token(user=user)
    if resolved is None:
        logger.info("validate_stored_token: no token found (user=%s)", getattr(user, "pk", None))
        return False
    token, source = resolved
    # ... rest of the function uses ``token`` as before ...
```

And update the cache key to include `source` so per-user and global validations don't collide. Minimal change: add `source` to the cache entry:

```python
if (
    _validation_cache["token"] == token
    and _validation_cache.get("source") == source
    and now - _validation_cache["checked_at"] < _VALIDATION_CACHE_TTL
):
    ...
```

And on write:

```python
_validation_cache.update(valid=valid, checked_at=now, token=token, source=source)
```

Update the `cli_is_ready = validate_stored_token` alias — stays as-is since it's `validate_stored_token` itself that's the public API.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/common/tests/test_auth_flow_resolver.py -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full auth_flow test suite to catch regressions**

Run: `pytest apps/common/tests/ -v -k "auth_flow or token or credential"`

Expected: all green. Fix any regressions from callers that assumed `get_stored_token()` returned a `str`.

- [ ] **Step 6: Commit**

```bash
git add apps/common/auth_flow.py apps/common/tests/test_auth_flow_resolver.py
git commit -m "feat(auth): user-aware get_stored_token resolver

Returns (token, source) tuple where source is user/global/env. Prefers
per-user UserCredential, falls back to global SystemConfig blob, env
var last. validate_stored_token() also accepts user= and keys cache on
(token, source) to prevent per-user results from colliding with global."
```

---

### Task 4: Per-session credential staging in `CLIBackend`

**Files:**
- Modify: `apps/common/cli_backend.py`
- Create: `apps/common/tests/test_cli_backend_credential_staging.py`

Current `CLIBackend._build_env()` returns a single env dict pointing at the shared `ACE_CLAUDE_HOME`. We'll replace that with a per-invocation staged HOME so each subprocess reads the session-owner's blob.

- [ ] **Step 1: Write the staging test**

Create `apps/common/tests/test_cli_backend_credential_staging.py`:

```python
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.common.cli_backend import CLIBackend
from apps.common.models import SystemConfig, UserCredential
from apps.sessions.models import Session

REAL = "sk-ant-oat01-" + "x" * 40


@pytest.mark.django_db
def test_staged_env_uses_user_blob_when_present(tmp_path):
    user = get_user_model().objects.create_user(email="a@dimagi.com", password="x")
    blob = {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="abc", title="t")

    backend = CLIBackend()
    env, staged_home = backend._stage_env_for(session)
    try:
        assert env["HOME"] == staged_home
        creds_path = Path(staged_home) / ".claude" / ".credentials.json"
        assert creds_path.exists()
        stored = json.loads(creds_path.read_text())
        assert stored["claudeAiOauth"]["accessToken"] == REAL
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == REAL
        assert "ANTHROPIC_API_KEY" not in env
    finally:
        backend._teardown_staged_home(staged_home)
    assert not Path(staged_home).exists()


@pytest.mark.django_db
def test_staged_env_falls_back_to_global():
    user = get_user_model().objects.create_user(email="b@dimagi.com", password="x")
    global_token = "sk-ant-oat01-" + "g" * 40
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": global_token}}),
    )
    session = Session.objects.create(owner=user, slug="def", title="t2")

    backend = CLIBackend()
    env, staged_home = backend._stage_env_for(session)
    try:
        stored = json.loads((Path(staged_home) / ".claude" / ".credentials.json").read_text())
        assert stored["claudeAiOauth"]["accessToken"] == global_token
    finally:
        backend._teardown_staged_home(staged_home)


@pytest.mark.django_db
def test_staged_homes_are_isolated_per_invocation():
    user = get_user_model().objects.create_user(email="c@dimagi.com", password="x")
    blob = {"claudeAiOauth": {"accessToken": REAL}}
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps(blob),
        token_prefix=REAL[:15],
    )
    session = Session.objects.create(owner=user, slug="ghi", title="t3")

    backend = CLIBackend()
    _, home1 = backend._stage_env_for(session)
    _, home2 = backend._stage_env_for(session)
    try:
        assert home1 != home2
    finally:
        backend._teardown_staged_home(home1)
        backend._teardown_staged_home(home2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/common/tests/test_cli_backend_credential_staging.py -v`

Expected: FAIL — `AttributeError: 'CLIBackend' object has no attribute '_stage_env_for'`.

- [ ] **Step 3: Implement `_stage_env_for` and refactor the env path**

In `apps/common/cli_backend.py`, replace `_build_env` (~line 186) with:

```python
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from .auth_flow import get_stored_token


def _stage_env_for(self, session: "Session") -> tuple[dict[str, str], str]:
    """Resolve the owner's blob and stage it in a fresh temp HOME.

    Returns (env_dict, staged_home). Caller MUST call _teardown_staged_home(home)
    in a finally block to remove the directory.
    """
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    # Resolve blob (best-effort: this runs in the chat path, so any DB issue
    # should fall through to the subprocess failing naturally, not raise here).
    resolved = get_stored_token(user=session.owner)
    token = resolved[0] if resolved else ""
    blob_json = self._load_blob_for_token(session.owner, resolved)

    staged_root = Path(tempfile.gettempdir()) / "ace-cli" / f"{session.slug}-{uuid.uuid4().hex[:8]}"
    claude_dir = staged_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    creds_path = claude_dir / ".credentials.json"
    if blob_json:
        creds_path.write_text(blob_json)
        try:
            creds_path.chmod(0o600)
        except OSError:
            pass

    env["HOME"] = str(staged_root)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env, str(staged_root)


def _load_blob_for_token(self, owner, resolved) -> str:
    """Pick the full blob JSON matching ``resolved``'s source."""
    if resolved is None:
        return ""
    _, source = resolved
    if source == "user":
        from .models import UserCredential
        cred = UserCredential.objects.filter(user=owner).first()
        return cred.blob_encrypted if cred else ""
    if source == "global":
        from .models import SystemConfig
        row = SystemConfig.objects.filter(key="claude_credentials_blob").first()
        return row.value if row else ""
    # env source: reconstruct a minimal blob so the CLI's credentials file has
    # the expected shape.
    return json.dumps({"claudeAiOauth": {"accessToken": resolved[0]}})


def _teardown_staged_home(self, staged_home: str) -> None:
    try:
        shutil.rmtree(staged_home, ignore_errors=True)
    except Exception:
        logger.warning("Failed to clean staged CLI home %s", staged_home)
```

Remove or reduce the old `_build_env` to just `env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}; return env` — keep it as a private helper called from contexts that DON'T have a session (if any). Grep for callers: `grep -n "_build_env" apps/`.

Now thread `session` through `_spawn`. The cleanest refactor is to have `stream_completion` own the staged home lifetime:

In `stream_completion` (~line 74), wrap the body:

```python
staged_env, staged_home = self._stage_env_for(session)
try:
    # ... existing body, but pass staged_env into _spawn calls ...
finally:
    self._teardown_staged_home(staged_home)
```

Update `_spawn` to accept `env` instead of building it:

```python
async def _spawn(self, *, args: list[str], prompt: str, env: dict[str, str]):
    full_args = [self._binary, "-p", "--verbose", "--output-format", "stream-json", *args]
    proc = await asyncio.create_subprocess_exec(
        *full_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    # ... existing stdin write + error handling unchanged ...
```

And both `_spawn` callsites in `stream_completion` pass `env=staged_env`.

- [ ] **Step 4: Run the staging test**

Run: `pytest apps/common/tests/test_cli_backend_credential_staging.py -v`

Expected: all 3 tests PASS.

- [ ] **Step 5: Run the broader CLIBackend test suite**

Run: `pytest apps/common/tests/ -v -k "cli_backend"`

Expected: green. If existing CLIBackend tests passed env manually, they may need to be updated to use the new `_stage_env_for`. Fix by letting them use the real code path or by mocking `_stage_env_for` to return a prebuilt env + a throwaway temp dir.

- [ ] **Step 6: Commit**

```bash
git add apps/common/cli_backend.py apps/common/tests/test_cli_backend_credential_staging.py
git commit -m "feat(auth): stage per-session CLI credentials in temp HOME

CLIBackend.stream_completion now stages the session owner's resolved
credential blob into /tmp/ace-cli/<slug>-<uuid>/.claude/.credentials.json,
sets HOME to that temp dir for the subprocess, and tears it down in
finally. Prevents concurrent sessions for different owners from sharing
credentials. Falls back to global blob when the owner has no personal one."
```

---

### Task 5: Upload endpoint `scope=user|global`

**Files:**
- Modify: `apps/common/auth_views.py`
- Modify: `apps/common/auth_flow.py` (add `store_user_credentials_blob`)
- Create: `apps/common/tests/test_auth_views_scope.py`

- [ ] **Step 1: Write the scope tests**

Create `apps/common/tests/test_auth_views_scope.py`:

```python
import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.common.models import SystemConfig, UserCredential

REAL = "sk-ant-oat01-" + "x" * 40
BLOB = {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}}


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="u@dimagi.com", password="x")


@pytest.fixture
def admin(db):
    return get_user_model().objects.create_user(
        email="a@dimagi.com", password="x", is_staff=True
    )


@pytest.mark.django_db
def test_upload_defaults_to_user_scope(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post("/api/auth/cli/upload", BLOB, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["scope"] == "user"
    assert UserCredential.objects.filter(user=user).exists()
    assert not SystemConfig.objects.filter(key="claude_credentials_blob").exists()


@pytest.mark.django_db
def test_global_scope_requires_admin(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/auth/cli/upload?scope=global", BLOB, format="json"
    )
    assert resp.status_code == 403
    assert not SystemConfig.objects.filter(key="claude_credentials_blob").exists()


@pytest.mark.django_db
def test_admin_can_write_global(admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post(
        "/api/auth/cli/upload?scope=global", BLOB, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["scope"] == "global"
    assert SystemConfig.objects.filter(key="claude_credentials_blob").exists()


@pytest.mark.django_db
def test_malformed_blob_rejected(user):
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/auth/cli/upload",
        {"claudeAiOauth": {"accessToken": "not-a-real-token"}},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_blob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/common/tests/test_auth_views_scope.py -v`

Expected: most tests fail because the endpoint doesn't know about `scope` yet.

- [ ] **Step 3: Add `store_user_credentials_blob` to auth_flow.py**

In `apps/common/auth_flow.py`, add alongside `store_credentials_blob`:

```python
def store_user_credentials_blob(user, blob: dict) -> str:
    """Persist ``blob`` as ``user``'s UserCredential. Returns the access token."""
    from .models import UserCredential

    token = _extract_access_token(blob)
    if not token_looks_real(token):
        raise ValueError(
            "Credential blob missing or malformed access token "
            "(expected claudeAiOauth.accessToken matching sk-ant-oat...)"
        )
    _invalidate_validation_cache()
    UserCredential.objects.update_or_create(
        user=user,
        defaults={
            "blob_encrypted": json.dumps(blob),
            "token_prefix": token[:15],
        },
    )
    logger.info(
        "store_user_credentials_blob: saved user=%s prefix=%s len=%d",
        user.pk, token[:15], len(token),
    )
    return token
```

- [ ] **Step 4: Update the upload view**

In `apps/common/auth_views.py`, replace `cli_auth_upload`:

```python
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_upload(request: Request) -> Response:
    """Accept a credential blob and persist it at user or global scope."""
    scope = request.query_params.get("scope", "user")
    if scope not in ("user", "global"):
        return Response(
            error_response(message="scope must be 'user' or 'global'", code="bad_scope"),
            status=400,
        )
    if scope == "global" and not request.user.is_staff:
        return Response(
            error_response(message="global scope requires staff", code="forbidden"),
            status=403,
        )

    blob = request.data
    if not isinstance(blob, dict):
        return Response(
            error_response(message="body must be a JSON object", code="bad_request"),
            status=400,
        )
    if "claudeAiOauth" not in blob and "accessToken" in blob:
        blob = {"claudeAiOauth": blob}

    try:
        if scope == "user":
            token = auth_flow.store_user_credentials_blob(request.user, blob)
            authenticated = auth_flow.validate_stored_token(user=request.user)
            # Persist validation state so the resolver can fall back to global
            # if this blob is stored-but-dead.
            from django.utils import timezone
            from .models import UserCredential
            UserCredential.objects.filter(user=request.user).update(
                last_validated_at=timezone.now(),
                last_validation_ok=authenticated,
            )
        else:
            token = auth_flow.store_credentials_blob(blob)
            authenticated = auth_flow.validate_stored_token()
    except ValueError as exc:
        return Response(
            error_response(message=str(exc), code="bad_blob"),
            status=400,
        )

    logger.info(
        "cli_auth_upload: user=%s scope=%s token_len=%d authenticated=%s",
        getattr(request.user, "email", "?"), scope, len(token), authenticated,
    )
    return Response(
        success_response({
            "stored": True,
            "authenticated": authenticated,
            "token_prefix": token[:15],
            "scope": scope,
        })
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest apps/common/tests/test_auth_views_scope.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/common/auth_views.py apps/common/auth_flow.py apps/common/tests/test_auth_views_scope.py
git commit -m "feat(auth): /api/auth/cli/upload scope=user|global

Default scope is user (writes UserCredential). scope=global writes the
shared SystemConfig row but requires is_staff. Response includes scope
so the skill/CLI can confirm."
```

---

### Task 6: Status endpoint returns both panels

**Files:**
- Modify: `apps/common/auth_views.py`
- Create: `apps/common/tests/test_auth_views_status.py`

- [ ] **Step 1: Write the status tests**

Create `apps/common/tests/test_auth_views_status.py`:

```python
import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.common.models import SystemConfig, UserCredential

REAL = "sk-ant-oat01-" + "x" * 40


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(email="s@dimagi.com", password="x")


@pytest.mark.django_db
def test_status_reports_user_and_global_state(user, monkeypatch):
    """validate_stored_token live-runs claude. For unit scope, mock it."""
    UserCredential.objects.create(
        user=user,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": REAL}}),
        token_prefix=REAL[:15],
    )
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-" + "g" * 40}}),
    )

    # Short-circuit the CLI probe so tests don't invoke claude.
    from apps.common import auth_flow
    monkeypatch.setattr(auth_flow, "_check_token_via_cli", lambda: True)

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get("/api/auth/cli/status")
    data = resp.json()["data"]
    assert data["authenticated"] is True
    assert data["user"]["has_blob"] is True
    assert data["user"]["token_prefix"] == REAL[:15]
    assert data["global"]["has_blob"] is True


@pytest.mark.django_db
def test_status_when_user_has_nothing(user, monkeypatch):
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-" + "g" * 40}}),
    )
    from apps.common import auth_flow
    monkeypatch.setattr(auth_flow, "_check_token_via_cli", lambda: True)

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get("/api/auth/cli/status")
    data = resp.json()["data"]
    assert data["authenticated"] is True  # global fallback works
    assert data["user"]["has_blob"] is False
    assert data["user"].get("token_prefix") is None
    assert data["global"]["has_blob"] is True
```

- [ ] **Step 2: Update the status endpoint**

In `apps/common/auth_views.py`, replace `cli_auth_status`:

```python
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_status(request: Request) -> Response:
    if getattr(settings, "ACE_USE_FAKE_CLI_BACKEND", False):
        return Response(success_response({
            "authenticated": True,
            "user": {"has_blob": False, "token_prefix": None},
            "global": {"has_blob": False},
        }))

    from .models import SystemConfig, UserCredential

    cred = UserCredential.objects.filter(user=request.user).first()
    user_panel = {
        "has_blob": cred is not None,
        "token_prefix": cred.token_prefix if cred else None,
    }

    global_row = SystemConfig.objects.filter(key=auth_flow._BLOB_DB_KEY).first()
    global_panel = {"has_blob": global_row is not None}

    # "authenticated" = the token the chat path will actually use is live.
    # For the signed-in user, that's user blob first, else global.
    authenticated = auth_flow.validate_stored_token(user=request.user)

    return Response(
        success_response({
            "authenticated": authenticated,
            "user": user_panel,
            "global": global_panel,
        })
    )
```

- [ ] **Step 3: Run tests**

Run: `pytest apps/common/tests/test_auth_views_status.py -v`

Expected: both tests PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/common/auth_views.py apps/common/tests/test_auth_views_status.py
git commit -m "feat(auth): /api/auth/cli/status returns user and global panels

Response shape: {authenticated, user: {has_blob, token_prefix}, global:
{has_blob}}. authenticated reflects the token the chat path will pick for
the signed-in user (user blob first, else global)."
```

---

### Task 7: Admin "promote my token to global"

**Files:**
- Modify: `apps/common/auth_views.py` (new endpoint)
- Modify: `apps/common/urls.py`
- Create: `apps/common/tests/test_auth_views_promote.py`

- [ ] **Step 1: Write the promote test**

Create `apps/common/tests/test_auth_views_promote.py`:

```python
import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.common.models import SystemConfig, UserCredential

REAL = "sk-ant-oat01-" + "x" * 40


@pytest.fixture
def admin(db):
    u = get_user_model().objects.create_user(
        email="a@dimagi.com", password="x", is_staff=True
    )
    UserCredential.objects.create(
        user=u,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": REAL}}),
        token_prefix=REAL[:15],
    )
    return u


@pytest.fixture
def non_admin(db):
    return get_user_model().objects.create_user(email="u@dimagi.com", password="x")


@pytest.mark.django_db
def test_admin_promote_copies_user_blob_to_global(admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post("/api/auth/cli/promote")
    assert resp.status_code == 200, resp.content
    row = SystemConfig.objects.get(key="claude_credentials_blob")
    assert REAL in row.value


@pytest.mark.django_db
def test_non_admin_cannot_promote(non_admin):
    client = APIClient()
    client.force_authenticate(user=non_admin)
    resp = client.post("/api/auth/cli/promote")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_promote_fails_when_admin_has_no_personal_blob(db):
    admin = get_user_model().objects.create_user(
        email="a2@dimagi.com", password="x", is_staff=True
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post("/api/auth/cli/promote")
    assert resp.status_code == 400
```

- [ ] **Step 2: Add the endpoint**

In `apps/common/auth_views.py`:

```python
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_promote(request: Request) -> Response:
    """Admin-only: copy the caller's UserCredential blob to the global SystemConfig row."""
    if not request.user.is_staff:
        return Response(
            error_response(message="staff only", code="forbidden"),
            status=403,
        )
    from .models import UserCredential

    cred = UserCredential.objects.filter(user=request.user).first()
    if cred is None:
        return Response(
            error_response(
                message="no personal blob to promote — upload one first",
                code="no_personal_blob",
            ),
            status=400,
        )
    try:
        blob = json.loads(cred.blob_encrypted)
    except ValueError:
        return Response(
            error_response(message="personal blob is corrupt", code="bad_blob"),
            status=400,
        )
    auth_flow.store_credentials_blob(blob)
    logger.info("cli_auth_promote: admin=%s promoted personal blob to global", request.user.email)
    return Response(success_response({"promoted": True, "token_prefix": cred.token_prefix}))
```

Add `import json` at the top if missing.

- [ ] **Step 3: Wire the URL**

In `apps/common/urls.py`, add:

```python
path("auth/cli/promote", auth_views.cli_auth_promote, name="cli_auth_promote"),
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/common/tests/test_auth_views_promote.py -v`

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/common/auth_views.py apps/common/urls.py apps/common/tests/test_auth_views_promote.py
git commit -m "feat(auth): admin POST /api/auth/cli/promote

Copies the caller's UserCredential blob into the global SystemConfig row.
Staff-only. 400 when the admin has no personal blob yet."
```

---

### Task 8: Update `scripts/ace_cli_login.py` for scopes

**Files:**
- Modify: `scripts/ace_cli_login.py`

- [ ] **Step 1: Add `--scope` and `--global` flags**

In `scripts/ace_cli_login.py`, update `main()`:

After the existing `--dry-run` arg, add:

```python
p.add_argument(
    "--scope",
    choices=("user", "global"),
    default="user",
    help="upload to your personal blob (default) or the instance-wide fallback (requires admin)",
)
p.add_argument(
    "--global",
    dest="scope",
    action="store_const",
    const="global",
    help="shorthand for --scope global (admin only)",
)
```

Then in `post_upload`, change the URL construction to append the query param:

```python
def post_upload(url: str, token: str, blob: dict, scope: str = "user") -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + f"/api/auth/cli/upload?scope={scope}",
        # ... rest unchanged ...
    )
    # ... rest unchanged ...
```

And the call site in `main()`:

```python
try:
    data = post_upload(args.url, args.token, blob, scope=args.scope)
```

Update the top-of-file docstring's "Usage" section to mention `--scope`.

- [ ] **Step 2: Smoke-check locally (if you have a dev server running)**

```bash
python3 scripts/ace_cli_login.py --dry-run --scope=user
python3 scripts/ace_cli_login.py --dry-run --global
```

Expected: both print the redacted blob and exit 0. The --scope is not sent during dry-run (no HTTP request) — just validate the argparse accepts the flag.

- [ ] **Step 3: Commit**

```bash
git add scripts/ace_cli_login.py
git commit -m "feat(cli-login): --scope=user|global (default user)

Adds --scope (and --global shorthand) to ace_cli_login.py so developers
upload their personal blob by default; admins can opt into the global
fallback."
```

---

### Task 9: Update the ace-web skill + command

**Files:**
- Modify: `.claude/skills/ace-web/create-cli-credentials/SKILL.md`
- Modify: `.claude/commands/ace-web/create-cli-credentials.md`

- [ ] **Step 1: Add scope guidance to the SKILL body**

In `.claude/skills/ace-web/create-cli-credentials/SKILL.md`, add a new section after `## Steps` but before `## Failure modes`:

```markdown
## Scope: personal vs global

By default the uploader writes a **personal** blob (your user's
`UserCredential`). Your subsequent web chat sessions will use your own
Max subscription. This is what 99% of users want.

The **global** fallback blob (instance-wide `SystemConfig` row) exists
for two reasons:
1. Bootstrap — lets a new user send their first chat before they've
   uploaded their own token.
2. Shared team instances where a designated admin subscription powers
   everyone.

Only `is_staff` admins can write the global blob. To do it explicitly:

```
ACE_URL=... ACE_TOKEN=... python3 scripts/ace_cli_login.py --global
```

If a non-admin passes `--global`, the server returns `403`.
```

Also update the Step 5 curl example's expected response to reflect the new shape:

```
Expect `{"data":{"authenticated":true, "user":{"has_blob":true,
"token_prefix":"sk-ant-oat01-xx"}, "global":{"has_blob":true}}, "error":null}`.
```

- [ ] **Step 2: Mention scope in the command entrypoint**

In `.claude/commands/ace-web/create-cli-credentials.md`, update the numbered steps list:

After step 4 ("Run the uploader with ACE_URL and ACE_TOKEN"), add:

```
4a. Confirm scope — default is personal (your `UserCredential`). Pass
    `--global` only for admin-driven instance-wide fallback updates.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/ace-web/create-cli-credentials/SKILL.md .claude/commands/ace-web/create-cli-credentials.md
git commit -m "docs(skill): personal vs global scope for credential upload"
```

---

### Task 10: Settings page two-panel credentials UI

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/api/auth.ts` (create if missing) for the status + promote endpoints
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Add API types**

In `frontend/src/api/types.ts`, add:

```ts
export type CliAuthStatus = {
  authenticated: boolean;
  user: { has_blob: boolean; token_prefix: string | null };
  global: { has_blob: boolean };
};
```

- [ ] **Step 2: Add the API client**

Create `frontend/src/api/auth.ts` (or extend existing file):

```ts
import { apiGet, apiPost } from "./client";
import type { CliAuthStatus } from "./types";

export async function getCliAuthStatus(): Promise<CliAuthStatus> {
  return apiGet<CliAuthStatus>("/api/auth/cli/status");
}

export async function promoteCliAuthToGlobal(): Promise<{ promoted: boolean; token_prefix: string }> {
  return apiPost("/api/auth/cli/promote", {});
}
```

(If `apiGet`/`apiPost` helpers exist in `client.ts` under different names, use those.)

- [ ] **Step 3: Render the credentials section**

In `frontend/src/pages/SettingsPage.tsx`, add below the existing "Upload tokens" section:

```tsx
import { getCliAuthStatus, promoteCliAuthToGlobal } from "@/api/auth";
import type { CliAuthStatus } from "@/api/types";
import { Badge } from "@/components/ui/badge";

// ... inside the component body, add state + loader:
const [cliStatus, setCliStatus] = useState<CliAuthStatus | null>(null);

useEffect(() => {
  getCliAuthStatus().then(setCliStatus).catch(() => {
    /* swallow — settings page should still render */
  });
}, []);

const handlePromote = async () => {
  try {
    await promoteCliAuthToGlobal();
    toast.success("Promoted to global fallback");
    const fresh = await getCliAuthStatus();
    setCliStatus(fresh);
  } catch (e: any) {
    toast.error(e.message ?? "Promote failed");
  }
};
```

And in the JSX, below the existing `<section>` for upload tokens:

```tsx
{cliStatus && (
  <section className="max-w-2xl mt-10">
    <h2 className="text-base font-semibold">Claude CLI credentials</h2>
    <p className="mt-1 text-sm text-muted-foreground">
      Powers server-side <code>claude -p</code> for web chat. Upload via the
      <code> /ace-web:create-cli-credentials</code> skill.
    </p>

    <div className="mt-4 rounded border border-border p-4">
      <div className="flex items-center justify-between">
        <div className="font-medium">Your token</div>
        <Badge variant={cliStatus.user.has_blob ? "default" : "outline"}>
          {cliStatus.user.has_blob
            ? (cliStatus.authenticated ? "Active" : "Uploaded but failing")
            : "Not uploaded"}
        </Badge>
      </div>
      {cliStatus.user.token_prefix && (
        <code className="mt-2 block text-xs text-muted-foreground">
          {cliStatus.user.token_prefix}…
        </code>
      )}
    </div>

    <div className="mt-3 rounded border border-border p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">Instance fallback</div>
          <div className="text-xs text-muted-foreground">
            Used when a user hasn't uploaded their own blob.
          </div>
        </div>
        <Badge variant={cliStatus.global.has_blob ? "default" : "outline"}>
          {cliStatus.global.has_blob ? "Configured" : "Missing"}
        </Badge>
      </div>
      {cliStatus.user.has_blob && (
        <Button size="sm" variant="outline" className="mt-3" onClick={handlePromote}>
          Promote my token to global (admin only)
        </Button>
      )}
    </div>
  </section>
)}
```

The promote button is visible to everyone with a personal blob; the server returns 403 for non-admins and we surface the error via toast. This is fine — showing/hiding based on frontend role state would require a separate "is admin?" call.

- [ ] **Step 4: Manual walkthrough**

Run `docker compose up`, log in, navigate to `/settings`. Verify:
- With no user blob: "Not uploaded" badge, no promote button.
- After uploading via the skill: "Active" badge and token prefix appear.
- Instance fallback shows "Configured" / "Missing" correctly.
- Clicking promote as non-admin → toast "Promote failed" (403).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx frontend/src/api/auth.ts frontend/src/api/types.ts
git commit -m "feat(settings): two-panel Claude CLI credentials section

Shows 'Your token' and 'Instance fallback' panels with live status from
/api/auth/cli/status. Admin promote button surfaces errors via toast
rather than gating by a pre-fetched is_admin flag."
```

---

### Task 11: Log-scrubbing audit test

**Files:**
- Create: `apps/common/tests/test_log_scrubbing.py`

Adds a test that runs a full upload+validate cycle under log capture and asserts no sequence longer than the prefix appears anywhere in emitted logs. Defense against future regression where a debug log accidentally dumps a full token.

- [ ] **Step 1: Write the test**

Create `apps/common/tests/test_log_scrubbing.py`:

```python
import json
import logging

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

REAL = "sk-ant-oat01-" + "Z" * 50   # long enough to detect; distinctive character


@pytest.mark.django_db
def test_upload_does_not_log_full_token(caplog, monkeypatch):
    """Capture all logs emitted during an upload and assert the full access token
    never appears as a substring. Only the 15-char prefix is allowed."""
    user = get_user_model().objects.create_user(email="log@dimagi.com", password="x")
    client = APIClient()
    client.force_authenticate(user=user)

    # Stub the live probe so we don't run claude in CI.
    from apps.common import auth_flow
    monkeypatch.setattr(auth_flow, "_check_token_via_cli", lambda: True)

    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/api/auth/cli/upload",
            {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}},
            format="json",
        )
        assert resp.status_code == 200

    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    # The prefix (first 15 chars) is allowed; the full token is not.
    assert REAL not in combined, f"Full token leaked in logs: {combined[-500:]}"
    assert REAL[15:] not in combined, "Suffix of token leaked — partial exposure"
```

- [ ] **Step 2: Run it**

Run: `pytest apps/common/tests/test_log_scrubbing.py -v`

Expected: PASS. If it FAILs, the offending log line is in `caplog`'s output — find the caller (likely in `auth_flow.py` or `auth_views.py`) and trim the log to prefix-only.

- [ ] **Step 3: Commit**

```bash
git add apps/common/tests/test_log_scrubbing.py
git commit -m "test(auth): regression test that no full CLI token hits the logs"
```

---

### Task 12: End-to-end smoke test

**Files:**
- Create: `tests/test_per_user_credentials_e2e.py`

Exercise the full chat path with two different users to prove isolation. Uses the `FakeCLIBackend` path so we don't need a real claude subscription in CI — the test asserts that `_stage_env_for` produced the right env for each session, not that the Anthropic API was called.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_per_user_credentials_e2e.py`:

```python
import json

import pytest
from django.contrib.auth import get_user_model

from apps.common.cli_backend import CLIBackend
from apps.common.models import SystemConfig, UserCredential
from apps.sessions.models import Session

USER_A_TOKEN = "sk-ant-oat01-A" + "a" * 40
USER_B_TOKEN = "sk-ant-oat01-B" + "b" * 40
GLOBAL_TOKEN = "sk-ant-oat01-G" + "g" * 40


@pytest.mark.django_db
def test_two_users_get_isolated_credentials():
    User = get_user_model()
    a = User.objects.create_user(email="ea@dimagi.com", password="x")
    b = User.objects.create_user(email="eb@dimagi.com", password="x")
    c = User.objects.create_user(email="ec@dimagi.com", password="x")  # no blob

    UserCredential.objects.create(
        user=a,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": USER_A_TOKEN}}),
        token_prefix=USER_A_TOKEN[:15],
    )
    UserCredential.objects.create(
        user=b,
        blob_encrypted=json.dumps({"claudeAiOauth": {"accessToken": USER_B_TOKEN}}),
        token_prefix=USER_B_TOKEN[:15],
    )
    SystemConfig.objects.create(
        key="claude_credentials_blob",
        value=json.dumps({"claudeAiOauth": {"accessToken": GLOBAL_TOKEN}}),
    )

    sa = Session.objects.create(owner=a, slug="s-a", title="a")
    sb = Session.objects.create(owner=b, slug="s-b", title="b")
    sc = Session.objects.create(owner=c, slug="s-c", title="c")

    backend = CLIBackend()
    env_a, home_a = backend._stage_env_for(sa)
    env_b, home_b = backend._stage_env_for(sb)
    env_c, home_c = backend._stage_env_for(sc)
    try:
        assert env_a["CLAUDE_CODE_OAUTH_TOKEN"] == USER_A_TOKEN
        assert env_b["CLAUDE_CODE_OAUTH_TOKEN"] == USER_B_TOKEN
        assert env_c["CLAUDE_CODE_OAUTH_TOKEN"] == GLOBAL_TOKEN
        assert home_a != home_b != home_c
    finally:
        backend._teardown_staged_home(home_a)
        backend._teardown_staged_home(home_b)
        backend._teardown_staged_home(home_c)
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_per_user_credentials_e2e.py -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_per_user_credentials_e2e.py
git commit -m "test: end-to-end isolation — two users + fallback user get distinct tokens"
```

---

### Task 13 (optional, deferrable): `ace-upload --watch`

**Files:**
- Modify: `apps/ingest/cli.py`
- Create: `apps/ingest/tests/test_cli_watch.py`

If time permits. The core per-user work is independent of this; skip to Task 14 if not landing `--watch` in this PR.

- [ ] **Step 1: Write the watch-loop test (with mocks)**

Create `apps/ingest/tests/test_cli_watch.py`:

```python
from pathlib import Path
from unittest.mock import patch

import pytest


def test_watch_skips_unchanged_files(tmp_path):
    from apps.ingest.cli import _collect_changes

    f1 = tmp_path / "a.jsonl"
    f1.write_text('{"type":"init"}\n')

    state: dict[Path, tuple[int, float]] = {}
    to_upload = _collect_changes([tmp_path], state)
    assert to_upload == [f1]
    # state was populated
    assert f1 in state

    # second call with no changes: nothing to upload
    assert _collect_changes([tmp_path], state) == []


def test_watch_detects_modified_file(tmp_path):
    from apps.ingest.cli import _collect_changes

    f1 = tmp_path / "a.jsonl"
    f1.write_text("x")
    state: dict[Path, tuple[int, float]] = {}
    _collect_changes([tmp_path], state)

    # Modify
    f1.write_text("xy")
    import os, time
    time.sleep(0.01)
    os.utime(f1, None)

    changed = _collect_changes([tmp_path], state)
    assert changed == [f1]
```

- [ ] **Step 2: Implement `--watch`**

In `apps/ingest/cli.py`, add:

```python
def _collect_changes(roots: list[Path], state: dict) -> list[Path]:
    """Return files whose (size, mtime) differ from state. Updates state in place."""
    changed: list[Path] = []
    for root in roots:
        for path in root.rglob("*.jsonl"):
            st = path.stat()
            key = (st.st_size, st.st_mtime)
            if state.get(path) != key:
                state[path] = key
                changed.append(path)
    return changed


def _watch_loop(roots: list[Path], interval: int, uploader):
    """Poll roots every `interval` seconds. Debounce: upload only files whose
    (size, mtime) have been stable across two consecutive polls."""
    import time
    state: dict = {}
    pending: dict = {}  # file -> consecutive-stable poll count
    while True:
        changed = _collect_changes(roots, state)
        for p in changed:
            pending[p] = 0  # reset: file is changing
        # Bump stable counters for files NOT in `changed` but previously seen
        for p in list(pending):
            if p not in changed:
                pending[p] += 1
        ready = [p for p, n in pending.items() if n >= 2]
        for p in ready:
            try:
                uploader(p)
            except Exception as exc:
                print(f"upload failed for {p}: {exc}", file=sys.stderr)
            del pending[p]
        time.sleep(interval)
```

And wire `--watch` in the arg parser alongside the existing subcommands.

- [ ] **Step 3: Run tests**

Run: `pytest apps/ingest/tests/test_cli_watch.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/ingest/cli.py apps/ingest/tests/test_cli_watch.py
git commit -m "feat(ingest): ace-upload --watch for hands-off local→web mirror

Polls ~/.claude/projects/ every --interval seconds (default 60), uploads
any JSONL whose (size, mtime) has been stable across two consecutive
polls. Debounced to avoid mid-write uploads. State-less — no persistent
store; cross-restart deduplication is handled server-side by the
cli_session_id 409 path."
```

---

### Task 14: PR, deploy, smoke

**Files:** none (process tasks)

- [ ] **Step 1: Open the PR**

Push: `git push -u origin feat/per-user-cli-credentials`

Create PR against `main`:

```bash
gh pr create --base main --title "feat(auth): per-user Claude CLI credentials" --body "$(cat <<'EOF'
## Summary
- Adds per-user \`UserCredential\` storage for Claude CLI blobs, encrypted at rest via django-cryptography
- Chat subprocess stages the session owner's blob in a per-invocation temp HOME; falls back to the existing global SystemConfig blob when the owner hasn't uploaded one
- Upload endpoint learns \`scope=user|global\` (global is admin-only)
- Settings page shows a two-panel credentials section (Your token / Instance fallback) with an admin "promote my token to global" button
- \`ace-upload --watch\` hands-off local→web mirror (optional)

Spec: docs/specs/2026-04-18-per-user-cli-credentials-design.md

## Test plan
- [x] Unit tests pass (\`pytest -v\`)
- [ ] Migration runs cleanly on a labs snapshot (\`python manage.py migrate common --plan\`)
- [ ] Settings page walkthrough: upload personal → Active badge; non-admin promote → 403 toast
- [ ] Second user login, chat → logs show their token prefix, not the first user's

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Run CI and address any failures**

Watch `gh pr checks --watch`. If CI fails, read logs, patch, commit, push.

- [ ] **Step 3: Write the labs secret before deploy**

In AWS Secrets Manager:
```bash
aws secretsmanager create-secret \
  --name ace-web/field-encryption-key \
  --secret-string "$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --region us-east-1 --profile labs
```

If the secret already exists, use `put-secret-value` instead.

- [ ] **Step 4: Merge and deploy**

After review:
```bash
gh pr merge <pr-number> --merge --admin
gh workflow run deploy-labs.yml --ref main -f run_migrations=true
```

- [ ] **Step 5: Post-deploy smoke**

Log in at `https://labs.connect.dimagi.com/ace`, visit `/settings`, verify:
- "Your token" shows Not uploaded (expected — no one has run the personal upload yet on the new schema).
- "Instance fallback" shows Configured (migration re-encrypted the existing global blob).
- Chat still works end-to-end using the global blob.

Then run the personal upload flow:
```bash
ACE_URL=https://labs.connect.dimagi.com/ace \
ACE_TOKEN=<mint at /settings> \
python3 scripts/ace_cli_login.py
```

Refresh settings → "Your token" becomes Active. Send a chat message. Server logs should show `token_source=user prefix=sk-ant-oat01-xx` matching your prefix.

- [ ] **Step 6: Update CLAUDE.md and project memory**

In `CLAUDE.md`, under the "Phase 4" row or a new "Post-Phase-4 work" bullet, note: "Per-user CLI credentials (spec 2026-04-18) — shipped. Web chat now runs on each user's own Max subscription; global SystemConfig blob remains as fallback."

Update `~/.claude/projects/-Users-jjackson-emdash-projects-ace-web/memory/project_per_user_cli_tokens.md` to mark the work completed and cite the PR / commit.

Commit:
```bash
git checkout main && git pull
git checkout -b docs/per-user-cli-shipped
# edit CLAUDE.md
git add CLAUDE.md
git commit -m "docs: note per-user CLI credentials shipped (PR #<n>)"
git push -u origin docs/per-user-cli-shipped
gh pr create --base main --title "docs: note per-user CLI credentials shipped" --body "Housekeeping follow-up to PR #<n>."
gh pr merge --merge --admin
```
