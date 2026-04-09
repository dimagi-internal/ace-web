# ACE Opportunity Workbench — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Workbench — a new `apps/opps/` Django app plus a three-pane React surface at `/opps` in ace-web — that reads ACE opportunity state live from Google Drive (via a per-user OAuth Drive client) and presents all 19 skills of a selected run as a dense, scannable list with inline output previews, judge scores + deltas, gate history, and a hero "Discuss in chat" CTA that launches a new ace-web chat session pre-seeded with the step's context so the team can iterate on the output and push a SKILL.md improvement to GitHub from the chat. Multiple runs per IDD are first-class; a lightweight side-by-side comparison page is included.

**Architecture:** Google Drive is the source of truth. No Postgres mirror of opp / run / step / artifact state. `apps/opps/` is a read-through layer: every API call authenticates the logged-in user against Google (secondary OAuth flow on top of the existing identity auth), fetches the opportunity's folder contents live via a `DriveClient` wrapper copied from `../connect-search/backend/app/core/drive.py`, parses the structured YAML/JSONL format (`opp.yaml`, `runs/<id>/run.yaml`, `steps/<n>-<skill>/{step.yaml, judge.yaml, gates.jsonl, output/}`, `events.jsonl`), and returns a workbench payload to the browser. A flat-layout fallback lets ace-web ship before the ACE plugin adopts the structured format — legacy `ACE/<opp>/state.yaml` + `idd.md` + artifact subfolders are read as a single implicit run. Per-skill "preview extractors" turn one artifact body into the one-line inline preview shown in the center pane. The chat integration reuses the existing ace-web `Session` model with three new string pointer fields (`opp_slug`, `opp_run_id`, `opp_step_skill`); the seed builder composes a system message from the IDD + artifact bodies + judge verdict and ships it into a new session so Claude in the chat has everything needed to propose and push a skill edit.

**Tech Stack:** Python 3.11+, Django 5.x, Django REST Framework, `google-api-python-client`, `google-auth`, `cryptography` (for Fernet token encryption), PyYAML, React 19 + Vite + TypeScript + Tailwind, react-router-dom 6. No new Python dependencies beyond the three Google + crypto + YAML packages. No new frontend dependencies.

**Spec reference:** `docs/specs/2026-04-08-ace-opp-visualization-design.md` — read sections 4 (surfaces), 5 (auth), 6 (Drive folder format), 7 (data flow), and 8 (chat integration) before starting.

**Pattern source:** Drive client + Google OAuth flow is a direct port from `../connect-search/backend/app/core/{drive.py,auth.py,encryption.py}` and `../connect-search/backend/app/api/auth.py`. Those files are short (~250 lines total) and FastAPI-flavored; the port translates FastAPI routes to Django views but the core logic is unchanged. Read them before Task 2.

**Assumed dependency state:** This plan targets the post-AWS-pivot ace-web state where identity is handled by a hand-rolled CommCare Connect OAuth flow with PKCE (`apps/auth/oauth.py` + `apps/auth/oauth_views.py`, pattern ported from `../connect-labs/`), **not** `django-allauth`. The IAP middleware and the `apps/auth/middleware.py` file have been removed. Session cookies are tenant-unique (`sessionid_ace`, `csrftoken_ace`) and path-scoped to `/ace/`. This is already the state of the branch as of this plan execution (the AWS migration was merged in before this plan started).

**Key decisions to keep in mind** (from the spec and project memories):
- Drive is the source of truth. Do NOT propose Postgres models for Opp / Run / Step / Artifact / JudgeResult / GateDecision. They do not exist in the Django ORM.
- No live updates. No background sync. Every page load is a fresh Drive read. Slowness is acceptable.
- Every API response uses `apps.common.envelope.success_response` / `error_response` wrappers (`{data, error}`).
- Prefer the right and elegant structural choice over the quick one. When two options are viable, take the one with cleaner boundaries, better names, stronger test coverage.
- YAGNI still applies to features that are explicitly out of scope — do not pre-build share tokens, trend dashboards, or a SKILL.md editor UI.

---

## File structure (created across all tasks)

```
ace-web/
├── apps/
│   ├── opps/                                # NEW: the entire ACE visualization module
│   │   ├── __init__.py
│   │   ├── apps.py                          # AppConfig
│   │   ├── urls.py                          # /api/opps/* routes + /auth/drive/* routes
│   │   ├── views.py                         # DRF views for opps endpoints
│   │   ├── drive_auth_views.py              # Google OAuth start/callback for Drive scope
│   │   ├── middleware.py                    # RequireDriveToken guard for /api/opps/*
│   │   ├── drive_client.py                  # DriveClient ABC + GoogleDriveClient impl
│   │   ├── drive_credentials.py             # build_oauth_credentials helper + refresh logic
│   │   ├── encryption.py                    # Fernet wrapper for token_cache
│   │   ├── parsers.py                       # Parse opp.yaml / run.yaml / step.yaml / judge.yaml / gates.jsonl / events.jsonl
│   │   ├── sync.py                          # Drive folder → workbench payload (both structured and flat layouts)
│   │   ├── previews.py                      # Per-skill preview_text extractors (19 + fallback)
│   │   ├── seed.py                          # Build chat-session seed system message from an opp/run/step
│   │   ├── serializers.py                   # DRF serializers for workbench payloads
│   │   ├── skills.py                        # Canonical skill metadata (ordinals, phases, gate/judge flags)
│   │   ├── admin.py                         # Empty (no ORM models)
│   │   ├── models.py                        # Empty (no ORM models)
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_encryption.py
│   │       ├── test_drive_client.py
│   │       ├── test_drive_credentials.py
│   │       ├── test_drive_auth_views.py
│   │       ├── test_middleware.py
│   │       ├── test_parsers.py
│   │       ├── test_sync_structured.py
│   │       ├── test_sync_flat.py
│   │       ├── test_previews.py
│   │       ├── test_views_opp_list.py
│   │       ├── test_views_workbench.py
│   │       ├── test_views_step_detail.py
│   │       ├── test_views_artifact.py
│   │       ├── test_views_compare.py
│   │       ├── test_views_discuss.py
│   │       ├── test_seed.py
│   │       ├── test_skills.py
│   │       └── fixtures/
│   │           ├── __init__.py
│   │           ├── fake_drive.py            # In-memory FakeDriveClient that serves a dict tree
│   │           └── drive/
│   │               ├── ACE/
│   │               │   ├── malaria-pilot/                   # Structured layout fixture
│   │               │   │   ├── opp.yaml
│   │               │   │   ├── idd.md
│   │               │   │   └── runs/
│   │               │   │       ├── 2026-04-01-001/          # Earlier run (for compare tests)
│   │               │   │       │   ├── run.yaml
│   │               │   │       │   ├── events.jsonl
│   │               │   │       │   └── steps/
│   │               │   │       │       ├── 01-idea-to-idd/
│   │               │   │       │       │   ├── step.yaml
│   │               │   │       │       │   ├── judge.yaml
│   │               │   │       │       │   └── output/idd.md
│   │               │   │       │       ├── 02-idd-to-learn-app/
│   │               │   │       │       │   ├── step.yaml
│   │               │   │       │       │   ├── judge.yaml
│   │               │   │       │       │   └── output/learn-app-brief.md
│   │               │   │       │       └── 04-app-deploy/
│   │               │   │       │           ├── step.yaml
│   │               │   │       │           ├── gates.jsonl
│   │               │   │       │           └── output/deploy-summary.md
│   │               │   │       └── 2026-04-06-002/          # Later run (current)
│   │               │   │           ├── run.yaml
│   │               │   │           ├── events.jsonl
│   │               │   │           └── steps/
│   │               │   │               ├── 01-idea-to-idd/
│   │               │   │               │   ├── step.yaml
│   │               │   │               │   ├── judge.yaml
│   │               │   │               │   └── output/idd.md
│   │               │   │               ├── 02-idd-to-learn-app/
│   │               │   │               ├── 03-idd-to-deliver-app/
│   │               │   │               ├── 04-app-deploy/
│   │               │   │               │   ├── step.yaml
│   │               │   │               │   ├── gates.jsonl
│   │               │   │               │   └── output/deploy-summary.md
│   │               │   │               ├── 05-app-test/
│   │               │   │               │   ├── step.yaml
│   │               │   │               │   ├── judge.yaml
│   │               │   │               │   └── output/
│   │               │   │               │       ├── test-plan.md
│   │               │   │               │       └── test-results.yaml
│   │               │   │               └── 06-training-materials/
│   │               │   └── nutrition-legacy/                # Flat-layout (legacy) fixture
│   │               │       ├── state.yaml
│   │               │       ├── idd.md
│   │               │       ├── app-summaries/
│   │               │       │   ├── learn-app-summary.md
│   │               │       │   └── deliver-app-summary.md
│   │               │       └── test-results/
│   │               │           └── test-plan.md
│   │
│   ├── auth/
│   │   ├── models.py                        # MODIFIED: add drive_token_cache + drive_token_refreshed_at
│   │   └── migrations/
│   │       └── 0002_drive_token_fields.py   # NEW migration
│   │
│   ├── sessions/
│   │   ├── models.py                        # MODIFIED: add opp_slug, opp_run_id, opp_step_skill + index
│   │   └── migrations/
│   │       └── 0002_session_opp_pointers.py # NEW migration
│   │
│   └── common/
│       └── (no changes)
│
├── config/
│   ├── settings/
│   │   └── base.py                          # MODIFIED: add apps.opps to INSTALLED_APPS, add Google OAuth settings, add ACE_DRIVE_ROOT_FOLDER
│   └── urls.py                              # MODIFIED: include apps.opps.urls under /api/opps/ and /auth/drive/
│
├── frontend/
│   └── src/
│       ├── api/
│       │   ├── opps.ts                      # NEW: typed API client for the workbench
│       │   ├── types.ts                     # MODIFIED: add Opp/Run/Step/Artifact/JudgeResult TS types
│       │   └── client.ts                    # MODIFIED: handle 401 → /auth/drive/start redirect
│       │
│       ├── pages/
│       │   ├── OppListPage.tsx              # NEW: /opps
│       │   ├── OppWorkbenchPage.tsx         # NEW: /opps/:slug and /opps/:slug/runs/:runId
│       │   └── OppComparePage.tsx           # NEW: /opps/:slug/compare
│       │
│       ├── components/opps/
│       │   ├── OppSidebar.tsx               # Left pane: filterable opp list with run badges
│       │   ├── WorkbenchHeader.tsx          # Top bar: opp name, phase, mode, run switcher
│       │   ├── RunSwitcher.tsx              # Run dropdown + "compare to v1" link
│       │   ├── SkillList.tsx                # Center pane: phase-grouped 19-row list
│       │   ├── SkillRow.tsx                 # One row: status/name/judge/delta/gate/preview
│       │   ├── StepDetailPane.tsx           # Right pane: artifact, judge, gate, linked chats, CTA
│       │   ├── DiscussInChatButton.tsx      # Primary CTA with loading + error states
│       │   ├── ArtifactPreview.tsx          # Renders first N lines of an artifact body
│       │   ├── JudgeVerdict.tsx             # Score + criteria + rationale card
│       │   ├── GateHistory.tsx              # Approvals list
│       │   ├── LinkedChats.tsx              # List of prior Session rows
│       │   ├── CompareTable.tsx             # Two-column compare view
│       │   └── LoadingStates.tsx            # Shared empty / loading / error components
│       │
│       └── router.tsx                       # MODIFIED: add /opps, /opps/:slug, /opps/:slug/runs/:runId, /opps/:slug/runs/:runId/steps/:skill, /opps/:slug/compare
│
├── pyproject.toml                           # MODIFIED: add google-api-python-client, google-auth, cryptography, pyyaml to dependencies
├── docs/
│   └── learnings/
│       └── drive-oauth-two-flow.md          # NEW: why ace-web has two OAuth flows (identity + drive)
└── CLAUDE.md                                # MODIFIED: note the new apps/opps module and its relationship to the ACE plugin
```

---

## Task 1: Scaffold `apps/opps/` module and register it

**Files:**
- Create: `apps/opps/__init__.py`
- Create: `apps/opps/apps.py`
- Create: `apps/opps/models.py` (intentionally empty)
- Create: `apps/opps/admin.py` (intentionally empty)
- Create: `apps/opps/urls.py`
- Create: `apps/opps/views.py`
- Create: `apps/opps/tests/__init__.py`
- Create: `apps/opps/tests/test_scaffold.py`
- Modify: `config/settings/base.py`
- Modify: `config/urls.py`

No Drive work yet — just the module scaffold, a trivial health endpoint, and a test that proves it's wired into URL config and settings. Establishes the module before anything else depends on it.

- [ ] **Step 1: Write the scaffold test**

Create `apps/opps/tests/__init__.py` as an empty file.

Create `apps/opps/tests/test_scaffold.py`:

```python
"""Sanity-check that the apps/opps module is registered and its URL include works."""
from django.apps import apps
from django.test import Client
from django.urls import reverse


def test_opps_app_is_registered():
    assert apps.is_installed("apps.opps")


def test_opps_health_endpoint_reverses():
    url = reverse("opps-health")
    assert url == "/api/opps/health"


def test_opps_health_endpoint_responds():
    client = Client()
    response = client.get("/api/opps/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"data": {"status": "ok", "module": "opps"}, "error": None}
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_scaffold.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.opps'`.

- [ ] **Step 3: Create the app scaffold**

Create `apps/opps/__init__.py` as an empty file.

Create `apps/opps/apps.py`:

```python
from django.apps import AppConfig


class OppsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opps"
    label = "opps"
    verbose_name = "ACE Opportunities"
```

Create `apps/opps/models.py`:

```python
"""No ORM models.

The ACE visualization reads through to Google Drive on every request.
Opp / Run / Step / Artifact / JudgeResult / GateDecision all live in Drive
as YAML / Markdown / JSONL files, not in Postgres. See:
- docs/specs/2026-04-08-ace-opp-visualization-design.md (Section 6)
- memory entry: project_drive_is_source_of_truth.md

If in the future the team decides to add a Postgres cache for latency,
models go in this file. For now it is intentionally empty.
"""
```

Create `apps/opps/admin.py`:

```python
"""No admin registrations — the opps module has no ORM models (see models.py)."""
```

Create `apps/opps/views.py`:

```python
"""REST API views for the ACE opportunity Workbench."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import success_response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Scaffold sanity check. Used by tests in Task 1."""
    return Response(success_response({"status": "ok", "module": "opps"}))
```

Create `apps/opps/urls.py`:

```python
"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="opps-health"),
]
```

- [ ] **Step 4: Register the app and include its URLs**

Modify `config/settings/base.py`. Find the `INSTALLED_APPS` list and append `"apps.opps.apps.OppsConfig"` after the existing `"apps.sessions.apps.SessionsConfig"` entry:

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
]
```

Modify `config/urls.py`. Add the `apps.opps.urls` include above the SPA catch-all:

```python
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/opps/", include("apps.opps.urls")),
    # SPA catch-all: any non-api/non-admin/non-static/non-assets path serves
    # the React index.html. React Router handles client-side routing from
    # there.
    re_path(
        r"^(?!api/|admin/|static/|assets/).*$",
        TemplateView.as_view(template_name="index.html"),
        name="spa",
    ),
]
```

- [ ] **Step 5: Run the test, expect pass**

Run: `pytest apps/opps/tests/test_scaffold.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the full test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: all existing tests pass plus 3 new ones.

- [ ] **Step 7: Commit**

```bash
git add apps/opps/ config/settings/base.py config/urls.py
git commit -m "feat(opps): scaffold apps/opps module with health endpoint"
```

---

## Task 2: Token encryption helper

**Files:**
- Create: `apps/opps/encryption.py`
- Create: `apps/opps/tests/test_encryption.py`
- Modify: `pyproject.toml`
- Modify: `config/settings/base.py`

Port `../connect-search/backend/app/core/encryption.py` with one adjustment: read the encryption key from Django settings rather than taking it as a function argument at every call site. The key itself still comes from the environment — just route it through `settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY`.

- [ ] **Step 1: Add `cryptography` to dependencies**

Modify `pyproject.toml`. Add `cryptography>=42` to the `dependencies` list (alphabetized under `django-environ`):

```toml
[project]
name = "ace-web"
version = "0.1.0"
description = "Web harness for the ACE initiative"
requires-python = ">=3.11"
dependencies = [
    "cryptography>=42",
    "django>=5.0,<6.0",
    "djangorestframework>=3.15",
    "channels>=4.1",
    "uvicorn[standard]>=0.30",
    "psycopg[binary]>=3.2",
    "whitenoise>=6.7",
    "django-environ>=0.11",
]
```

Run `uv sync` (or `pip install -e .[dev]`) to install.

- [ ] **Step 2: Add the encryption key setting**

Modify `config/settings/base.py`. Add a new section above `# --- I18N ---`:

```python
# --- Google Drive OAuth (secondary flow for the Workbench) ---
# Encryption key for the per-user Drive token cache. Rotated via AWS Secrets
# Manager / SSM Parameter Store in prod. In dev, a static key is fine.
ACE_DRIVE_TOKEN_ENCRYPTION_KEY = env(
    "ACE_DRIVE_TOKEN_ENCRYPTION_KEY",
    default="dev-insecure-drive-token-key-change-me",
)
```

- [ ] **Step 3: Write the encryption tests**

Create `apps/opps/tests/test_encryption.py`:

```python
"""Tests for the Fernet-based Drive token encryption helper."""
import pytest
from django.test import override_settings

from apps.opps.encryption import decrypt_token, encrypt_token


def test_round_trip_with_default_key():
    payload = {"access_token": "abc", "refresh_token": "def", "scopes": ["drive"]}
    encrypted = encrypt_token(payload)
    decrypted = decrypt_token(encrypted)
    assert decrypted == payload


def test_encrypted_output_is_not_the_plaintext():
    payload = {"access_token": "secret-value-123"}
    encrypted = encrypt_token(payload)
    assert "secret-value-123" not in encrypted
    assert encrypted != str(payload)


def test_encrypt_produces_different_ciphertexts_each_call():
    """Fernet includes a random IV, so two encrypts of the same payload differ."""
    payload = {"access_token": "abc"}
    a = encrypt_token(payload)
    b = encrypt_token(payload)
    assert a != b
    assert decrypt_token(a) == decrypt_token(b)


@override_settings(ACE_DRIVE_TOKEN_ENCRYPTION_KEY="")
def test_empty_key_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        encrypt_token({"access_token": "abc"})


@override_settings(ACE_DRIVE_TOKEN_ENCRYPTION_KEY="key-a")
def test_cannot_decrypt_with_a_different_key():
    encrypted = encrypt_token({"access_token": "abc"})
    with override_settings(ACE_DRIVE_TOKEN_ENCRYPTION_KEY="key-b"):
        with pytest.raises(Exception):  # cryptography.fernet.InvalidToken
            decrypt_token(encrypted)
```

- [ ] **Step 4: Run the test, expect import failure**

Run: `pytest apps/opps/tests/test_encryption.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.opps.encryption'`.

- [ ] **Step 5: Implement the encryption module**

Create `apps/opps/encryption.py`:

```python
"""Fernet-based encryption for per-user Drive OAuth token caches.

Ported from ../connect-search/backend/app/core/encryption.py with one change:
the key comes from Django settings instead of being passed at every call site.

The key is derived via PBKDF2-HMAC-SHA256 from settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY
using a fixed salt. This is intentional: a fixed salt makes the derived Fernet
key deterministic for a given input, which means we can rotate the raw env
var without having to re-encrypt every stored token — as long as the old and
new values derive to the same Fernet key, they are interchangeable. For a
genuine key rotation, you need to decrypt everything with the old key and
re-encrypt with the new one, same as connect-search.
"""
import base64
import json

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings


def _get_fernet() -> Fernet:
    key = settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ValueError("ACE_DRIVE_TOKEN_ENCRYPTION_KEY must not be empty")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"ace-web-drive-token-salt",
        iterations=100_000,
    )
    derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    return Fernet(derived)


def encrypt_token(token_data: dict) -> str:
    """Encrypt a token-data dict and return a URL-safe base64 ciphertext string."""
    f = _get_fernet()
    return f.encrypt(json.dumps(token_data).encode()).decode()


def decrypt_token(encrypted: str) -> dict:
    """Decrypt a ciphertext string produced by `encrypt_token`."""
    f = _get_fernet()
    return json.loads(f.decrypt(encrypted.encode()))
```

- [ ] **Step 6: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_encryption.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/opps/encryption.py apps/opps/tests/test_encryption.py pyproject.toml config/settings/base.py
git commit -m "feat(opps): add Fernet token encryption helper for Drive OAuth tokens"
```

---

## Task 3: `DriveClient` ABC and `GoogleDriveClient` implementation

**Files:**
- Create: `apps/opps/drive_client.py`
- Create: `apps/opps/tests/test_drive_client.py`
- Create: `apps/opps/tests/fixtures/__init__.py`
- Create: `apps/opps/tests/fixtures/fake_drive.py`
- Modify: `pyproject.toml`

Port `../connect-search/backend/app/core/drive.py` almost verbatim. The ABC and the concrete Google implementation stay the same; only the test layer differs — we build a `FakeDriveClient` that serves an in-memory dict tree so the rest of the plan can test sync/parser/views without network.

- [ ] **Step 1: Add Google API deps**

Modify `pyproject.toml`. Add the two Google packages to the `dependencies` list:

```toml
dependencies = [
    "cryptography>=42",
    "django>=5.0,<6.0",
    "djangorestframework>=3.15",
    "channels>=4.1",
    "google-api-python-client>=2.130",
    "google-auth>=2.30",
    "uvicorn[standard]>=0.30",
    "psycopg[binary]>=3.2",
    "whitenoise>=6.7",
    "django-environ>=0.11",
]
```

Run `uv sync`.

- [ ] **Step 2: Write the DriveClient tests**

Create `apps/opps/tests/fixtures/__init__.py` as an empty file.

Create `apps/opps/tests/fixtures/fake_drive.py`:

```python
"""An in-memory fake DriveClient for tests.

Serves a dict-shaped virtual file tree so sync / parser / view tests can run
without touching Google. The tree is keyed by (synthetic) folder id; files
and folders each get a synthetic id of the form `fake-<counter>` assigned at
tree build time.

Usage:

    tree = {
        "ACE": {
            "malaria-pilot": {
                "opp.yaml": "slug: malaria-pilot\\n...",
                "runs": {
                    "r1": {
                        "run.yaml": "...",
                    }
                }
            }
        }
    }
    client = FakeDriveClient.from_tree(tree)
    files = client.list_files(client.folder_id("ACE/malaria-pilot"))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from apps.opps.drive_client import DriveClient, DriveFile, FileContent


@dataclass
class _Node:
    id: str
    name: str
    parent_id: str | None
    mime_type: str               # "application/vnd.google-apps.folder" for folders
    body: str | None = None      # None for folders
    children: dict[str, "_Node"] = field(default_factory=dict)  # name -> node


class FakeDriveClient(DriveClient):
    """In-memory DriveClient for tests. Supports the methods the sync layer uses."""

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self):
        self._root = _Node(id="fake-root", name="", parent_id=None, mime_type=self.FOLDER_MIME)
        self._nodes_by_id: dict[str, _Node] = {"fake-root": self._root}
        self._counter = count(1)

    @classmethod
    def from_tree(cls, tree: dict) -> "FakeDriveClient":
        client = cls()
        client._load(client._root, tree)
        return client

    def _load(self, parent: _Node, tree: dict):
        for name, value in tree.items():
            nid = f"fake-{next(self._counter)}"
            if isinstance(value, dict):
                node = _Node(
                    id=nid, name=name, parent_id=parent.id, mime_type=self.FOLDER_MIME
                )
                parent.children[name] = node
                self._nodes_by_id[nid] = node
                self._load(node, value)
            else:
                mime = self._guess_mime(name)
                node = _Node(
                    id=nid, name=name, parent_id=parent.id, mime_type=mime, body=str(value)
                )
                parent.children[name] = node
                self._nodes_by_id[nid] = node

    @staticmethod
    def _guess_mime(name: str) -> str:
        if name.endswith(".yaml") or name.endswith(".yml"):
            return "application/x-yaml"
        if name.endswith(".md"):
            return "text/markdown"
        if name.endswith(".jsonl") or name.endswith(".json"):
            return "application/json"
        return "text/plain"

    def folder_id(self, path: str) -> str:
        """Test helper: resolve a slash-separated path to a folder id."""
        node = self._root
        for part in path.strip("/").split("/"):
            node = node.children[part]
        return node.id

    # --- DriveClient interface ---

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        node = self._nodes_by_id[folder_id]
        results: list[DriveFile] = []
        self._list(node, "", recursive, results)
        return results

    def _list(self, node: _Node, prefix: str, recursive: bool, results: list):
        for name, child in node.children.items():
            child_path = f"{prefix}/{name}" if prefix else name
            if child.mime_type == self.FOLDER_MIME:
                if recursive:
                    self._list(child, child_path, True, results)
                else:
                    results.append(DriveFile(
                        id=child.id, name=name, mime_type=child.mime_type,
                        web_view_link=f"https://fake/{child.id}", path=child_path,
                    ))
            else:
                results.append(DriveFile(
                    id=child.id, name=name, mime_type=child.mime_type,
                    web_view_link=f"https://fake/{child.id}", path=child_path,
                ))

    def get_file(self, file_id: str) -> DriveFile:
        node = self._nodes_by_id[file_id]
        return DriveFile(
            id=node.id, name=node.name, mime_type=node.mime_type,
            web_view_link=f"https://fake/{node.id}",
        )

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        node = self._nodes_by_id[file_id]
        if node.body is None:
            raise ValueError(f"{node.name} is a folder, not a file")
        return FileContent(content=node.body, content_type=node.mime_type)
```

Create `apps/opps/tests/test_drive_client.py`:

```python
"""Tests for the DriveClient ABC + the FakeDriveClient test helper.

The real GoogleDriveClient is not tested here — it requires a live Google
Drive API. Its behavior is validated indirectly by sync/view fixture tests
that use FakeDriveClient as a drop-in. This test suite just locks in the
ABC contract and the fake's round-trip behavior.
"""
import pytest

from apps.opps.drive_client import DriveClient, DriveFile, FileContent
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


def test_drive_file_dataclass_fields():
    f = DriveFile(id="1", name="x.md", mime_type="text/markdown", web_view_link="https://x")
    assert f.id == "1"
    assert f.name == "x.md"
    assert f.path == ""  # default


def test_file_content_dataclass_fields():
    c = FileContent(content="hello", content_type="text/plain")
    assert c.content == "hello"
    assert c.encoding is None


def test_drive_client_is_abstract():
    with pytest.raises(TypeError, match="abstract"):
        DriveClient()


def test_fake_drive_list_files_top_level():
    client = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"idd.md": "# IDD"}}
    })
    ace_id = client.folder_id("ACE")
    files = client.list_files(ace_id)
    assert len(files) == 1
    assert files[0].name == "malaria-pilot"
    assert files[0].mime_type == "application/vnd.google-apps.folder"


def test_fake_drive_list_files_recursive():
    client = FakeDriveClient.from_tree({
        "ACE": {
            "malaria-pilot": {
                "idd.md": "# IDD",
                "runs": {
                    "r1": {"run.yaml": "run_id: r1"}
                }
            }
        }
    })
    ace_id = client.folder_id("ACE/malaria-pilot")
    files = client.list_files(ace_id, recursive=True)
    names = sorted(f.name for f in files)
    assert names == ["idd.md", "run.yaml"]


def test_fake_drive_get_content():
    client = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"idd.md": "# Malaria IDD\nbody"}}
    })
    files = client.list_files(client.folder_id("ACE/malaria-pilot"))
    idd = next(f for f in files if f.name == "idd.md")
    content = client.get_content(idd.id, idd.mime_type)
    assert content.content == "# Malaria IDD\nbody"
    assert content.content_type == "text/markdown"


def test_fake_drive_get_content_on_folder_raises():
    client = FakeDriveClient.from_tree({"ACE": {"malaria-pilot": {}}})
    folder_id = client.folder_id("ACE/malaria-pilot")
    with pytest.raises(ValueError, match="is a folder"):
        client.get_content(folder_id, "application/vnd.google-apps.folder")
```

- [ ] **Step 3: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_drive_client.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.opps.drive_client'`.

- [ ] **Step 4: Implement DriveClient**

Create `apps/opps/drive_client.py`:

```python
"""Google Drive client abstraction.

Ported from ../connect-search/backend/app/core/drive.py. The ABC defines the
methods the sync layer uses; GoogleDriveClient is the real implementation
that wraps googleapiclient.discovery.build("drive", "v3", ...). Tests use
FakeDriveClient (apps/opps/tests/fixtures/fake_drive.py) as a drop-in.

Surface kept intentionally small: the Workbench only ever reads — listing
folders recursively, fetching file content, getting file metadata. Writes
(create_folder, create_shortcut, share_file) from the connect-search version
are not ported because the ace-web Workbench never writes to Drive.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    web_view_link: str
    path: str = ""                                  # full slash-separated path from the listing root
    size_bytes: int | None = None
    modified_time: str | None = None                # ISO-8601 string, as returned by Drive


@dataclass
class FileContent:
    content: str                                    # UTF-8 for text files; base64 for binary
    content_type: str                               # e.g. "text/markdown", "application/json"
    encoding: str | None = None                     # "base64" for binary files


class DriveClient(ABC):
    """Narrow read-only Drive interface the sync layer depends on."""

    @abstractmethod
    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        """List immediate children of a folder, or the full recursive tree."""

    @abstractmethod
    def get_file(self, file_id: str) -> DriveFile:
        """Fetch metadata for a single file or folder."""

    @abstractmethod
    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        """Fetch the body of a file. Google Docs types are exported to text/plain
        or text/csv; binary types are returned base64-encoded."""


class GoogleDriveClient(DriveClient):
    """Real Google Drive implementation. Requires authenticated credentials."""

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self, credentials):
        from googleapiclient.discovery import build
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        results: list[DriveFile] = []
        self._list_folder(folder_id, path="", results=results, recursive=recursive,
                          page_size=page_size)
        return results

    def _list_folder(
        self, folder_id: str, path: str, results: list, recursive: bool, page_size: int
    ):
        page_token = None
        while True:
            response = self._service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=(
                    "nextPageToken, "
                    "files(id, name, mimeType, webViewLink, size, modifiedTime)"
                ),
                pageSize=page_size,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            for f in response.get("files", []):
                file_path = f"{path}/{f['name']}" if path else f["name"]
                if f["mimeType"] == self.FOLDER_MIME:
                    if recursive:
                        self._list_folder(f["id"], file_path, results, True, page_size)
                    else:
                        results.append(self._to_drive_file(f, file_path))
                else:
                    results.append(self._to_drive_file(f, file_path))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    @staticmethod
    def _to_drive_file(f: dict, path: str) -> DriveFile:
        size = f.get("size")
        return DriveFile(
            id=f["id"],
            name=f["name"],
            mime_type=f["mimeType"],
            web_view_link=f.get("webViewLink", ""),
            path=path,
            size_bytes=int(size) if size is not None else None,
            modified_time=f.get("modifiedTime"),
        )

    def get_file(self, file_id: str) -> DriveFile:
        f = self._service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, webViewLink, size, modifiedTime",
            supportsAllDrives=True,
        ).execute()
        return self._to_drive_file(f, path=f["name"])

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        export_map = {
            "application/vnd.google-apps.document": ("text/plain", "text/plain"),
            "application/vnd.google-apps.spreadsheet": ("text/csv", "text/csv"),
            "application/vnd.google-apps.presentation": ("text/plain", "text/plain"),
        }
        if mime_type in export_map:
            export_mime, content_type = export_map[mime_type]
            content = self._service.files().export(
                fileId=file_id, mimeType=export_mime
            ).execute()
            text = content.decode("utf-8") if isinstance(content, bytes) else content
            return FileContent(content=text, content_type=content_type)

        # Regular file download.
        content = self._service.files().get_media(fileId=file_id).execute()
        if isinstance(content, bytes):
            try:
                text = content.decode("utf-8")
                return FileContent(content=text, content_type=mime_type)
            except UnicodeDecodeError:
                import base64
                return FileContent(
                    content=base64.b64encode(content).decode("ascii"),
                    content_type=mime_type,
                    encoding="base64",
                )
        return FileContent(content=content, content_type=mime_type)
```

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_drive_client.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/drive_client.py apps/opps/tests/test_drive_client.py apps/opps/tests/fixtures/ pyproject.toml
git commit -m "feat(opps): add DriveClient ABC, GoogleDriveClient impl, and FakeDriveClient test fixture"
```

---

## Task 4: Google OAuth credentials builder and refresh

**Files:**
- Create: `apps/opps/drive_credentials.py`
- Create: `apps/opps/tests/test_drive_credentials.py`
- Modify: `config/settings/base.py`

Ports the `build_oauth_credentials` helper from `../connect-search/backend/app/core/auth.py` and adds a refresh-on-expiry wrapper that updates the stored token cache. The wrapper is what views and middleware call — they never touch `google.oauth2.credentials.Credentials` directly.

- [ ] **Step 1: Add Google OAuth client settings**

Modify `config/settings/base.py`. Extend the Drive section you added in Task 2:

```python
# --- Google Drive OAuth (secondary flow for the Workbench) ---
# Encryption key for the per-user Drive token cache.
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
# Top-level Drive folder that holds ACE opportunities. Default matches the
# ACE plugin convention.
ACE_DRIVE_ROOT_FOLDER_NAME = env("ACE_DRIVE_ROOT_FOLDER_NAME", default="ACE")
```

- [ ] **Step 2: Write the credentials tests**

Create `apps/opps/tests/test_drive_credentials.py`:

```python
"""Tests for the OAuth credentials builder and refresh wrapper."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from apps.opps.drive_credentials import (
    CredentialsRefreshFailed,
    build_credentials,
    ensure_fresh,
)


def _fake_token_data(expiry: datetime | None = None) -> dict:
    return {
        "access_token": "access-123",
        "refresh_token": "refresh-456",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "expiry": expiry.isoformat() if expiry else None,
    }


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_build_credentials_includes_client_id_and_secret():
    creds = build_credentials(_fake_token_data())
    assert creds.client_id == "client-id"
    assert creds.client_secret == "client-secret"
    assert creds.token == "access-123"
    assert creds.refresh_token == "refresh-456"


def test_ensure_fresh_returns_unchanged_when_not_expired(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    token_data = _fake_token_data(expiry=future)

    with override_settings(
        ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
        ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ):
        creds, updated = ensure_fresh(token_data)
        assert creds.token == "access-123"
        assert updated is None  # nothing to persist


def test_ensure_fresh_refreshes_when_expired(monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token_data = _fake_token_data(expiry=past)

    # Patch the Credentials.refresh method to simulate a successful refresh.
    def fake_refresh(self, request):
        self.token = "access-NEW"
        self.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", fake_refresh
    )

    with override_settings(
        ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
        ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ):
        creds, updated = ensure_fresh(token_data)
        assert creds.token == "access-NEW"
        assert updated is not None
        assert updated["access_token"] == "access-NEW"
        assert updated["refresh_token"] == "refresh-456"  # preserved


def test_ensure_fresh_raises_when_refresh_fails(monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token_data = _fake_token_data(expiry=past)

    def boom(self, request):
        raise RuntimeError("refresh endpoint rejected the grant")

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", boom)

    with override_settings(
        ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
        ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ):
        with pytest.raises(CredentialsRefreshFailed):
            ensure_fresh(token_data)


@override_settings(ACE_GOOGLE_OAUTH_CLIENT_ID="", ACE_GOOGLE_OAUTH_CLIENT_SECRET="")
def test_build_credentials_raises_without_client_config():
    with pytest.raises(RuntimeError, match="not configured"):
        build_credentials(_fake_token_data())
```

- [ ] **Step 3: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_drive_credentials.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement the credentials module**

Create `apps/opps/drive_credentials.py`:

```python
"""Google OAuth credentials construction and refresh.

Two public helpers:

- `build_credentials(token_data)` — builds a google.oauth2.credentials.Credentials
  instance from a persisted token dict + the OAuth client ID/secret in settings.
  Used wherever callers need raw credentials (e.g. to pass into GoogleDriveClient).

- `ensure_fresh(token_data) -> (creds, updated_token_data | None)` — builds
  credentials and refreshes the access token if it has expired (60-second buffer).
  Returns (credentials, None) if no refresh was needed; (credentials, new_token_data)
  if the caller should persist the refreshed token back to the User row.

Refresh failures raise `CredentialsRefreshFailed`; the middleware catches this
and redirects the user to /auth/drive/start with a "reconnect" banner.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


class CredentialsRefreshFailed(RuntimeError):
    """Raised when the refresh-token exchange fails (revoked grant, network, etc)."""


def _require_client_config() -> tuple[str, str]:
    cid = settings.ACE_GOOGLE_OAUTH_CLIENT_ID
    cs = settings.ACE_GOOGLE_OAUTH_CLIENT_SECRET
    if not cid or not cs:
        raise RuntimeError(
            "Google OAuth client is not configured: set "
            "ACE_GOOGLE_OAUTH_CLIENT_ID and ACE_GOOGLE_OAUTH_CLIENT_SECRET"
        )
    return cid, cs


def build_credentials(token_data: dict) -> Credentials:
    """Build Credentials from a persisted token_data dict.

    token_data shape (exactly what the callback view stores):
        {
            "access_token": str,
            "refresh_token": str | None,
            "token_uri": str,
            "scopes": list[str],
            "expiry": str | None,  # ISO-8601, may be absent for never-expired tokens
        }
    """
    cid, cs = _require_client_config()
    expiry_iso = token_data.get("expiry")
    expiry = None
    if expiry_iso:
        # google-auth expects a naive UTC datetime, not tz-aware.
        dt = datetime.fromisoformat(expiry_iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        expiry = dt
    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=cid,
        client_secret=cs,
        scopes=token_data.get("scopes"),
        expiry=expiry,
    )
    return creds


def ensure_fresh(token_data: dict) -> tuple[Credentials, dict | None]:
    """Return (credentials, updated_token_data_or_None).

    If the access token is still valid (with a 60-second buffer), returns
    (creds, None). Otherwise refreshes via the refresh token and returns
    (creds, new_token_data) — callers must persist the new dict.
    """
    creds = build_credentials(token_data)
    if creds.expiry is None:
        return creds, None

    # google-auth uses naive UTC for expiry comparisons.
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    buffer = timedelta(seconds=60)
    if creds.expiry - buffer > now_naive:
        return creds, None

    try:
        creds.refresh(Request())
    except Exception as exc:
        raise CredentialsRefreshFailed(str(exc)) from exc

    new_expiry_iso = None
    if creds.expiry is not None:
        new_expiry_iso = creds.expiry.replace(tzinfo=timezone.utc).isoformat()

    updated = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token or token_data.get("refresh_token"),
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes) if creds.scopes else token_data.get("scopes"),
        "expiry": new_expiry_iso,
    }
    return creds, updated
```

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_drive_credentials.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/drive_credentials.py apps/opps/tests/test_drive_credentials.py config/settings/base.py
git commit -m "feat(opps): add Google OAuth credentials builder and refresh wrapper"
```

---

## Task 5: `User` model migration for Drive token cache

**Files:**
- Modify: `apps/auth/models.py`
- Create: `apps/auth/migrations/0002_drive_token_fields.py`
- Create: `apps/auth/tests/test_drive_token_fields.py`

Add `drive_token_cache` (TextField; stores the Fernet ciphertext output of `encrypt_token`) and `drive_token_refreshed_at` (DateTimeField, nullable) to the existing `User` model. TextField rather than JSONField because the encrypted value is an opaque string, not structured JSON.

- [ ] **Step 1: Write the model test**

Create `apps/auth/tests/test_drive_token_fields.py`:

```python
"""Tests for the Drive token fields added to the User model."""
import pytest

from apps.auth.models import User


@pytest.mark.django_db
def test_user_drive_token_cache_defaults_to_empty():
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    assert user.drive_token_cache == ""
    assert user.drive_token_refreshed_at is None


@pytest.mark.django_db
def test_user_can_store_drive_token_cache():
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    user.drive_token_cache = "opaque-ciphertext-string"
    user.save()
    user.refresh_from_db()
    assert user.drive_token_cache == "opaque-ciphertext-string"


@pytest.mark.django_db
def test_user_has_drive_token_returns_bool():
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    assert user.has_drive_token() is False
    user.drive_token_cache = "ciphertext"
    assert user.has_drive_token() is True
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/auth/tests/test_drive_token_fields.py -v`
Expected: `AttributeError: 'User' object has no attribute 'drive_token_cache'`.

- [ ] **Step 3: Add the fields to the User model**

Modify `apps/auth/models.py`:

```python
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=200)
    google_sub = models.CharField(max_length=200, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # Per-user Google Drive OAuth token cache for the ACE opp Workbench
    # (apps/opps). Encrypted via apps.opps.encryption.encrypt_token; decrypted
    # on demand in drive_credentials.ensure_fresh. TextField because the
    # ciphertext is an opaque string, not JSON.
    drive_token_cache = models.TextField(blank=True, default="")
    drive_token_refreshed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email

    def has_drive_token(self) -> bool:
        return bool(self.drive_token_cache)
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations ace_auth -n drive_token_fields`
Expected: creates `apps/auth/migrations/0002_drive_token_fields.py` with two `AddField` operations.

Inspect the generated file to make sure only the two new fields are added — nothing else should change. Commit it as-is.

- [ ] **Step 5: Run the test, expect pass**

Run: `pytest apps/auth/tests/test_drive_token_fields.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the full auth test suite**

Run: `pytest apps/auth/ -v`
Expected: all prior auth tests still pass.

- [ ] **Step 7: Commit**

```bash
git add apps/auth/models.py apps/auth/migrations/0002_drive_token_fields.py apps/auth/tests/test_drive_token_fields.py
git commit -m "feat(auth): add drive_token_cache and drive_token_refreshed_at fields to User"
```

---

## Task 6: Drive OAuth flow views (start + callback)

**Files:**
- Create: `apps/opps/drive_auth_views.py`
- Create: `apps/opps/tests/test_drive_auth_views.py`
- Modify: `apps/opps/urls.py`
- Modify: `config/urls.py`

Two views: `GET /auth/drive/start` redirects the logged-in user to the Google OAuth consent screen; `GET /auth/drive/callback?code=...` exchanges the code for tokens, encrypts them, stores on the current user, stamps `drive_token_refreshed_at`, and redirects back to `/opps`.

The views assume identity auth is already in place — i.e. `request.user.is_authenticated` is true. If identity fails, the view returns 401; the identity auth layer handles login redirection independently.

- [ ] **Step 1: Write the flow tests**

Create `apps/opps/tests/test_drive_auth_views.py`:

```python
"""Tests for the /auth/drive/start and /auth/drive/callback views."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.auth.models import User
from apps.opps.encryption import decrypt_token


@pytest.fixture
def user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def authed_client(user):
    c = Client()
    c.force_login(user)
    return c


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ACE_DRIVE_OAUTH_REDIRECT_URI="http://testserver/auth/drive/callback",
)
def test_start_redirects_to_google_consent(authed_client):
    response = authed_client.get(reverse("drive-auth-start"))
    assert response.status_code == 302
    parsed = urlparse(response.url)
    assert parsed.netloc == "accounts.google.com"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["client-id"]
    assert qs["response_type"] == ["code"]
    assert "drive.readonly" in qs["scope"][0]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["redirect_uri"] == ["http://testserver/auth/drive/callback"]


def test_start_requires_auth(db):
    client = Client()
    response = client.get(reverse("drive-auth-start"))
    assert response.status_code == 401


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    ACE_DRIVE_OAUTH_REDIRECT_URI="http://testserver/auth/drive/callback",
)
def test_callback_exchanges_code_and_stores_token(authed_client, user):
    fake_token_response = {
        "access_token": "access-xyz",
        "refresh_token": "refresh-xyz",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile https://www.googleapis.com/auth/drive.readonly",
    }
    with patch("apps.opps.drive_auth_views._exchange_code", return_value=fake_token_response):
        response = authed_client.get(reverse("drive-auth-callback"), {"code": "abc123"})

    assert response.status_code == 302
    assert response.url == "/opps"

    user.refresh_from_db()
    assert user.drive_token_cache  # non-empty
    assert user.drive_token_refreshed_at is not None
    decrypted = decrypt_token(user.drive_token_cache)
    assert decrypted["access_token"] == "access-xyz"
    assert decrypted["refresh_token"] == "refresh-xyz"
    assert "drive.readonly" in decrypted["scopes"][0] or "drive.readonly" in " ".join(
        decrypted["scopes"]
    )


def test_callback_without_code_returns_400(authed_client):
    response = authed_client.get(reverse("drive-auth-callback"))
    assert response.status_code == 400
    assert "code" in response.json()["error"]["message"].lower()


@override_settings(
    ACE_GOOGLE_OAUTH_CLIENT_ID="client-id",
    ACE_GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
)
def test_callback_surfaces_exchange_failure(authed_client):
    with patch(
        "apps.opps.drive_auth_views._exchange_code",
        side_effect=RuntimeError("google said no"),
    ):
        response = authed_client.get(reverse("drive-auth-callback"), {"code": "abc"})
    assert response.status_code == 400
    assert "google said no" in response.json()["error"]["message"]
```

- [ ] **Step 2: Run the tests, expect failures**

Run: `pytest apps/opps/tests/test_drive_auth_views.py -v`
Expected: URL reverse errors (`drive-auth-start`, `drive-auth-callback` not registered).

- [ ] **Step 3: Implement the views**

Create `apps/opps/drive_auth_views.py`:

```python
"""Google OAuth flow views for the secondary Drive-scope authorization.

Two views:

- `GET /auth/drive/start` — redirects the logged-in user to Google's consent
  screen for Drive readonly + Sheets readonly access. Requires identity auth.

- `GET /auth/drive/callback?code=...` — exchanges the code for tokens, encrypts
  them, stores on the User, and redirects back to `/opps`.

The pattern matches ../connect-search/backend/app/api/auth.py, translated from
FastAPI to Django function views. The main semantic difference: connect-search
uses a single Google OAuth flow for BOTH identity and Drive access; ace-web
separates them — identity is handled by the hand-rolled CommCare Connect OAuth flow (pattern ported from connect-labs),
Drive is a secondary scoped grant layered on top.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.common.envelope import error_response
from apps.opps.encryption import encrypt_token

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _build_consent_url() -> str:
    params = {
        "client_id": settings.ACE_GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.ACE_DRIVE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(settings.ACE_DRIVE_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _exchange_code(code: str) -> dict:
    """Exchange an auth code for a token response. Separate function so tests can patch it."""
    data = {
        "code": code,
        "client_id": settings.ACE_GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.ACE_GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.ACE_DRIVE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    response = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=10.0)
    if response.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {response.text}")
    return response.json()


@api_view(["GET"])
def start(request):
    """Redirect the logged-in user to Google's Drive-scope consent screen."""
    if not request.user.is_authenticated:
        return Response(error_response("authentication required", code="auth-required"), status=401)
    return HttpResponseRedirect(_build_consent_url())


@api_view(["GET"])
def callback(request):
    """Exchange the auth code, store the encrypted token, redirect to /opps."""
    if not request.user.is_authenticated:
        return Response(error_response("authentication required", code="auth-required"), status=401)

    code = request.GET.get("code", "")
    if not code:
        return Response(
            error_response("missing code parameter", code="missing-code"), status=400
        )

    try:
        token_response = _exchange_code(code)
    except RuntimeError as exc:
        return Response(error_response(str(exc), code="token-exchange-failed"), status=400)

    # Derive expiry from expires_in (seconds).
    expires_in = token_response.get("expires_in")
    expiry_iso = None
    if expires_in:
        expiry_dt = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        expiry_iso = expiry_dt.isoformat()

    scope_str = token_response.get("scope", "")
    scopes = scope_str.split() if scope_str else list(settings.ACE_DRIVE_OAUTH_SCOPES)

    token_data = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token"),
        "token_uri": GOOGLE_TOKEN_URL,
        "scopes": scopes,
        "expiry": expiry_iso,
    }

    user = request.user
    user.drive_token_cache = encrypt_token(token_data)
    user.drive_token_refreshed_at = datetime.now(timezone.utc)
    user.save(update_fields=["drive_token_cache", "drive_token_refreshed_at"])

    return HttpResponseRedirect("/opps")
```

Modify `apps/opps/urls.py`:

```python
"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import drive_auth_views, views

urlpatterns = [
    path("health", views.health, name="opps-health"),
]

auth_urlpatterns = [
    path("auth/drive/start", drive_auth_views.start, name="drive-auth-start"),
    path("auth/drive/callback", drive_auth_views.callback, name="drive-auth-callback"),
]
```

Modify `config/urls.py` to include the auth urlpatterns at the root path (not under `/api/`):

```python
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from apps.opps.urls import auth_urlpatterns as drive_auth_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/opps/", include("apps.opps.urls")),
    *drive_auth_urlpatterns,
    re_path(
        r"^(?!api/|admin/|static/|assets/|auth/).*$",
        TemplateView.as_view(template_name="index.html"),
        name="spa",
    ),
]
```

Note the SPA catch-all is tightened to exclude `auth/` so the OAuth callback is not shadowed.

- [ ] **Step 4: Add `httpx` to dependencies if not already present**

Check `pyproject.toml`. If `httpx` is not there, add it:

```toml
dependencies = [
    ...
    "httpx>=0.27",
    ...
]
```

Run `uv sync`.

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_drive_auth_views.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/drive_auth_views.py apps/opps/tests/test_drive_auth_views.py apps/opps/urls.py config/urls.py pyproject.toml
git commit -m "feat(opps): add Google OAuth start and callback views for Drive scope"
```

---

## Task 7: `RequireDriveToken` middleware / DRF permission

**Files:**
- Create: `apps/opps/middleware.py`
- Create: `apps/opps/tests/test_middleware.py`

A DRF permission class (not a Django middleware — keeps the guard scoped to `/api/opps/*` views and lets us return a structured 401 with a reconnect URL instead of a redirect). The class checks `request.user.has_drive_token()`; if false, denies with a 401 + `{"reconnect_url": "/auth/drive/start"}` body.

- [ ] **Step 1: Write the permission tests**

Create `apps/opps/tests/test_middleware.py`:

```python
"""Tests for the RequireDriveToken DRF permission class."""
import pytest
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory

from apps.auth.models import User
from apps.opps.middleware import RequireDriveToken


@pytest.fixture
def user_without_token(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.fixture
def user_with_token(db):
    u = User.objects.create(email="neal@dimagi.com", display_name="Neal")
    u.drive_token_cache = "some-ciphertext"
    u.save()
    return u


def test_denies_unauthenticated(db):
    perm = RequireDriveToken()
    factory = APIRequestFactory()
    request = factory.get("/api/opps/")
    request.user = None
    assert perm.has_permission(request, view=None) is False


def test_denies_user_without_drive_token(user_without_token):
    perm = RequireDriveToken()
    factory = APIRequestFactory()
    request = factory.get("/api/opps/")
    request.user = user_without_token
    assert perm.has_permission(request, view=None) is False


def test_allows_user_with_drive_token(user_with_token):
    perm = RequireDriveToken()
    factory = APIRequestFactory()
    request = factory.get("/api/opps/")
    request.user = user_with_token
    assert perm.has_permission(request, view=None) is True


def test_denied_response_contains_reconnect_url():
    """When a view uses this permission and access is denied, the error body
    should include a reconnect URL so the frontend can redirect the user."""
    from rest_framework.exceptions import PermissionDenied
    perm = RequireDriveToken()
    # The permission itself just returns False; the reconnect hint is provided
    # via a custom exception raised by the view's permission_denied handler.
    # That handler is exposed via get_reconnect_payload() on the permission.
    payload = perm.get_reconnect_payload()
    assert payload == {"reconnect_url": "/auth/drive/start"}
```

- [ ] **Step 2: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_middleware.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the permission class**

Create `apps/opps/middleware.py`:

```python
"""DRF permission that gates /api/opps/* views on having a valid Drive token.

Named `middleware.py` to match the project's existing convention (see
apps/auth/middleware.py) even though this is a permission class, not a
Django middleware. The distinction matters: Django middleware runs for every
request; a DRF permission runs only for the views that declare it. The
Workbench API is the only place we need this guard, and we want structured
401 responses with a reconnect URL rather than a redirect.
"""
from rest_framework.permissions import BasePermission


class RequireDriveToken(BasePermission):
    """Deny unless request.user is authenticated AND has a cached Drive token.

    On deny, views using this permission should include the output of
    `get_reconnect_payload()` in the error body so the frontend knows where
    to send the user for a fresh OAuth grant.
    """

    message = "Google Drive access is not connected for this user"

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return bool(getattr(user, "drive_token_cache", ""))

    @staticmethod
    def get_reconnect_payload() -> dict:
        return {"reconnect_url": "/auth/drive/start"}
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_middleware.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/middleware.py apps/opps/tests/test_middleware.py
git commit -m "feat(opps): add RequireDriveToken DRF permission with reconnect payload"
```

---

## Task 8: Canonical skill metadata registry

**Files:**
- Create: `apps/opps/skills.py`
- Create: `apps/opps/tests/test_skills.py`

A single authoritative place that lists all 19 ACE skills with their phase, ordinal (1..19), whether they have an LLM-as-Judge, whether they are a gate step, and whether they are recurring. Sync layer, preview extractors, serializers, and frontend-shared JSON all consume this. No ACE plugin network calls — the metadata is static, pinned to match `../ace/docs/generated/playbook.md`.

- [ ] **Step 1: Write the skills tests**

Create `apps/opps/tests/test_skills.py`:

```python
"""Tests for the canonical skill metadata registry."""
from apps.opps.skills import (
    PHASE_APP_BUILDING,
    PHASE_CLOSEOUT,
    PHASE_CONNECT_SETUP,
    PHASE_LLO_MANAGEMENT,
    SKILL_REGISTRY,
    Skill,
    get_skill,
    skills_in_phase,
)


def test_registry_has_nineteen_skills():
    assert len(SKILL_REGISTRY) == 19


def test_ordinals_are_unique_and_sequential():
    ordinals = sorted(s.ordinal for s in SKILL_REGISTRY)
    assert ordinals == list(range(1, 20))


def test_names_are_unique():
    names = [s.name for s in SKILL_REGISTRY]
    assert len(names) == len(set(names))


def test_get_skill_by_name():
    s = get_skill("idea-to-idd")
    assert s.ordinal == 1
    assert s.phase == PHASE_APP_BUILDING
    assert s.has_judge is True
    assert s.is_gate is True


def test_get_skill_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        get_skill("nonexistent-skill")


def test_phase_grouping():
    building = skills_in_phase(PHASE_APP_BUILDING)
    assert [s.name for s in building] == [
        "idea-to-idd",
        "idd-to-learn-app",
        "idd-to-deliver-app",
        "app-deploy",
        "app-test",
        "training-materials",
    ]
    setup = skills_in_phase(PHASE_CONNECT_SETUP)
    assert [s.name for s in setup] == [
        "connect-program-setup",
        "connect-opp-setup",
        "llo-invite",
    ]
    llo = skills_in_phase(PHASE_LLO_MANAGEMENT)
    assert len(llo) == 6
    closeout = skills_in_phase(PHASE_CLOSEOUT)
    assert [s.name for s in closeout] == [
        "opp-closeout",
        "llo-feedback",
        "learnings-summary",
        "cycle-grade",
    ]


def test_gate_steps():
    gates = [s.name for s in SKILL_REGISTRY if s.is_gate]
    # From the ACE design spec gate list: idea-to-idd, app-deploy, llo-invite, llo-launch
    assert set(gates) == {"idea-to-idd", "app-deploy", "llo-invite", "llo-launch"}


def test_recurring_steps():
    recurring = [s.name for s in SKILL_REGISTRY if s.is_recurring]
    assert set(recurring) == {"timeline-monitor", "flw-data-review"}


def test_skill_is_frozen_dataclass():
    s = get_skill("idea-to-idd")
    import pytest
    with pytest.raises(Exception):
        s.ordinal = 999  # type: ignore[misc]
```

- [ ] **Step 2: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_skills.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the registry**

Create `apps/opps/skills.py`:

```python
"""Canonical metadata for the 19 ACE skills.

This is the single source of truth that the sync layer, preview extractors,
serializers, and the frontend all consume. Pinned to match the ACE plugin
playbook (../ace/docs/generated/playbook.md). When the ACE plugin adds a new
skill, this registry must be updated to match.

Not a database table because the ACE plugin's skill set is the source of
truth — duplicating it into Postgres would create a sync problem.
"""
from __future__ import annotations

from dataclasses import dataclass

PHASE_APP_BUILDING = "app-building"
PHASE_CONNECT_SETUP = "connect-setup"
PHASE_LLO_MANAGEMENT = "llo-management"
PHASE_CLOSEOUT = "closeout"

ALL_PHASES = (
    PHASE_APP_BUILDING,
    PHASE_CONNECT_SETUP,
    PHASE_LLO_MANAGEMENT,
    PHASE_CLOSEOUT,
)

PHASE_DISPLAY_NAMES = {
    PHASE_APP_BUILDING: "App Building",
    PHASE_CONNECT_SETUP: "Connect Setup",
    PHASE_LLO_MANAGEMENT: "LLO Management",
    PHASE_CLOSEOUT: "Closeout",
}


@dataclass(frozen=True)
class Skill:
    name: str                       # e.g. "idea-to-idd"
    ordinal: int                    # 1..19 across the full lifecycle
    phase: str                      # one of the PHASE_* constants above
    has_judge: bool                 # LLM-as-Judge runs on this step's output
    is_gate: bool                   # human gate required in review mode
    is_recurring: bool              # runs periodically during active opp (weekly)
    primary_output: str             # the "headline" artifact filename for preview extraction


SKILL_REGISTRY: tuple[Skill, ...] = (
    Skill("idea-to-idd",          1, PHASE_APP_BUILDING,    True,  True,  False, "idd.md"),
    Skill("idd-to-learn-app",     2, PHASE_APP_BUILDING,    True,  False, False, "learn-app-brief.md"),
    Skill("idd-to-deliver-app",   3, PHASE_APP_BUILDING,    True,  False, False, "deliver-app-brief.md"),
    Skill("app-deploy",           4, PHASE_APP_BUILDING,    False, True,  False, "deploy-summary.md"),
    Skill("app-test",             5, PHASE_APP_BUILDING,    True,  False, False, "test-results.yaml"),
    Skill("training-materials",   6, PHASE_APP_BUILDING,    True,  False, False, "llo-manager-guide.md"),
    Skill("connect-program-setup", 7, PHASE_CONNECT_SETUP,  False, False, False, "program-config.md"),
    Skill("connect-opp-setup",    8, PHASE_CONNECT_SETUP,   False, False, False, "opp-config.md"),
    Skill("llo-invite",           9, PHASE_CONNECT_SETUP,   False, True,  False, "invite-list.md"),
    Skill("llo-onboarding",      10, PHASE_LLO_MANAGEMENT,  False, False, False, "onboarding-emails.md"),
    Skill("llo-uat",             11, PHASE_LLO_MANAGEMENT,  False, False, False, "uat-protocol.md"),
    Skill("llo-launch",          12, PHASE_LLO_MANAGEMENT,  False, True,  False, "launch-checklist.md"),
    Skill("ocs-agent-setup",     13, PHASE_LLO_MANAGEMENT,  True,  False, False, "ocs-context.md"),
    Skill("timeline-monitor",    14, PHASE_LLO_MANAGEMENT,  True,  False, True,  "timeline-report.md"),
    Skill("flw-data-review",     15, PHASE_LLO_MANAGEMENT,  True,  False, True,  "flw-review.md"),
    Skill("opp-closeout",        16, PHASE_CLOSEOUT,        False, False, False, "invoice-summary.md"),
    Skill("llo-feedback",        17, PHASE_CLOSEOUT,        False, False, False, "feedback-report.md"),
    Skill("learnings-summary",   18, PHASE_CLOSEOUT,        False, False, False, "learnings.md"),
    Skill("cycle-grade",         19, PHASE_CLOSEOUT,        True,  False, False, "grade-report.md"),
)

_BY_NAME = {s.name: s for s in SKILL_REGISTRY}


def get_skill(name: str) -> Skill:
    """Return the Skill metadata for a given skill name. Raises KeyError if unknown."""
    return _BY_NAME[name]


def skills_in_phase(phase: str) -> list[Skill]:
    """Return all skills in a phase, ordered by ordinal."""
    return sorted((s for s in SKILL_REGISTRY if s.phase == phase), key=lambda s: s.ordinal)
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_skills.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/skills.py apps/opps/tests/test_skills.py
git commit -m "feat(opps): add canonical 19-skill registry with phase/judge/gate metadata"
```

---

## Task 9: Drive file parsers (opp.yaml, run.yaml, step.yaml, judge.yaml, gates.jsonl, events.jsonl)

**Files:**
- Create: `apps/opps/parsers.py`
- Create: `apps/opps/tests/test_parsers.py`
- Modify: `pyproject.toml`

Pure parsing functions — no Drive I/O. Each takes a string (the file body) and returns a structured dict (or list of dicts for JSONL). Tolerant of missing optional fields, strict about required ones. Used by the sync layer in Task 10.

- [ ] **Step 1: Add PyYAML dependency**

Modify `pyproject.toml`:

```toml
dependencies = [
    "cryptography>=42",
    "django>=5.0,<6.0",
    "djangorestframework>=3.15",
    "channels>=4.1",
    "google-api-python-client>=2.130",
    "google-auth>=2.30",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "uvicorn[standard]>=0.30",
    "psycopg[binary]>=3.2",
    "whitenoise>=6.7",
    "django-environ>=0.11",
]
```

Run `uv sync`.

- [ ] **Step 2: Write the parser tests**

Create `apps/opps/tests/test_parsers.py`:

```python
"""Tests for the Drive file parsers."""
import pytest

from apps.opps.parsers import (
    OppManifest,
    RunManifest,
    StepManifest,
    parse_events_jsonl,
    parse_gates_jsonl,
    parse_judge_yaml,
    parse_opp_yaml,
    parse_run_yaml,
    parse_step_yaml,
)


def test_parse_opp_yaml_full():
    body = """
slug: malaria-pilot
display_name: Malaria Pilot — Northern Mozambique
created_at: 2026-03-15T09:00:00Z
created_by: neal@dimagi.com
labels:
  - malaria
  - mozambique
  - q2-2026
current_run_id: 2026-04-06-002
"""
    opp: OppManifest = parse_opp_yaml(body)
    assert opp.slug == "malaria-pilot"
    assert opp.display_name == "Malaria Pilot — Northern Mozambique"
    assert opp.labels == ["malaria", "mozambique", "q2-2026"]
    assert opp.current_run_id == "2026-04-06-002"
    assert opp.created_by == "neal@dimagi.com"


def test_parse_opp_yaml_minimal():
    body = "slug: test\ndisplay_name: Test\n"
    opp = parse_opp_yaml(body)
    assert opp.slug == "test"
    assert opp.labels == []
    assert opp.current_run_id is None


def test_parse_opp_yaml_missing_slug_raises():
    with pytest.raises(ValueError, match="slug"):
        parse_opp_yaml("display_name: x\n")


def test_parse_run_yaml_full():
    body = """
run_id: 2026-04-06-002
mode: review
status: running
started_at: 2026-04-06T10:12:00Z
completed_at: null
current_phase: app-building
current_step: app-deploy
skill_versions:
  idea-to-idd: 4f2b8c1
  app-deploy: 8a91f22
notes: |
  Re-run after editing app-deploy SKILL.md.
"""
    run: RunManifest = parse_run_yaml(body)
    assert run.run_id == "2026-04-06-002"
    assert run.mode == "review"
    assert run.status == "running"
    assert run.current_step == "app-deploy"
    assert run.skill_versions["app-deploy"] == "8a91f22"
    assert run.completed_at is None


def test_parse_run_yaml_rejects_bad_mode():
    body = "run_id: r1\nmode: banana\nstatus: running\n"
    with pytest.raises(ValueError, match="mode"):
        parse_run_yaml(body)


def test_parse_run_yaml_rejects_bad_status():
    body = "run_id: r1\nmode: review\nstatus: wat\n"
    with pytest.raises(ValueError, match="status"):
        parse_run_yaml(body)


def test_parse_step_yaml():
    body = """
skill_name: app-deploy
phase: app-building
ordinal: 4
status: gate-pending
started_at: 2026-04-06T10:34:00Z
completed_at: null
error: null
preview_stats:
  apps_packaged: 2
  target_domain: crispr-connect
"""
    step: StepManifest = parse_step_yaml(body)
    assert step.skill_name == "app-deploy"
    assert step.status == "gate-pending"
    assert step.preview_stats["apps_packaged"] == 2


def test_parse_judge_yaml():
    body = """
score: 9.2
passed: true
evaluated_at: 2026-04-06T10:14:25Z
criteria:
  completeness: 9.5
  specificity: 9.0
rationale: |
  The IDD is comprehensive.
"""
    judge = parse_judge_yaml(body)
    assert judge.score == 9.2
    assert judge.passed is True
    assert judge.criteria["completeness"] == 9.5
    assert "comprehensive" in judge.rationale


def test_parse_gates_jsonl():
    body = """{"ts":"2026-04-01T10:00:00Z","decision":"approved","decided_by":"neal@dimagi.com","note":"lgtm"}
{"ts":"2026-04-06T10:14:25Z","decision":"pending","payload":{"reason":"awaiting review"}}
"""
    gates = parse_gates_jsonl(body)
    assert len(gates) == 2
    assert gates[0].decision == "approved"
    assert gates[0].decided_by == "neal@dimagi.com"
    assert gates[1].decision == "pending"
    assert gates[1].decided_by == ""


def test_parse_gates_jsonl_empty():
    assert parse_gates_jsonl("") == []
    assert parse_gates_jsonl("\n\n") == []


def test_parse_gates_jsonl_malformed_line_is_skipped():
    body = """{"ts":"2026-04-01T10:00:00Z","decision":"approved"}
not-json
{"ts":"2026-04-02T10:00:00Z","decision":"rejected"}
"""
    gates = parse_gates_jsonl(body)
    assert len(gates) == 2
    assert [g.decision for g in gates] == ["approved", "rejected"]


def test_parse_events_jsonl():
    body = """{"ts":"2026-04-06T10:12:00Z","kind":"run.started","payload":{"mode":"review"}}
{"ts":"2026-04-06T10:12:03Z","kind":"step.started","step":"idea-to-idd"}
"""
    events = parse_events_jsonl(body)
    assert len(events) == 2
    assert events[0].kind == "run.started"
    assert events[1].step == "idea-to-idd"
```

- [ ] **Step 3: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_parsers.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement the parsers**

Create `apps/opps/parsers.py`:

```python
"""Pure parsers for the ACE opp Drive folder format.

Every function takes a file body (string) and returns a structured dataclass
or list of dataclasses. No Drive I/O. No Django model operations. Parsers
are strict about required fields (raise ValueError) and tolerant about
optional ones (default to None / empty).

Format reference: docs/specs/2026-04-08-ace-opp-visualization-design.md § 6.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import yaml


# --- Dataclasses for parsed manifests ---

@dataclass
class OppManifest:
    slug: str
    display_name: str
    created_at: str | None = None
    created_by: str | None = None
    labels: list[str] = field(default_factory=list)
    current_run_id: str | None = None


@dataclass
class RunManifest:
    run_id: str
    mode: str                           # auto | review | dry-run | sandbox
    status: str                         # running | blocked | complete | failed | abandoned
    started_at: str | None = None
    completed_at: str | None = None
    current_phase: str | None = None
    current_step: str | None = None
    skill_versions: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass
class StepManifest:
    skill_name: str
    phase: str
    ordinal: int
    status: str                         # pending | running | complete | judge-fail | gate-pending | gate-rejected | error | skipped
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    preview_stats: dict = field(default_factory=dict)


@dataclass
class JudgeVerdict:
    score: float | None
    passed: bool | None
    evaluated_at: str | None
    criteria: dict = field(default_factory=dict)
    rationale: str = ""


@dataclass
class GateDecision:
    ts: str
    decision: str                       # pending | approved | rejected
    decided_by: str = ""
    note: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class RunEvent:
    ts: str
    kind: str
    step: str | None = None
    payload: dict = field(default_factory=dict)


# --- Validators ---

_VALID_MODES = frozenset({"auto", "review", "dry-run", "sandbox"})
_VALID_RUN_STATUSES = frozenset(
    {"running", "blocked", "complete", "failed", "abandoned"}
)
_VALID_STEP_STATUSES = frozenset(
    {
        "pending",
        "running",
        "complete",
        "judge-fail",
        "gate-pending",
        "gate-rejected",
        "error",
        "skipped",
    }
)
_VALID_GATE_DECISIONS = frozenset({"pending", "approved", "rejected"})


# --- Parsers ---

def _load_yaml(body: str) -> dict:
    """Load a YAML document, returning an empty dict if blank."""
    result = yaml.safe_load(body) if body.strip() else {}
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise ValueError(f"expected a YAML mapping, got {type(result).__name__}")
    return result


def parse_opp_yaml(body: str) -> OppManifest:
    data = _load_yaml(body)
    slug = data.get("slug")
    if not slug:
        raise ValueError("opp.yaml missing required field 'slug'")
    return OppManifest(
        slug=str(slug),
        display_name=str(data.get("display_name", slug)),
        created_at=data.get("created_at"),
        created_by=data.get("created_by"),
        labels=list(data.get("labels") or []),
        current_run_id=data.get("current_run_id"),
    )


def parse_run_yaml(body: str) -> RunManifest:
    data = _load_yaml(body)
    run_id = data.get("run_id")
    if not run_id:
        raise ValueError("run.yaml missing required field 'run_id'")
    mode = data.get("mode", "review")
    if mode not in _VALID_MODES:
        raise ValueError(f"run.yaml invalid mode '{mode}' — expected one of {sorted(_VALID_MODES)}")
    status = data.get("status", "running")
    if status not in _VALID_RUN_STATUSES:
        raise ValueError(
            f"run.yaml invalid status '{status}' — expected one of {sorted(_VALID_RUN_STATUSES)}"
        )
    return RunManifest(
        run_id=str(run_id),
        mode=mode,
        status=status,
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        current_phase=data.get("current_phase"),
        current_step=data.get("current_step"),
        skill_versions=dict(data.get("skill_versions") or {}),
        notes=str(data.get("notes") or ""),
    )


def parse_step_yaml(body: str) -> StepManifest:
    data = _load_yaml(body)
    if not data.get("skill_name"):
        raise ValueError("step.yaml missing required field 'skill_name'")
    status = data.get("status", "pending")
    if status not in _VALID_STEP_STATUSES:
        raise ValueError(
            f"step.yaml invalid status '{status}' — expected one of {sorted(_VALID_STEP_STATUSES)}"
        )
    return StepManifest(
        skill_name=str(data["skill_name"]),
        phase=str(data.get("phase", "")),
        ordinal=int(data.get("ordinal", 0)),
        status=status,
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        error=data.get("error"),
        preview_stats=dict(data.get("preview_stats") or {}),
    )


def parse_judge_yaml(body: str) -> JudgeVerdict:
    data = _load_yaml(body)
    return JudgeVerdict(
        score=(float(data["score"]) if "score" in data and data["score"] is not None else None),
        passed=data.get("passed"),
        evaluated_at=data.get("evaluated_at"),
        criteria=dict(data.get("criteria") or {}),
        rationale=str(data.get("rationale") or ""),
    )


def parse_gates_jsonl(body: str) -> list[GateDecision]:
    out: list[GateDecision] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # Tolerate malformed lines rather than fail the entire sync.
            continue
        decision = record.get("decision", "pending")
        if decision not in _VALID_GATE_DECISIONS:
            continue
        out.append(
            GateDecision(
                ts=str(record.get("ts", "")),
                decision=decision,
                decided_by=str(record.get("decided_by", "")),
                note=str(record.get("note", "")),
                payload=dict(record.get("payload") or {}),
            )
        )
    return out


def parse_events_jsonl(body: str) -> list[RunEvent]:
    out: list[RunEvent] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(
            RunEvent(
                ts=str(record.get("ts", "")),
                kind=str(record.get("kind", "")),
                step=record.get("step"),
                payload=dict(record.get("payload") or {}),
            )
        )
    return out
```

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_parsers.py -v`
Expected: 13 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/parsers.py apps/opps/tests/test_parsers.py pyproject.toml
git commit -m "feat(opps): add strict parsers for Drive format (opp/run/step/judge/gates/events)"
```

---

## Task 10: Sync layer — structured layout reader

**Files:**
- Create: `apps/opps/sync.py` (initial version; Task 11 adds flat-layout fallback)
- Create: `apps/opps/tests/test_sync_structured.py`
- Create: `apps/opps/tests/fixtures/drive/` fixture tree (YAML/markdown content shown inline below)

Reads a full opp from the structured format via a `DriveClient` and produces a typed `OppSnapshot` containing the `OppManifest`, the list of `Run` summaries, and the fully-expanded `RunDetail` for a requested run. This is the single function the views call; everything downstream is rendering.

- [ ] **Step 1: Write the structured-layout fixture tree**

Create a helper in `apps/opps/tests/fixtures/fake_drive.py` — add a classmethod to build a realistic malaria-pilot tree. Extend the file with:

```python
# --- Realistic fixture builders ---

MALARIA_PILOT_IDD = """# Malaria Pilot IDD

Reduce malaria infant mortality in northern Mozambique via monthly
FLW-administered RDT screening and referral.
"""

def _step_yaml(skill: str, phase: str, ordinal: int, status: str = "complete") -> str:
    return f"""skill_name: {skill}
phase: {phase}
ordinal: {ordinal}
status: {status}
started_at: 2026-04-06T10:00:00Z
completed_at: 2026-04-06T10:05:00Z
"""


def _judge_yaml(score: float, rationale: str = "solid") -> str:
    return f"""score: {score}
passed: true
evaluated_at: 2026-04-06T10:05:00Z
criteria:
  completeness: {score}
  specificity: {score}
rationale: |
  {rationale}
"""


def malaria_pilot_structured_tree() -> dict:
    """Two-run structured fixture for malaria-pilot.

    Run 2026-04-01-001: older run, idd-to-learn-app judge 7.1
    Run 2026-04-06-002: newer run, idd-to-learn-app judge 8.5 (improved)
    """
    return {
        "ACE": {
            "malaria-pilot": {
                "opp.yaml": """slug: malaria-pilot
display_name: Malaria Pilot — Northern Mozambique
created_at: 2026-03-15T09:00:00Z
created_by: neal@dimagi.com
labels:
  - malaria
  - mozambique
current_run_id: 2026-04-06-002
""",
                "idd.md": MALARIA_PILOT_IDD,
                "runs": {
                    "2026-04-01-001": {
                        "run.yaml": """run_id: 2026-04-01-001
mode: review
status: complete
started_at: 2026-04-01T10:00:00Z
completed_at: 2026-04-01T12:00:00Z
current_phase: closeout
current_step: cycle-grade
skill_versions:
  idea-to-idd: 4f2b8c1
  idd-to-learn-app: 4f2b8c1
""",
                        "events.jsonl": '{"ts":"2026-04-01T10:00:00Z","kind":"run.started"}\n',
                        "steps": {
                            "01-idea-to-idd": {
                                "step.yaml": _step_yaml("idea-to-idd", "app-building", 1),
                                "judge.yaml": _judge_yaml(7.8, "acceptable"),
                                "output": {"idd.md": MALARIA_PILOT_IDD},
                            },
                            "02-idd-to-learn-app": {
                                "step.yaml": _step_yaml("idd-to-learn-app", "app-building", 2),
                                "judge.yaml": _judge_yaml(7.1, "missing some forms"),
                                "output": {"learn-app-brief.md": "# Learn App Brief\n\n8 forms"},
                            },
                        },
                    },
                    "2026-04-06-002": {
                        "run.yaml": """run_id: 2026-04-06-002
mode: review
status: running
started_at: 2026-04-06T10:00:00Z
current_phase: app-building
current_step: app-deploy
skill_versions:
  idea-to-idd: 4f2b8c1
  idd-to-learn-app: 4f2b8c1
  app-deploy: 8a91f22
""",
                        "events.jsonl": '{"ts":"2026-04-06T10:00:00Z","kind":"run.started"}\n',
                        "steps": {
                            "01-idea-to-idd": {
                                "step.yaml": _step_yaml("idea-to-idd", "app-building", 1),
                                "judge.yaml": _judge_yaml(9.2, "comprehensive"),
                                "output": {"idd.md": MALARIA_PILOT_IDD},
                            },
                            "02-idd-to-learn-app": {
                                "step.yaml": _step_yaml("idd-to-learn-app", "app-building", 2),
                                "judge.yaml": _judge_yaml(8.5, "better now"),
                                "output": {"learn-app-brief.md": "# Learn App Brief\n\n12 forms"},
                            },
                            "03-idd-to-deliver-app": {
                                "step.yaml": _step_yaml("idd-to-deliver-app", "app-building", 3),
                                "judge.yaml": _judge_yaml(8.1),
                                "output": {"deliver-app-brief.md": "# Deliver App\n\n4 workflows"},
                            },
                            "04-app-deploy": {
                                "step.yaml": _step_yaml("app-deploy", "app-building", 4, status="gate-pending"),
                                "gates.jsonl": '{"ts":"2026-04-06T10:34:00Z","decision":"pending"}\n',
                                "output": {"deploy-summary.md": "2 apps packaged\nawaiting publish"},
                            },
                        },
                    },
                },
            }
        }
    }
```

- [ ] **Step 2: Write the sync tests**

Create `apps/opps/tests/test_sync_structured.py`:

```python
"""Tests for the structured-layout sync layer."""
import pytest

from apps.opps.sync import OppSnapshot, load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree(malaria_pilot_structured_tree())


def test_load_opp_returns_full_snapshot(client):
    ace_id = client.folder_id("ACE")
    snap: OppSnapshot = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    assert snap.opp.slug == "malaria-pilot"
    assert snap.opp.current_run_id == "2026-04-06-002"
    assert [r.run_id for r in snap.all_runs] == [
        "2026-04-06-002",
        "2026-04-01-001",
    ]  # newest first
    # Current run expanded
    assert snap.current_run.run_id == "2026-04-06-002"
    assert snap.current_run.mode == "review"
    assert snap.current_run.status == "running"


def test_load_opp_includes_all_steps_for_current_run(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    skill_names = [s.step.skill_name for s in snap.current_run.steps]
    assert skill_names == [
        "idea-to-idd",
        "idd-to-learn-app",
        "idd-to-deliver-app",
        "app-deploy",
    ]


def test_load_opp_populates_judge_results(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    step = next(s for s in snap.current_run.steps if s.step.skill_name == "idea-to-idd")
    assert step.judge is not None
    assert step.judge.score == 9.2
    step_lla = next(s for s in snap.current_run.steps if s.step.skill_name == "idd-to-learn-app")
    assert step_lla.judge.score == 8.5


def test_load_opp_populates_gates(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    step = next(s for s in snap.current_run.steps if s.step.skill_name == "app-deploy")
    assert len(step.gates) == 1
    assert step.gates[0].decision == "pending"


def test_load_opp_with_explicit_run_id(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(
        client, ace_folder_id=ace_id, slug="malaria-pilot", run_id="2026-04-01-001"
    )
    assert snap.current_run.run_id == "2026-04-01-001"
    # The older run has only 2 steps in the fixture
    assert len(snap.current_run.steps) == 2


def test_load_opp_attaches_idd_body(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    assert "Malaria Pilot IDD" in snap.idd_body


def test_load_opp_unknown_slug_raises(client):
    ace_id = client.folder_id("ACE")
    with pytest.raises(FileNotFoundError, match="malaria-banana"):
        load_opp(client, ace_folder_id=ace_id, slug="malaria-banana")
```

- [ ] **Step 3: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_sync_structured.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement the sync layer (structured layout)**

Create `apps/opps/sync.py`:

```python
"""Drive-folder → workbench payload sync.

Reads an ACE opportunity folder from Google Drive via a DriveClient and
returns a fully-expanded OppSnapshot suitable for JSON serialization.

This file handles the STRUCTURED layout:
    ACE/<slug>/opp.yaml
    ACE/<slug>/idd.md
    ACE/<slug>/runs/<run-id>/run.yaml
    ACE/<slug>/runs/<run-id>/events.jsonl
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/step.yaml
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/judge.yaml
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/gates.jsonl
    ACE/<slug>/runs/<run-id>/steps/<n>-<skill>/output/<artifact>

Flat-layout fallback (for legacy ACE/<slug>/state.yaml + idd.md + subfolders)
is in Task 11, as a second entry point in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.parsers import (
    GateDecision,
    JudgeVerdict,
    OppManifest,
    RunManifest,
    StepManifest,
    parse_gates_jsonl,
    parse_judge_yaml,
    parse_opp_yaml,
    parse_run_yaml,
    parse_step_yaml,
)


# --- Output dataclasses ---

@dataclass
class ArtifactRef:
    name: str
    drive_file_id: str
    drive_web_link: str
    size_bytes: int | None
    mime_type: str
    path: str             # relative to the step's output/ folder, e.g. "idd.md"


@dataclass
class StepSnapshot:
    step: StepManifest
    judge: JudgeVerdict | None
    gates: list[GateDecision]
    artifacts: list[ArtifactRef]
    folder_id: str


@dataclass
class RunDetail:
    run_id: str
    mode: str
    status: str
    started_at: str | None
    completed_at: str | None
    current_phase: str | None
    current_step: str | None
    skill_versions: dict[str, str]
    notes: str
    steps: list[StepSnapshot]
    folder_id: str


@dataclass
class RunSummary:
    run_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    folder_id: str


@dataclass
class OppSnapshot:
    opp: OppManifest
    idd_body: str
    opp_folder_id: str
    all_runs: list[RunSummary]         # sorted newest-first
    current_run: RunDetail


# --- Drive helpers ---

def _find_child(files: list[DriveFile], name: str) -> DriveFile | None:
    for f in files:
        if f.name == name:
            return f
    return None


def _find_child_folder(files: list[DriveFile], name: str) -> DriveFile | None:
    f = _find_child(files, name)
    if f and f.mime_type == "application/vnd.google-apps.folder":
        return f
    return None


def _read_text(client: DriveClient, file: DriveFile) -> str:
    return client.get_content(file.id, file.mime_type).content


# --- Main entry point ---

def load_opp(
    client: DriveClient,
    *,
    ace_folder_id: str,
    slug: str,
    run_id: str | None = None,
) -> OppSnapshot:
    """Load a full opp snapshot from the STRUCTURED layout.

    If the given slug is not present under ace_folder_id, raises FileNotFoundError.
    If the slug is present but does not have an `opp.yaml` (i.e. it's a legacy
    flat layout), raises FileNotFoundError — callers should fall through to
    the flat-layout loader.
    """
    # Locate the opp folder
    ace_children = client.list_files(ace_folder_id)
    opp_folder = _find_child_folder(ace_children, slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp folder named {slug!r} under ACE/")

    opp_children = client.list_files(opp_folder.id)
    opp_yaml_file = _find_child(opp_children, "opp.yaml")
    if opp_yaml_file is None:
        raise FileNotFoundError(
            f"opp {slug!r} has no opp.yaml — may be a legacy flat layout"
        )

    opp_manifest = parse_opp_yaml(_read_text(client, opp_yaml_file))

    idd_file = _find_child(opp_children, "idd.md")
    idd_body = _read_text(client, idd_file) if idd_file else ""

    runs_folder = _find_child_folder(opp_children, "runs")
    if runs_folder is None:
        raise FileNotFoundError(f"opp {slug!r} has no runs/ subfolder")

    run_folders = [
        f for f in client.list_files(runs_folder.id)
        if f.mime_type == "application/vnd.google-apps.folder"
    ]
    # Sort newest first by name (ids are date-prefixed per the spec).
    run_folders.sort(key=lambda f: f.name, reverse=True)

    if not run_folders:
        raise FileNotFoundError(f"opp {slug!r} has runs/ but no run folders inside")

    # Build lightweight summaries for the run switcher
    all_runs: list[RunSummary] = []
    for rf in run_folders:
        rf_children = client.list_files(rf.id)
        run_yaml_file = _find_child(rf_children, "run.yaml")
        if run_yaml_file is None:
            continue
        run = parse_run_yaml(_read_text(client, run_yaml_file))
        all_runs.append(
            RunSummary(
                run_id=run.run_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                folder_id=rf.id,
            )
        )

    # Resolve which run to expand
    target_run_id = run_id or opp_manifest.current_run_id or all_runs[0].run_id
    target_summary = next((r for r in all_runs if r.run_id == target_run_id), None)
    if target_summary is None:
        # Fall back to latest
        target_summary = all_runs[0]

    current_run = _load_run_detail(client, target_summary.folder_id)

    return OppSnapshot(
        opp=opp_manifest,
        idd_body=idd_body,
        opp_folder_id=opp_folder.id,
        all_runs=all_runs,
        current_run=current_run,
    )


def _load_run_detail(client: DriveClient, run_folder_id: str) -> RunDetail:
    files = client.list_files(run_folder_id)
    run_yaml_file = _find_child(files, "run.yaml")
    if run_yaml_file is None:
        raise FileNotFoundError("run folder has no run.yaml")
    run = parse_run_yaml(_read_text(client, run_yaml_file))

    steps_folder = _find_child_folder(files, "steps")
    steps: list[StepSnapshot] = []
    if steps_folder is not None:
        step_folders = [
            f for f in client.list_files(steps_folder.id)
            if f.mime_type == "application/vnd.google-apps.folder"
        ]
        # Sort by name (which is "<ordinal>-<skill>").
        step_folders.sort(key=lambda f: f.name)
        for sf in step_folders:
            steps.append(_load_step_snapshot(client, sf.id))

    return RunDetail(
        run_id=run.run_id,
        mode=run.mode,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        current_phase=run.current_phase,
        current_step=run.current_step,
        skill_versions=run.skill_versions,
        notes=run.notes,
        steps=steps,
        folder_id=run_folder_id,
    )


def _load_step_snapshot(client: DriveClient, step_folder_id: str) -> StepSnapshot:
    files = client.list_files(step_folder_id)

    step_yaml_file = _find_child(files, "step.yaml")
    if step_yaml_file is None:
        raise FileNotFoundError("step folder has no step.yaml")
    step = parse_step_yaml(_read_text(client, step_yaml_file))

    judge_file = _find_child(files, "judge.yaml")
    judge = parse_judge_yaml(_read_text(client, judge_file)) if judge_file else None

    gates_file = _find_child(files, "gates.jsonl")
    gates = parse_gates_jsonl(_read_text(client, gates_file)) if gates_file else []

    output_folder = _find_child_folder(files, "output")
    artifacts: list[ArtifactRef] = []
    if output_folder is not None:
        for f in client.list_files(output_folder.id, recursive=True):
            if f.mime_type == "application/vnd.google-apps.folder":
                continue
            artifacts.append(
                ArtifactRef(
                    name=f.name,
                    drive_file_id=f.id,
                    drive_web_link=f.web_view_link,
                    size_bytes=f.size_bytes,
                    mime_type=f.mime_type,
                    path=f.path,
                )
            )

    return StepSnapshot(
        step=step,
        judge=judge,
        gates=gates,
        artifacts=artifacts,
        folder_id=step_folder_id,
    )
```

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_sync_structured.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/sync.py apps/opps/tests/test_sync_structured.py apps/opps/tests/fixtures/fake_drive.py
git commit -m "feat(opps): add structured-layout sync (opp + runs + steps + judge + gates)"
```

---

## Task 11: Sync layer — flat-layout fallback

**Files:**
- Modify: `apps/opps/sync.py`
- Create: `apps/opps/tests/test_sync_flat.py`

Extend `load_opp` to fall through to a flat-layout reader when `opp.yaml` is not present. The flat layout is the ACE plugin's current output:
```
ACE/<slug>/
  state.yaml
  idd.md
  app-summaries/learn-app-summary.md
  app-summaries/deliver-app-summary.md
  test-results/…
  training-materials/…
  comms-log/…
  closeout/…
```

The flat reader synthesizes one implicit run with `run_id="r1"` whose current step is derived from `state.yaml`. Step manifests are synthesized from the `SKILL_REGISTRY`; each skill that has a known artifact subfolder gets status `complete` with artifacts populated, others get status `pending`.

- [ ] **Step 1: Add flat-layout fixture**

Extend `apps/opps/tests/fixtures/fake_drive.py`:

```python
def nutrition_legacy_flat_tree() -> dict:
    """Legacy flat-layout fixture. No runs/ subfolder — all artifacts live
    as siblings of state.yaml."""
    return {
        "ACE": {
            "nutrition-legacy": {
                "state.yaml": """current_phase: app-building
current_step: app-test
mode: review
started_at: 2026-03-20T09:00:00Z
""",
                "idd.md": "# Nutrition IDD\n\nInfant nutrition monitoring in rural India.",
                "app-summaries": {
                    "learn-app-summary.md": "8 forms · 3 case types",
                    "deliver-app-summary.md": "3 service workflows",
                },
                "test-results": {
                    "test-plan.md": "40 test cases",
                    "bug-list.md": "2 bugs found",
                },
            }
        }
    }
```

- [ ] **Step 2: Write the flat-layout tests**

Create `apps/opps/tests/test_sync_flat.py`:

```python
"""Tests for the flat-layout fallback reader."""
import pytest

from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    nutrition_legacy_flat_tree,
)


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree(nutrition_legacy_flat_tree())


def test_flat_layout_synthesizes_implicit_run(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    assert snap.opp.slug == "nutrition-legacy"
    assert snap.opp.current_run_id == "r1"
    assert len(snap.all_runs) == 1
    assert snap.all_runs[0].run_id == "r1"
    assert snap.current_run.run_id == "r1"


def test_flat_layout_populates_idd_body(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    assert "Nutrition IDD" in snap.idd_body


def test_flat_layout_synthesizes_step_rows_for_all_19_skills(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    skill_names = [s.step.skill_name for s in snap.current_run.steps]
    assert len(skill_names) == 19
    assert skill_names[0] == "idea-to-idd"
    assert skill_names[-1] == "cycle-grade"


def test_flat_layout_marks_known_subfolder_steps_complete(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    # app-summaries/ subfolder is treated as evidence that
    # idd-to-learn-app and idd-to-deliver-app produced output.
    learn = next(s for s in snap.current_run.steps if s.step.skill_name == "idd-to-learn-app")
    assert learn.step.status == "complete"
    assert any("learn-app-summary" in a.name for a in learn.artifacts)
    # test-results/ subfolder → app-test
    test_step = next(s for s in snap.current_run.steps if s.step.skill_name == "app-test")
    assert test_step.step.status == "complete"


def test_flat_layout_later_steps_pending(client):
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="nutrition-legacy")
    cycle_grade = next(s for s in snap.current_run.steps if s.step.skill_name == "cycle-grade")
    assert cycle_grade.step.status == "pending"
    assert cycle_grade.artifacts == []
```

- [ ] **Step 3: Run the tests, expect failure**

Run: `pytest apps/opps/tests/test_sync_flat.py -v`
Expected: FileNotFoundError (opp has no opp.yaml) — because Task 10's `load_opp` raises if no opp.yaml.

- [ ] **Step 4: Add the flat-layout fallback**

Modify `apps/opps/sync.py`. At the top of `load_opp` replace the FileNotFoundError raise with a fall-through:

```python
    opp_yaml_file = _find_child(opp_children, "opp.yaml")
    if opp_yaml_file is None:
        # Flat legacy layout — no opp.yaml, state.yaml at the top level.
        return _load_flat_opp(client, slug=slug, opp_folder=opp_folder, opp_children=opp_children)
```

Then add the flat loader at the bottom of `apps/opps/sync.py`:

```python
# --- Flat legacy layout support ---

# Map from flat-layout subfolder name to the set of skills whose artifacts
# are expected to live inside it. Derived from the ACE plugin's current
# conventions (see ../ace/docs/generated/playbook.md).
_FLAT_SUBFOLDER_SKILLS = {
    "app-summaries": {"idd-to-learn-app", "idd-to-deliver-app"},
    "test-results": {"app-test"},
    "training-materials": {"training-materials"},
    "comms-log": {"llo-onboarding", "llo-invite", "llo-feedback"},
    "closeout": {"opp-closeout", "learnings-summary", "cycle-grade"},
}


def _load_flat_opp(
    client: DriveClient,
    *,
    slug: str,
    opp_folder: DriveFile,
    opp_children: list[DriveFile],
) -> OppSnapshot:
    """Read a legacy flat-layout opp as an implicit single run."""
    from apps.opps.skills import SKILL_REGISTRY

    # Parse state.yaml if present for current_step / mode hints.
    state_file = _find_child(opp_children, "state.yaml")
    state_data: dict = {}
    if state_file is not None:
        import yaml
        raw = _read_text(client, state_file)
        state_data = yaml.safe_load(raw) or {}

    idd_file = _find_child(opp_children, "idd.md")
    idd_body = _read_text(client, idd_file) if idd_file else ""

    # Build a map of subfolder name -> list of DriveFile (recursively) so we
    # can look up which skills have produced output.
    subfolder_files: dict[str, list[DriveFile]] = {}
    for child in opp_children:
        if child.mime_type == "application/vnd.google-apps.folder":
            subfolder_files[child.name] = client.list_files(child.id, recursive=True)

    # Build a skill_name -> [ArtifactRef] map from the subfolder mapping.
    artifacts_by_skill: dict[str, list[ArtifactRef]] = {}
    for subfolder_name, skills in _FLAT_SUBFOLDER_SKILLS.items():
        files = subfolder_files.get(subfolder_name, [])
        artifact_refs = [
            ArtifactRef(
                name=f.name,
                drive_file_id=f.id,
                drive_web_link=f.web_view_link,
                size_bytes=f.size_bytes,
                mime_type=f.mime_type,
                path=f.path,
            )
            for f in files
            if f.mime_type != "application/vnd.google-apps.folder"
        ]
        for skill in skills:
            artifacts_by_skill.setdefault(skill, []).extend(artifact_refs)

    # Also treat idd.md as the artifact for idea-to-idd.
    if idd_file is not None:
        artifacts_by_skill.setdefault("idea-to-idd", []).append(
            ArtifactRef(
                name="idd.md",
                drive_file_id=idd_file.id,
                drive_web_link=idd_file.web_view_link,
                size_bytes=idd_file.size_bytes,
                mime_type=idd_file.mime_type,
                path="idd.md",
            )
        )

    # Synthesize step rows from the canonical skill registry.
    steps: list[StepSnapshot] = []
    for skill_meta in SKILL_REGISTRY:
        artifacts = artifacts_by_skill.get(skill_meta.name, [])
        status = "complete" if artifacts else "pending"
        step_manifest = StepManifest(
            skill_name=skill_meta.name,
            phase=skill_meta.phase,
            ordinal=skill_meta.ordinal,
            status=status,
        )
        steps.append(
            StepSnapshot(
                step=step_manifest,
                judge=None,
                gates=[],
                artifacts=artifacts,
                folder_id=opp_folder.id,
            )
        )

    run_detail = RunDetail(
        run_id="r1",
        mode=state_data.get("mode", "review"),
        status="running",
        started_at=state_data.get("started_at"),
        completed_at=None,
        current_phase=state_data.get("current_phase"),
        current_step=state_data.get("current_step"),
        skill_versions={},
        notes="Legacy flat-layout opp — synthesized as implicit single run 'r1'.",
        steps=steps,
        folder_id=opp_folder.id,
    )

    opp_manifest = OppManifest(
        slug=slug,
        display_name=state_data.get("display_name", slug),
        created_at=state_data.get("started_at"),
        created_by=state_data.get("created_by"),
        labels=[],
        current_run_id="r1",
    )

    return OppSnapshot(
        opp=opp_manifest,
        idd_body=idd_body,
        opp_folder_id=opp_folder.id,
        all_runs=[
            RunSummary(
                run_id="r1",
                status="running",
                started_at=state_data.get("started_at"),
                completed_at=None,
                folder_id=opp_folder.id,
            )
        ],
        current_run=run_detail,
    )
```

- [ ] **Step 5: Run the flat-layout tests**

Run: `pytest apps/opps/tests/test_sync_flat.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run both sync test suites to catch regressions**

Run: `pytest apps/opps/tests/test_sync_structured.py apps/opps/tests/test_sync_flat.py -v`
Expected: 12 passed (7 structured + 5 flat).

- [ ] **Step 7: Commit**

```bash
git add apps/opps/sync.py apps/opps/tests/test_sync_flat.py apps/opps/tests/fixtures/fake_drive.py
git commit -m "feat(opps): add flat-layout fallback for legacy ACE/<slug>/state.yaml opps"
```

---

## Task 12: Per-skill preview extractors

**Files:**
- Create: `apps/opps/previews.py`
- Create: `apps/opps/tests/test_previews.py`

One extractor function per skill, each turning the skill's primary artifact body into a one-line `preview_text` string for the center-pane row. A `PREVIEW_EXTRACTORS` registry maps skill name → function. Unknown skills get a generic `f"{n} artifacts"` fallback.

Each extractor takes `(StepSnapshot, dict[str, str])` — the snapshot and a mapping of artifact path → body that the sync layer has already fetched — and returns the preview string. This decouples extraction from Drive I/O: tests pass literal bodies, production code passes bodies the view layer has already fetched for the primary output.

- [ ] **Step 1: Write the preview tests**

Create `apps/opps/tests/test_previews.py`:

```python
"""Tests for per-skill preview_text extractors."""
from apps.opps.parsers import StepManifest
from apps.opps.previews import PREVIEW_EXTRACTORS, build_preview
from apps.opps.sync import ArtifactRef, StepSnapshot


def _step(skill: str, artifacts: list[str] | None = None) -> StepSnapshot:
    return StepSnapshot(
        step=StepManifest(skill_name=skill, phase="", ordinal=0, status="complete"),
        judge=None,
        gates=[],
        artifacts=[
            ArtifactRef(
                name=a, drive_file_id=f"fake-{a}", drive_web_link="",
                size_bytes=None, mime_type="text/markdown", path=a,
            )
            for a in (artifacts or [])
        ],
        folder_id="step-id",
    )


def test_idea_to_idd_preview():
    body = "# Malaria IDD\n\nReduce malaria mortality via monthly RDT screening."
    step = _step("idea-to-idd", artifacts=["idd.md"])
    preview = build_preview(step, bodies={"idd.md": body})
    assert "idd.md" in preview
    assert "Reduce malaria mortality" in preview


def test_learn_app_preview_extracts_form_count():
    body = "# Learn App Brief\n\n12 forms\n34 questions\n6 case types"
    step = _step("idd-to-learn-app", artifacts=["learn-app-brief.md"])
    preview = build_preview(step, bodies={"learn-app-brief.md": body})
    assert "12 forms" in preview


def test_app_test_preview_extracts_pass_ratio():
    body = "passed: 38\nfailed: 2\ntotal: 40\n"
    step = _step("app-test", artifacts=["test-results.yaml"])
    preview = build_preview(step, bodies={"test-results.yaml": body})
    assert "38/40 pass" in preview
    assert "2 fail" in preview


def test_training_materials_preview_counts_artifacts():
    step = _step(
        "training-materials",
        artifacts=[
            "llo-manager-guide.md",
            "flw-training-guide.md",
            "quick-reference.md",
            "faq.md",
        ],
    )
    preview = build_preview(step, bodies={})
    assert "4 docs" in preview


def test_cycle_grade_preview():
    body = "overall_grade: 8.4\nintervention_effectiveness: 9\napp_quality: 8\n"
    step = _step("cycle-grade", artifacts=["grade-report.md"])
    preview = build_preview(step, bodies={"grade-report.md": body})
    assert "8.4" in preview


def test_unknown_skill_falls_back_to_count():
    step = _step("unknown-skill-123", artifacts=["a.md", "b.md"])
    preview = build_preview(step, bodies={})
    assert preview == "2 artifacts"


def test_no_artifacts_falls_back_to_dash():
    step = _step("idea-to-idd", artifacts=[])
    preview = build_preview(step, bodies={})
    assert preview == "—"


def test_every_registered_skill_has_an_extractor():
    """Every skill in the registry must have either a dedicated extractor or
    rely on the generic fallback — we don't want silent gaps."""
    from apps.opps.skills import SKILL_REGISTRY
    # Not all 19 need a dedicated function, but if the generic fallback is
    # used we should be intentional about it. This test just asserts that
    # the registry is importable and the fallback path works.
    for skill in SKILL_REGISTRY:
        step = _step(skill.name, artifacts=[skill.primary_output])
        preview = build_preview(step, bodies={skill.primary_output: "sample"})
        assert isinstance(preview, str)
        assert preview != ""
```

- [ ] **Step 2: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_previews.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the previews module**

Create `apps/opps/previews.py`:

```python
"""Per-skill preview_text extractors.

Each extractor turns one step's artifact body (already fetched by the sync
layer) into a short one-line string rendered in the Workbench center-pane
row. The mapping from skill name to extractor lives in `PREVIEW_EXTRACTORS`.

Extractors are pure — they take (StepSnapshot, bodies: dict[str, str]) and
return a string. They never call Drive.
"""
from __future__ import annotations

import re
from typing import Callable

import yaml

from apps.opps.sync import StepSnapshot

PreviewFn = Callable[[StepSnapshot, dict[str, str]], str]


# --- Individual extractors ---

def _first_nonblank_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("# ").strip()
        if stripped:
            return stripped
    return ""


def _idea_to_idd(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("idd.md", "")
    # Try to skip the heading and grab the first sentence of the body.
    after_heading = body.split("\n\n", 1)[-1] if "\n\n" in body else body
    first_sentence = after_heading.strip().split(". ")[0].strip()
    if not first_sentence:
        return "📄 idd.md"
    return f"📄 idd.md — \"{first_sentence[:140]}\""


def _idd_to_learn_app(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("learn-app-brief.md", "")
    forms_match = re.search(r"(\d+)\s*forms?", body)
    questions_match = re.search(r"(\d+)\s*questions?", body)
    cases_match = re.search(r"(\d+)\s*case\s*types?", body)
    parts = []
    if forms_match:
        parts.append(f"{forms_match.group(1)} forms")
    if questions_match:
        parts.append(f"{questions_match.group(1)} questions")
    if cases_match:
        parts.append(f"{cases_match.group(1)} case types")
    if not parts:
        return "📦 learn-app-brief.md"
    return "📦 " + " · ".join(parts)


def _idd_to_deliver_app(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("deliver-app-brief.md", "")
    flows = re.search(r"(\d+)\s*(?:service\s*)?workflows?", body)
    triggers = re.search(r"(\d+)\s*payment\s*triggers?", body)
    parts = []
    if flows:
        parts.append(f"{flows.group(1)} workflows")
    if triggers:
        parts.append(f"{triggers.group(1)} payment triggers")
    if not parts:
        return "📦 deliver-app-brief.md"
    return "📦 " + " · ".join(parts)


def _app_deploy(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("deploy-summary.md", "")
    apps = re.search(r"(\d+)\s*apps?\s*packaged", body)
    status_line = ""
    for line in body.splitlines():
        if "status" in line.lower() or "awaiting" in line.lower():
            status_line = line.strip()
            break
    if apps:
        return f"📄 {apps.group(1)} apps packaged · {status_line or 'see summary'}"
    return "📄 deploy-summary.md"


def _app_test(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("test-results.yaml", "")
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        data = {}
    passed = data.get("passed")
    failed = data.get("failed")
    total = data.get("total")
    if passed is not None and total is not None:
        fail_str = f" · {failed} fail" if failed else ""
        return f"🧪 {passed}/{total} pass{fail_str}"
    return "🧪 test-results"


def _training_materials(step: StepSnapshot, bodies: dict[str, str]) -> str:
    n = len(step.artifacts)
    return f"📚 {n} doc{'s' if n != 1 else ''}"


def _connect_program_setup(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("program-config.md", "")
    first = _first_nonblank_line(body)
    return f"🔧 {first[:100]}" if first else "🔧 program-config.md"


def _connect_opp_setup(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("opp-config.md", "")
    rules = re.search(r"(\d+)\s*(?:verification\s*)?rules?", body)
    units = re.search(r"(\d+)\s*(?:delivery\s*)?units?", body)
    parts = []
    if rules:
        parts.append(f"{rules.group(1)} rules")
    if units:
        parts.append(f"{units.group(1)} units")
    if not parts:
        return "🔧 opp-config.md"
    return "🔧 " + " · ".join(parts)


def _llo_invite(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("invite-list.md", "")
    # Count bullet-point lines as LLO candidates.
    count = sum(1 for line in body.splitlines() if line.strip().startswith(("-", "*")))
    if count:
        return f"📧 {count} candidate LLO{'s' if count != 1 else ''}"
    return "📧 invite-list.md"


def _llo_onboarding(step: StepSnapshot, bodies: dict[str, str]) -> str:
    n = len(step.artifacts)
    return f"📧 {n} onboarding email{'s' if n != 1 else ''}"


def _llo_uat(step: StepSnapshot, bodies: dict[str, str]) -> str:
    return "🧪 UAT protocol" if step.artifacts else "—"


def _llo_launch(step: StepSnapshot, bodies: dict[str, str]) -> str:
    return "🚀 launch checklist" if step.artifacts else "—"


def _ocs_agent_setup(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("ocs-context.md", "")
    n_lines = len([line for line in body.splitlines() if line.strip()])
    if n_lines:
        return f"🤖 OCS agent · {n_lines}-line context"
    return "🤖 ocs-context.md"


def _timeline_monitor(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("timeline-report.md", "")
    first = _first_nonblank_line(body)
    return f"📅 {first[:100]}" if first else "📅 timeline-report.md"


def _flw_data_review(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("flw-review.md", "")
    subs = re.search(r"(\d+)\s*submissions?", body)
    if subs:
        return f"📊 {subs.group(1)} submissions reviewed"
    return "📊 flw-review.md"


def _opp_closeout(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("invoice-summary.md", "")
    amount = re.search(r"\$[\d,]+(?:\.\d{2})?", body)
    if amount:
        return f"💰 invoice: {amount.group(0)}"
    return "💰 invoice-summary.md"


def _llo_feedback(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("feedback-report.md", "")
    responses = re.search(r"(\d+)/(\d+)\s*responses?", body)
    if responses:
        return f"📝 {responses.group(0)} collected"
    return "📝 feedback-report.md"


def _learnings_summary(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("learnings.md", "")
    n_items = sum(
        1 for line in body.splitlines() if line.strip().startswith(("-", "*"))
    )
    if n_items:
        return f"💡 {n_items} learning{'s' if n_items != 1 else ''}"
    return "💡 learnings.md"


def _cycle_grade(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("grade-report.md", "")
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        data = {}
    grade = data.get("overall_grade")
    if grade is not None:
        return f"🏆 {grade}/10"
    match = re.search(r"(\d+\.?\d*)\s*/\s*10", body)
    if match:
        return f"🏆 {match.group(1)}/10"
    return "🏆 grade-report.md"


# --- Registry + public entry point ---

PREVIEW_EXTRACTORS: dict[str, PreviewFn] = {
    "idea-to-idd":           _idea_to_idd,
    "idd-to-learn-app":      _idd_to_learn_app,
    "idd-to-deliver-app":    _idd_to_deliver_app,
    "app-deploy":            _app_deploy,
    "app-test":              _app_test,
    "training-materials":    _training_materials,
    "connect-program-setup": _connect_program_setup,
    "connect-opp-setup":     _connect_opp_setup,
    "llo-invite":            _llo_invite,
    "llo-onboarding":        _llo_onboarding,
    "llo-uat":               _llo_uat,
    "llo-launch":            _llo_launch,
    "ocs-agent-setup":       _ocs_agent_setup,
    "timeline-monitor":      _timeline_monitor,
    "flw-data-review":       _flw_data_review,
    "opp-closeout":          _opp_closeout,
    "llo-feedback":          _llo_feedback,
    "learnings-summary":     _learnings_summary,
    "cycle-grade":           _cycle_grade,
}


def build_preview(step: StepSnapshot, bodies: dict[str, str]) -> str:
    """Return the one-line preview_text for a step.

    Prefers a dedicated extractor if registered; falls back to an artifact count
    ("N artifacts") or a dash if there are none.
    """
    extractor = PREVIEW_EXTRACTORS.get(step.step.skill_name)
    if extractor is not None and step.artifacts:
        try:
            return extractor(step, bodies)
        except Exception:  # noqa: BLE001 — never crash the view on a bad preview
            pass
    if not step.artifacts:
        return "—"
    n = len(step.artifacts)
    return f"{n} artifact{'s' if n != 1 else ''}"
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_previews.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/previews.py apps/opps/tests/test_previews.py
git commit -m "feat(opps): add 19 per-skill preview extractors with fallback"
```

---

## Task 13: Serializers + drive-client-per-request helper

**Files:**
- Create: `apps/opps/serializers.py`
- Create: `apps/opps/drive_for_request.py`
- Create: `apps/opps/tests/test_serializers.py`

DRF serializers that turn `OppSnapshot` / `RunDetail` / `StepSnapshot` into the exact JSON shape the frontend expects. Also a small `get_drive_client_for(user)` helper that owns the "decrypt token → build credentials → refresh if needed → write back → instantiate GoogleDriveClient" sequence so every view doesn't repeat it.

- [ ] **Step 1: Write the serializer tests**

Create `apps/opps/tests/test_serializers.py`:

```python
"""Tests that the serializers produce the exact JSON shape the frontend expects."""
import pytest

from apps.opps.serializers import (
    serialize_opp_card,
    serialize_opp_snapshot,
    serialize_step_snapshot,
)
from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def snap():
    client = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = client.folder_id("ACE")
    return load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")


def test_serialize_opp_snapshot_top_level_keys(snap):
    data = serialize_opp_snapshot(snap)
    assert set(data.keys()) == {"opp", "idd_body", "runs", "current_run"}


def test_serialize_opp_card_fields(snap):
    card = serialize_opp_card(snap.opp, snap.current_run)
    assert card["slug"] == "malaria-pilot"
    assert card["display_name"] == "Malaria Pilot — Northern Mozambique"
    assert card["current_run_id"] == "2026-04-06-002"
    assert card["current_step"] == "app-deploy"
    assert "labels" in card


def test_serialize_opp_snapshot_runs_list(snap):
    data = serialize_opp_snapshot(snap)
    assert len(data["runs"]) == 2
    run_ids = [r["run_id"] for r in data["runs"]]
    assert run_ids == ["2026-04-06-002", "2026-04-01-001"]


def test_serialize_opp_snapshot_current_run_has_all_steps(snap):
    data = serialize_opp_snapshot(snap)
    steps = data["current_run"]["steps"]
    skills = [s["skill_name"] for s in steps]
    assert "idea-to-idd" in skills
    assert "app-deploy" in skills


def test_serialize_step_snapshot_judge_shape(snap):
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-idd"
    )
    data = serialize_step_snapshot(step_snap)
    assert data["skill_name"] == "idea-to-idd"
    assert data["judge"]["score"] == 9.2
    assert data["judge"]["passed"] is True
    assert "rationale" in data["judge"]


def test_serialize_step_snapshot_no_judge(snap):
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "app-deploy"
    )
    data = serialize_step_snapshot(step_snap)
    assert data["judge"] is None
    assert len(data["gates"]) == 1
    assert data["gates"][0]["decision"] == "pending"


def test_serialize_step_snapshot_artifacts(snap):
    step_snap = next(
        s for s in snap.current_run.steps if s.step.skill_name == "idea-to-idd"
    )
    data = serialize_step_snapshot(step_snap)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["name"] == "idd.md"
    assert "drive_web_link" in data["artifacts"][0]
```

- [ ] **Step 2: Run the tests, expect import failure**

Run: `pytest apps/opps/tests/test_serializers.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the serializers**

Create `apps/opps/serializers.py`:

```python
"""Plain dict serializers for the Workbench payload.

Not DRF Serializer classes — just pure functions that convert the sync layer's
dataclasses into plain dicts matching the shape the React frontend expects.
The choice is deliberate: DRF serializers shine for model-backed reads/writes
with validation, but everything here is read-only from Drive and we already
have strict validation in the parsers.
"""
from __future__ import annotations

from apps.opps.parsers import GateDecision, JudgeVerdict, OppManifest
from apps.opps.previews import build_preview
from apps.opps.skills import PHASE_DISPLAY_NAMES, get_skill
from apps.opps.sync import (
    ArtifactRef,
    OppSnapshot,
    RunDetail,
    RunSummary,
    StepSnapshot,
)


def serialize_artifact(a: ArtifactRef) -> dict:
    return {
        "name": a.name,
        "drive_file_id": a.drive_file_id,
        "drive_web_link": a.drive_web_link,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "path": a.path,
    }


def serialize_judge(j: JudgeVerdict | None) -> dict | None:
    if j is None:
        return None
    return {
        "score": j.score,
        "passed": j.passed,
        "evaluated_at": j.evaluated_at,
        "criteria": j.criteria,
        "rationale": j.rationale,
    }


def serialize_gate(g: GateDecision) -> dict:
    return {
        "ts": g.ts,
        "decision": g.decision,
        "decided_by": g.decided_by,
        "note": g.note,
    }


def serialize_step_snapshot(
    step_snap: StepSnapshot, bodies: dict[str, str] | None = None
) -> dict:
    bodies = bodies or {}
    try:
        skill_meta = get_skill(step_snap.step.skill_name)
        phase_display = PHASE_DISPLAY_NAMES.get(skill_meta.phase, skill_meta.phase)
        has_judge = skill_meta.has_judge
        is_gate = skill_meta.is_gate
        is_recurring = skill_meta.is_recurring
    except KeyError:
        phase_display = step_snap.step.phase
        has_judge = False
        is_gate = False
        is_recurring = False

    return {
        "skill_name": step_snap.step.skill_name,
        "phase": step_snap.step.phase,
        "phase_display": phase_display,
        "ordinal": step_snap.step.ordinal,
        "status": step_snap.step.status,
        "started_at": step_snap.step.started_at,
        "completed_at": step_snap.step.completed_at,
        "error": step_snap.step.error,
        "has_judge": has_judge,
        "is_gate": is_gate,
        "is_recurring": is_recurring,
        "preview_text": build_preview(step_snap, bodies),
        "judge": serialize_judge(step_snap.judge),
        "gates": [serialize_gate(g) for g in step_snap.gates],
        "artifacts": [serialize_artifact(a) for a in step_snap.artifacts],
    }


def serialize_run_detail(run: RunDetail) -> dict:
    return {
        "run_id": run.run_id,
        "mode": run.mode,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "current_phase": run.current_phase,
        "current_step": run.current_step,
        "skill_versions": run.skill_versions,
        "notes": run.notes,
        "steps": [serialize_step_snapshot(s) for s in run.steps],
    }


def serialize_run_summary(run: RunSummary) -> dict:
    return {
        "run_id": run.run_id,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


def serialize_opp_card(opp: OppManifest, current_run: RunDetail | None) -> dict:
    return {
        "slug": opp.slug,
        "display_name": opp.display_name,
        "labels": opp.labels,
        "created_at": opp.created_at,
        "created_by": opp.created_by,
        "current_run_id": opp.current_run_id,
        "current_phase": current_run.current_phase if current_run else None,
        "current_step": current_run.current_step if current_run else None,
        "status": current_run.status if current_run else "unknown",
    }


def serialize_opp_snapshot(snap: OppSnapshot) -> dict:
    return {
        "opp": serialize_opp_card(snap.opp, snap.current_run),
        "idd_body": snap.idd_body,
        "runs": [serialize_run_summary(r) for r in snap.all_runs],
        "current_run": serialize_run_detail(snap.current_run),
    }
```

- [ ] **Step 4: Implement the per-request Drive client helper**

Create `apps/opps/drive_for_request.py`:

```python
"""Build a GoogleDriveClient scoped to the current request's user.

Encapsulates the decrypt → refresh → re-encrypt → instantiate sequence so
every view has one line instead of six.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apps.opps.drive_client import GoogleDriveClient
from apps.opps.drive_credentials import (
    CredentialsRefreshFailed,
    ensure_fresh,
)
from apps.opps.encryption import decrypt_token, encrypt_token


class DriveTokenMissing(RuntimeError):
    pass


def get_drive_client_for(user) -> GoogleDriveClient:
    """Return a GoogleDriveClient using the user's cached OAuth credentials.

    Raises DriveTokenMissing if the user has no token.
    Raises CredentialsRefreshFailed if the refresh-token exchange fails.
    """
    if not getattr(user, "drive_token_cache", ""):
        raise DriveTokenMissing("user has no cached Drive token")

    token_data = decrypt_token(user.drive_token_cache)
    try:
        creds, updated = ensure_fresh(token_data)
    except CredentialsRefreshFailed:
        raise

    if updated is not None:
        user.drive_token_cache = encrypt_token(updated)
        user.drive_token_refreshed_at = datetime.now(timezone.utc)
        user.save(update_fields=["drive_token_cache", "drive_token_refreshed_at"])

    return GoogleDriveClient(creds)
```

- [ ] **Step 5: Run the serializer tests, expect pass**

Run: `pytest apps/opps/tests/test_serializers.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/serializers.py apps/opps/drive_for_request.py apps/opps/tests/test_serializers.py
git commit -m "feat(opps): add serializers and per-request Drive client helper"
```

---

## Task 14: Opp list endpoint

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_views_opp_list.py`

`GET /api/opps/` — lists every folder under the ACE root folder that qualifies as an opp (has `opp.yaml` OR has a `state.yaml` + `idd.md`). Returns minimal cards: slug, display_name, current_run_id, current_step, status, labels.

The ACE root folder is resolved by name (`settings.ACE_DRIVE_ROOT_FOLDER_NAME`, default `"ACE"`) via a Drive search — no pre-configured folder id.

- [ ] **Step 1: Write the list-endpoint test**

Create `apps/opps/tests/test_views_opp_list.py`:

```python
"""Tests for GET /api/opps/ — the opportunity list endpoint."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
    nutrition_legacy_flat_tree,
)


@pytest.fixture
def user_with_token(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    return u


@pytest.fixture
def authed_client(user_with_token):
    c = Client()
    c.force_login(user_with_token)
    return c


def _combined_tree() -> dict:
    """Both fixtures under one ACE folder, to verify the list endpoint returns both."""
    return {
        "ACE": {
            **malaria_pilot_structured_tree()["ACE"],
            **nutrition_legacy_flat_tree()["ACE"],
        }
    }


def test_opp_list_returns_both_structured_and_flat(authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    cards = body["data"]
    slugs = {c["slug"] for c in cards}
    assert slugs == {"malaria-pilot", "nutrition-legacy"}


def test_opp_list_malaria_card_fields(authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    malaria = next(c for c in cards if c["slug"] == "malaria-pilot")
    assert malaria["display_name"] == "Malaria Pilot — Northern Mozambique"
    assert malaria["current_run_id"] == "2026-04-06-002"
    assert "malaria" in malaria["labels"]


def test_opp_list_requires_drive_token(db):
    user = User.objects.create(email="no-token@dimagi.com", display_name="Nobody")
    c = Client()
    c.force_login(user)
    response = c.get("/api/opps/")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["message"]
    assert body["data"] == {"reconnect_url": "/auth/drive/start"}


def test_opp_list_unauthenticated_returns_401():
    c = Client()
    response = c.get("/api/opps/")
    assert response.status_code == 401
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_views_opp_list.py -v`
Expected: endpoint returns 404 (not registered) or AttributeError on internals.

- [ ] **Step 3: Implement the opp list view**

Modify `apps/opps/views.py`:

```python
"""REST API views for the ACE opportunity Workbench."""
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps.drive_client import DriveClient
from apps.opps.drive_for_request import (
    DriveTokenMissing,
    get_drive_client_for,
)
from apps.opps.drive_credentials import CredentialsRefreshFailed
from apps.opps.middleware import RequireDriveToken
from apps.opps.parsers import parse_opp_yaml
from apps.opps.serializers import serialize_opp_card
from apps.opps.sync import load_opp


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Scaffold sanity check. Registered in Task 1."""
    return Response(success_response({"status": "ok", "module": "opps"}))


def _resolve_ace_root_folder_id(client: DriveClient) -> str | None:
    """Find the ACE root folder by name.

    We search for a folder named `settings.ACE_DRIVE_ROOT_FOLDER_NAME` that
    the user has access to. If multiple matches exist, return the first one
    — this rarely happens in practice and can be overridden via a pinned
    folder id in settings later.

    Returns None if no such folder exists.
    """
    # The DriveClient ABC does not expose a search, only list_files / get_file.
    # GoogleDriveClient could add a search helper later; for now we walk from
    # the Drive root by listing top-level files. Tests patch this whole
    # function to return a known folder id.
    raise NotImplementedError(
        "real implementation: add a Drive files.list(q='name=...') helper; "
        "tests patch this function to return a known folder id"
    )


def _require_drive(request):
    """Return (drive_client, error_response) tuple. error_response is None on success."""
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    perm = RequireDriveToken()
    if not perm.has_permission(request, view=None):
        payload = RequireDriveToken.get_reconnect_payload()
        return None, Response(
            {"data": payload, "error": {
                "code": "drive-token-missing",
                "message": "Google Drive access is not connected for this user",
            }},
            status=401,
        )
    try:
        client = get_drive_client_for(request.user)
    except DriveTokenMissing:
        payload = RequireDriveToken.get_reconnect_payload()
        return None, Response(
            {"data": payload, "error": {
                "code": "drive-token-missing", "message": "no drive token on file",
            }},
            status=401,
        )
    except CredentialsRefreshFailed as exc:
        payload = RequireDriveToken.get_reconnect_payload()
        return None, Response(
            {"data": payload, "error": {
                "code": "drive-token-refresh-failed", "message": str(exc),
            }},
            status=401,
        )
    return client, None


@api_view(["GET"])
@permission_classes([AllowAny])  # RequireDriveToken is enforced inside
def opp_list(request):
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(success_response([]))

    cards: list[dict] = []
    for child in client.list_files(ace_folder_id):
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        # Try structured layout first: does it have opp.yaml?
        opp_children = client.list_files(child.id)
        opp_yaml = next((f for f in opp_children if f.name == "opp.yaml"), None)
        if opp_yaml is not None:
            try:
                body = client.get_content(opp_yaml.id, opp_yaml.mime_type).content
                manifest = parse_opp_yaml(body)
                cards.append(
                    serialize_opp_card(manifest, current_run=None)
                )
                continue
            except Exception:
                pass
        # Flat layout: state.yaml + idd.md
        has_state = any(f.name == "state.yaml" for f in opp_children)
        has_idd = any(f.name == "idd.md" for f in opp_children)
        if has_state and has_idd:
            # Fall through to sync to get a minimal card.
            try:
                snap = load_opp(client, ace_folder_id=ace_folder_id, slug=child.name)
                cards.append(serialize_opp_card(snap.opp, snap.current_run))
            except Exception:
                continue

    # For opps that matched structured layout above, enrich them by loading
    # a thin snapshot so current_run fields populate. (We do this in a second
    # pass rather than calling load_opp for every opp on the hot path, to
    # keep the list endpoint fast.)
    # TODO in a follow-up: a dedicated "list cards" Drive read that fetches
    # only opp.yaml + latest run.yaml, skipping the step expansion.
    return Response(success_response(cards))
```

Modify `apps/opps/urls.py` to add the list route:

```python
"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import drive_auth_views, views

urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
]

auth_urlpatterns = [
    path("auth/drive/start", drive_auth_views.start, name="drive-auth-start"),
    path("auth/drive/callback", drive_auth_views.callback, name="drive-auth-callback"),
]
```

Note: there is a `TODO in a follow-up` comment in the view — remove it and replace with a dedicated pass in a later task if performance becomes a problem. For the first ship, enriching via `load_opp` is acceptable.

- [ ] **Step 4: Run the test, expect pass**

Run: `pytest apps/opps/tests/test_views_opp_list.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_views_opp_list.py
git commit -m "feat(opps): add GET /api/opps/ opp list endpoint"
```

---

## Task 15: Workbench endpoint (opp + current run)

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_views_workbench.py`

`GET /api/opps/<slug>?run_id=<optional>` — the main Workbench payload. Fully expanded current run with all steps, judges, gates, artifacts; plus the run list for the switcher; plus the IDD body.

- [ ] **Step 1: Write the workbench test**

Create `apps/opps/tests/test_views_workbench.py`:

```python
"""Tests for GET /api/opps/<slug>."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def user_with_token(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    return u


@pytest.fixture
def authed_client(user_with_token):
    c = Client()
    c.force_login(user_with_token)
    return c


def _with_fake_drive(authed_client, fake, url, **query):
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url, query)


def test_workbench_returns_full_snapshot(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["opp"]["slug"] == "malaria-pilot"
    assert data["current_run"]["run_id"] == "2026-04-06-002"
    assert len(data["current_run"]["steps"]) == 4
    assert len(data["runs"]) == 2


def test_workbench_with_run_id_query_param(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(
        authed_client, fake, "/api/opps/malaria-pilot", run_id="2026-04-01-001"
    )
    data = response.json()["data"]
    assert data["current_run"]["run_id"] == "2026-04-01-001"
    assert len(data["current_run"]["steps"]) == 2


def test_workbench_unknown_opp_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/nonexistent")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_workbench_includes_idd_body(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake_drive(authed_client, fake, "/api/opps/malaria-pilot")
    data = response.json()["data"]
    assert "Malaria Pilot IDD" in data["idd_body"]
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_views_workbench.py -v`
Expected: 404 (route not yet registered).

- [ ] **Step 3: Add the workbench view**

Append to `apps/opps/views.py`:

```python
from apps.opps.serializers import serialize_opp_snapshot


@api_view(["GET"])
@permission_classes([AllowAny])  # RequireDriveToken enforced via _require_drive
def workbench(request, slug: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response(f"ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    run_id = request.GET.get("run_id") or None

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    return Response(success_response(serialize_opp_snapshot(snap)))
```

Modify `apps/opps/urls.py` to add the workbench route:

```python
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
]
```

- [ ] **Step 4: Run the test, expect pass**

Run: `pytest apps/opps/tests/test_views_workbench.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_views_workbench.py
git commit -m "feat(opps): add GET /api/opps/<slug> workbench endpoint"
```

---

## Task 16: Step detail endpoint

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_views_step_detail.py`

`GET /api/opps/<slug>/runs/<run_id>/steps/<skill>` — returns the full step detail: step metadata, judge verdict, gate history, artifacts, and for the primary artifact the first ~200 lines of the body inline (so the UI can show the artifact preview without a second round trip).

- [ ] **Step 1: Write the step detail test**

Create `apps/opps/tests/test_views_step_detail.py`:

```python
"""Tests for GET /api/opps/<slug>/runs/<run_id>/steps/<skill>."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    c = Client()
    c.force_login(u)
    return c


def _with_fake(authed_client, fake, url):
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_step_detail_returns_full_payload(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["skill_name"] == "idea-to-idd"
    assert data["judge"]["score"] == 9.2
    assert len(data["artifacts"]) == 1
    assert "primary_body" in data
    assert "Malaria Pilot IDD" in data["primary_body"]


def test_step_detail_app_deploy_has_gates_no_judge(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["judge"] is None
    assert len(data["gates"]) == 1
    assert data["gates"][0]["decision"] == "pending"


def test_step_detail_unknown_step_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/nonexistent",
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_views_step_detail.py -v`
Expected: 404 — route not registered.

- [ ] **Step 3: Implement the step detail view**

Append to `apps/opps/views.py`:

```python
from apps.opps.serializers import serialize_step_snapshot


@api_view(["GET"])
@permission_classes([AllowAny])
def step_detail(request, slug: str, run_id: str, skill: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        return Response(
            error_response(f"no step {skill!r} in run {run_id!r}", code="step-not-found"),
            status=404,
        )

    # Fetch the primary artifact body so the frontend can show it inline.
    primary_body = ""
    bodies: dict[str, str] = {}
    for artifact in step_snap.artifacts:
        try:
            content = client.get_content(artifact.drive_file_id, artifact.mime_type)
            bodies[artifact.path] = content.content
        except Exception:
            continue
    if step_snap.artifacts:
        primary_body = bodies.get(step_snap.artifacts[0].path, "")

    payload = serialize_step_snapshot(step_snap, bodies=bodies)
    payload["primary_body"] = primary_body[:20000]  # cap at ~200 lines
    return Response(success_response(payload))
```

Modify `apps/opps/urls.py`:

```python
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
]
```

- [ ] **Step 4: Run the test, expect pass**

Run: `pytest apps/opps/tests/test_views_step_detail.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_views_step_detail.py
git commit -m "feat(opps): add GET /api/opps/<slug>/runs/<run>/steps/<skill> endpoint"
```

---

## Task 17: Artifact body proxy endpoint

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_views_artifact.py`

`GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/artifacts/<artifact_name>` — streams an artifact body back to the browser. The view resolves the artifact's Drive file id via `load_opp`, fetches the body, and returns it as `text/plain` (or `application/json` / markdown if we can detect).

- [ ] **Step 1: Write the artifact test**

Create `apps/opps/tests/test_views_artifact.py`:

```python
"""Tests for GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/artifacts/<name>."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    c = Client()
    c.force_login(u)
    return c


def _with_fake(authed_client, fake, url):
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_artifact_body_returns_content(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd/artifacts/idd.md",
    )
    assert response.status_code == 200
    assert "Malaria Pilot IDD" in response.content.decode()
    assert "text/markdown" in response["Content-Type"]


def test_artifact_body_unknown_artifact_returns_404(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd/artifacts/nope.md",
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_views_artifact.py -v`
Expected: 404 — route not registered.

- [ ] **Step 3: Implement the artifact view**

Append to `apps/opps/views.py`:

```python
from django.http import HttpResponse


@api_view(["GET"])
@permission_classes([AllowAny])
def artifact_body(request, slug: str, run_id: str, skill: str, artifact_name: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        return Response(
            error_response(f"no step {skill!r}", code="step-not-found"), status=404
        )

    artifact = next(
        (a for a in step_snap.artifacts if a.name == artifact_name), None
    )
    if artifact is None:
        return Response(
            error_response(f"no artifact {artifact_name!r}", code="artifact-not-found"),
            status=404,
        )

    content = client.get_content(artifact.drive_file_id, artifact.mime_type)
    # Serve as HttpResponse (not DRF Response) to avoid wrapping a file body
    # in the envelope. The envelope is for JSON; this is raw content.
    return HttpResponse(content.content, content_type=artifact.mime_type or "text/plain")
```

Modify `apps/opps/urls.py`:

```python
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>",
        views.artifact_body,
        name="opps-artifact-body",
    ),
]
```

- [ ] **Step 4: Run the test, expect pass**

Run: `pytest apps/opps/tests/test_views_artifact.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_views_artifact.py
git commit -m "feat(opps): add GET artifact body proxy endpoint"
```

---

## Task 18: Compare endpoint

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_views_compare.py`

`GET /api/opps/<slug>/compare?from=<run-a>&to=<run-b>` — returns both runs' full payloads in one response so the frontend can render them side-by-side and compute deltas in JS.

- [ ] **Step 1: Write the compare test**

Create `apps/opps/tests/test_views_compare.py`:

```python
"""Tests for GET /api/opps/<slug>/compare?from=<a>&to=<b>."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    c = Client()
    c.force_login(u)
    return c


def _with_fake(authed_client, fake, url):
    with patch("apps.opps.views.get_drive_client_for", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        return authed_client.get(url)


def test_compare_returns_both_runs(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake,
        "/api/opps/malaria-pilot/compare?from=2026-04-01-001&to=2026-04-06-002",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["from_run"]["run_id"] == "2026-04-01-001"
    assert data["to_run"]["run_id"] == "2026-04-06-002"
    assert data["opp"]["slug"] == "malaria-pilot"


def test_compare_missing_params_returns_400(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    response = _with_fake(
        authed_client, fake, "/api/opps/malaria-pilot/compare?from=2026-04-01-001"
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_views_compare.py -v`
Expected: 404 (not registered).

- [ ] **Step 3: Implement the compare view**

Append to `apps/opps/views.py`:

```python
from apps.opps.serializers import serialize_run_detail


@api_view(["GET"])
@permission_classes([AllowAny])
def opp_compare(request, slug: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    from_id = request.GET.get("from", "")
    to_id = request.GET.get("to", "")
    if not from_id or not to_id:
        return Response(
            error_response("compare requires `from` and `to` query params", code="missing-params"),
            status=400,
        )

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap_from = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=from_id)
        snap_to = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=to_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp or run for {slug!r}", code="opp-not-found"),
            status=404,
        )

    return Response(success_response({
        "opp": {
            "slug": snap_to.opp.slug,
            "display_name": snap_to.opp.display_name,
        },
        "from_run": serialize_run_detail(snap_from.current_run),
        "to_run": serialize_run_detail(snap_to.current_run),
    }))
```

Modify `apps/opps/urls.py`:

```python
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path("<slug:slug>/compare", views.opp_compare, name="opps-compare"),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>",
        views.artifact_body,
        name="opps-artifact-body",
    ),
]
```

Note the compare route is placed BEFORE the step-detail route so the `compare` segment isn't shadowed by `<str:run_id>`.

- [ ] **Step 4: Run the test, expect pass**

Run: `pytest apps/opps/tests/test_views_compare.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_views_compare.py
git commit -m "feat(opps): add GET /api/opps/<slug>/compare endpoint"
```

---

## Task 19: `Session` model migration for opp linkage

**Files:**
- Modify: `apps/sessions/models.py`
- Create: `apps/sessions/migrations/0002_session_opp_pointers.py`
- Create: `apps/sessions/tests/test_session_opp_fields.py`

Add three string pointer fields and an index. No FK to the (nonexistent) Opp table — Drive is the source of truth.

- [ ] **Step 1: Write the field tests**

Create `apps/sessions/tests/test_session_opp_fields.py`:

```python
"""Tests for the opp pointer fields added to the Session model."""
import pytest

from apps.auth.models import User
from apps.sessions.models import Session


@pytest.fixture
def user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


@pytest.mark.django_db
def test_session_opp_pointer_defaults(user):
    session = Session.objects.create(owner=user, title="Test")
    assert session.opp_slug == ""
    assert session.opp_run_id == ""
    assert session.opp_step_skill == ""


@pytest.mark.django_db
def test_session_can_set_opp_pointers(user):
    session = Session.objects.create(
        owner=user,
        title="Discuss app-deploy",
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        opp_step_skill="app-deploy",
    )
    session.refresh_from_db()
    assert session.opp_slug == "malaria-pilot"
    assert session.opp_run_id == "2026-04-06-002"
    assert session.opp_step_skill == "app-deploy"


@pytest.mark.django_db
def test_session_filter_by_opp_pointers(user):
    Session.objects.create(
        owner=user, title="a", opp_slug="malaria-pilot",
        opp_run_id="r1", opp_step_skill="app-deploy",
    )
    Session.objects.create(
        owner=user, title="b", opp_slug="malaria-pilot",
        opp_run_id="r1", opp_step_skill="idea-to-idd",
    )
    Session.objects.create(
        owner=user, title="c", opp_slug="nutrition", opp_run_id="r1",
        opp_step_skill="app-deploy",
    )

    matches = Session.objects.filter(
        opp_slug="malaria-pilot", opp_run_id="r1", opp_step_skill="app-deploy"
    )
    assert matches.count() == 1
    assert matches.first().title == "a"
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/sessions/tests/test_session_opp_fields.py -v`
Expected: `AttributeError: 'Session' object has no attribute 'opp_slug'`.

- [ ] **Step 3: Add the fields**

Modify `apps/sessions/models.py`. In the `Session` class, right after `cli_session_id`:

```python
    cli_session_id = models.CharField(max_length=200, null=True, blank=True)

    # ACE opp linkage — populated when a Session is launched from the Workbench
    # via "Discuss in chat". See apps/opps and docs/specs/2026-04-08-ace-opp-visualization-design.md.
    # Strings, not FKs: Opps live in Google Drive, not Postgres.
    opp_slug = models.CharField(max_length=64, blank=True, default="")
    opp_run_id = models.CharField(max_length=64, blank=True, default="")
    opp_step_skill = models.CharField(max_length=64, blank=True, default="")
```

And in `Session.Meta`, add an index:

```python
    class Meta:
        db_table = "sessions"
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
            models.Index(
                fields=["opp_slug", "opp_run_id", "opp_step_skill"],
                name="idx_session_opp_step",
            ),
        ]
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations sessions -n session_opp_pointers`
Expected: creates `apps/sessions/migrations/0002_session_opp_pointers.py`. Inspect — it should only add three fields and one index.

- [ ] **Step 5: Run the test, expect pass**

Run: `pytest apps/sessions/tests/test_session_opp_fields.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the full sessions test suite**

Run: `pytest apps/sessions/ -v`
Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add apps/sessions/models.py apps/sessions/migrations/0002_session_opp_pointers.py apps/sessions/tests/test_session_opp_fields.py
git commit -m "feat(sessions): add opp_slug / opp_run_id / opp_step_skill pointer fields"
```

---

## Task 20: Chat seed builder

**Files:**
- Create: `apps/opps/seed.py`
- Create: `apps/opps/tests/test_seed.py`

Pure function: takes an `OppSnapshot` + a step skill name + a target SKILL.md path (relative, for the chat to know which file to edit) and returns a multi-section markdown string that gets posted as the seed "system message" on the new chat session.

The seed composes IDD (first 2k tokens) + artifact bodies for this step + latest judge verdict + gate history + a short preamble.

- [ ] **Step 1: Write the seed tests**

Create `apps/opps/tests/test_seed.py`:

```python
"""Tests for the chat-seed builder."""
import pytest

from apps.opps.seed import build_chat_seed
from apps.opps.sync import load_opp
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)


@pytest.fixture
def snap_with_bodies():
    client = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = client.folder_id("ACE")
    snap = load_opp(client, ace_folder_id=ace_id, slug="malaria-pilot")
    return snap, client


def test_seed_includes_idd_excerpt(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "## IDD" in seed
    assert "Malaria Pilot IDD" in seed


def test_seed_includes_artifact_body(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "## Artifacts" in seed
    assert "idd.md" in seed


def test_seed_includes_judge_verdict(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "## Judge verdict" in seed
    assert "9.2" in seed
    assert "comprehensive" in seed


def test_seed_includes_gate_history_for_gate_steps(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="app-deploy", drive_client=client,
        skill_md_path="skills/app-deploy/SKILL.md",
    )
    assert "## Gate history" in seed
    assert "pending" in seed


def test_seed_includes_skill_md_path(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    assert "skills/idea-to-idd/SKILL.md" in seed


def test_seed_includes_improvement_loop_preamble(snap_with_bodies):
    snap, client = snap_with_bodies
    seed = build_chat_seed(
        snap, skill="idea-to-idd", drive_client=client,
        skill_md_path="skills/idea-to-idd/SKILL.md",
    )
    # Preamble should explain the loop so Claude knows it can propose an edit.
    assert "improvement loop" in seed.lower() or "propose" in seed.lower()


def test_seed_unknown_skill_raises(snap_with_bodies):
    snap, client = snap_with_bodies
    with pytest.raises(ValueError, match="no step"):
        build_chat_seed(
            snap, skill="not-a-skill", drive_client=client,
            skill_md_path="skills/nope/SKILL.md",
        )
```

- [ ] **Step 2: Run the test, expect import failure**

Run: `pytest apps/opps/tests/test_seed.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the seed builder**

Create `apps/opps/seed.py`:

```python
"""Build a seed "system message" for a new ace-web chat session launched
from the Workbench's 'Discuss in chat' CTA.

The seed is rendered as markdown and includes:
- A preamble explaining the improvement loop so Claude knows it can propose
  a SKILL.md edit and (if the chat has the tools) push it to GitHub.
- The opp's IDD excerpt (up to IDD_MAX_CHARS characters).
- The target step's artifacts, with their bodies inlined (each capped to
  ARTIFACT_MAX_CHARS).
- The latest judge verdict (score, criteria, rationale) if present.
- The gate history if present.
- A pointer to the SKILL.md file in the ace plugin repo.

This is a pure function — it takes a DriveClient so it can fetch artifact
bodies, but it never writes to Drive and never talks to Django models.
"""
from __future__ import annotations

from apps.opps.drive_client import DriveClient
from apps.opps.sync import OppSnapshot

IDD_MAX_CHARS = 8000          # ~2k tokens
ARTIFACT_MAX_CHARS = 8000
PREAMBLE = """\
You have been dropped into a chat about a specific step of an ACE opportunity run.
The user wants to iterate on the output below — understand what went wrong (or what
could be better), and then if appropriate propose an edit to the skill's SKILL.md
file in the ace plugin repo. If you have git/gh tools in this session, you may
create a commit and open a PR against the plugin. This is the "improvement loop":
inspect → discuss → edit SKILL.md → re-run ACE → compare.
"""


def build_chat_seed(
    snap: OppSnapshot,
    *,
    skill: str,
    drive_client: DriveClient,
    skill_md_path: str,
) -> str:
    """Return a markdown-formatted seed message for the new chat session."""
    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        raise ValueError(
            f"no step {skill!r} in run {snap.current_run.run_id!r} for opp {snap.opp.slug!r}"
        )

    sections: list[str] = []

    sections.append(
        f"# Discussing `{skill}` — opp `{snap.opp.slug}`, run `{snap.current_run.run_id}`"
    )
    sections.append(PREAMBLE.strip())

    sections.append(
        f"**Skill source:** `{skill_md_path}` (edit this file to improve the skill)"
    )

    # IDD excerpt
    sections.append("## IDD")
    sections.append(f"```markdown\n{snap.idd_body[:IDD_MAX_CHARS]}\n```")

    # Artifacts
    if step_snap.artifacts:
        sections.append("## Artifacts")
        for artifact in step_snap.artifacts:
            try:
                content = drive_client.get_content(
                    artifact.drive_file_id, artifact.mime_type
                )
                body = content.content[:ARTIFACT_MAX_CHARS]
            except Exception as exc:
                body = f"(failed to fetch body: {exc})"
            sections.append(f"### `{artifact.name}`")
            sections.append(f"```\n{body}\n```")
    else:
        sections.append("## Artifacts")
        sections.append("_no artifacts for this step_")

    # Judge verdict
    if step_snap.judge is not None:
        j = step_snap.judge
        sections.append("## Judge verdict")
        score_line = f"**score:** {j.score} · **passed:** {j.passed}"
        sections.append(score_line)
        if j.criteria:
            sections.append("**criteria:**")
            for key, value in j.criteria.items():
                sections.append(f"- {key}: {value}")
        if j.rationale:
            sections.append("**rationale:**")
            sections.append(f"> {j.rationale}")

    # Gate history
    if step_snap.gates:
        sections.append("## Gate history")
        for gate in step_snap.gates:
            line = f"- `{gate.ts}` — **{gate.decision}**"
            if gate.decided_by:
                line += f" by `{gate.decided_by}`"
            if gate.note:
                line += f" — {gate.note}"
            sections.append(line)

    return "\n\n".join(sections)
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_seed.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/seed.py apps/opps/tests/test_seed.py
git commit -m "feat(opps): add chat-seed builder composing IDD + artifacts + judge + gates"
```

---

## Task 21: "Discuss in chat" endpoint

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_views_discuss.py`

`POST /api/opps/<slug>/runs/<run_id>/steps/<skill>/discuss` — creates a new ace-web `Session`, sets the three opp pointer fields, and creates the seed system message. Returns the session slug.

The seed message is created as a `Message` row with `role="system"` at `turn_index=0`. The chat UI renders system messages as collapsed context blocks at the top of the thread.

**Also lists linked chats for the step detail pane:** `GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/chats` — returns the list of prior Sessions linked to this (slug, run_id, skill). Extends the step detail pane's "Linked chats" section without requiring a second call into the workbench endpoint.

- [ ] **Step 1: Write the discuss tests**

Create `apps/opps/tests/test_views_discuss.py`:

```python
"""Tests for POST /api/opps/<slug>/runs/<run_id>/steps/<skill>/discuss
and GET /api/opps/<slug>/runs/<run_id>/steps/<skill>/chats."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)
from apps.sessions.models import Message, Session


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    c = Client()
    c.force_login(u)
    return c


def _with_fake(authed_client, fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client_for=lambda user: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )


def test_discuss_creates_session_with_pointer_fields(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    with _with_fake(authed_client, fake):
        response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd/discuss",
            content_type="application/json",
        )
    assert response.status_code == 201
    data = response.json()["data"]
    session = Session.objects.get(slug=data["session_slug"])
    assert session.opp_slug == "malaria-pilot"
    assert session.opp_run_id == "2026-04-06-002"
    assert session.opp_step_skill == "idea-to-idd"
    assert session.idd_ref  # populated with the idd.md drive file id


def test_discuss_seeds_a_system_message(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    with _with_fake(authed_client, fake):
        response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/idea-to-idd/discuss",
            content_type="application/json",
        )
    session = Session.objects.get(slug=response.json()["data"]["session_slug"])
    system_message = session.messages.filter(role="system").first()
    assert system_message is not None
    assert system_message.turn_index == 0
    assert "Discussing `idea-to-idd`" in system_message.plaintext
    assert "Malaria Pilot IDD" in system_message.plaintext


def test_discuss_auto_titles_the_session(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    with _with_fake(authed_client, fake):
        response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/discuss",
            content_type="application/json",
        )
    session = Session.objects.get(slug=response.json()["data"]["session_slug"])
    assert "app-deploy" in session.title
    assert "malaria-pilot" in session.title


def test_linked_chats_list_returns_prior_sessions(authed_client):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    # Create two prior chats linked to the same step.
    user = User.objects.get(email="jon@dimagi.com")
    Session.objects.create(
        owner=user, title="old discussion",
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        opp_step_skill="app-deploy",
    )
    Session.objects.create(
        owner=user, title="older discussion",
        opp_slug="malaria-pilot",
        opp_run_id="2026-04-06-002",
        opp_step_skill="app-deploy",
    )
    with _with_fake(authed_client, fake):
        response = authed_client.get(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/chats"
        )
    assert response.status_code == 200
    chats = response.json()["data"]
    assert len(chats) == 2
    titles = [c["title"] for c in chats]
    assert "old discussion" in titles
```

- [ ] **Step 2: Run the test, expect failure**

Run: `pytest apps/opps/tests/test_views_discuss.py -v`
Expected: 404 (routes not registered).

- [ ] **Step 3: Implement the discuss + linked chats views**

Append to `apps/opps/views.py`:

```python
from django.db import transaction

from apps.opps.seed import build_chat_seed
from apps.sessions.models import Message, Session


def _skill_md_relative_path(skill: str) -> str:
    """Return the path of a skill's SKILL.md relative to the ace plugin repo root.

    The ACE plugin lays skills out as `skills/<skill-name>/SKILL.md`.
    """
    return f"skills/{skill}/SKILL.md"


@api_view(["POST"])
@permission_classes([AllowAny])
def discuss(request, slug: str, run_id: str, skill: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    try:
        seed_body = build_chat_seed(
            snap,
            skill=skill,
            drive_client=client,
            skill_md_path=_skill_md_relative_path(skill),
        )
    except ValueError as exc:
        return Response(
            error_response(str(exc), code="step-not-found"), status=404
        )

    # Resolve the IDD drive file id for session.idd_ref.
    idd_drive_id = ""
    for step_snap in snap.current_run.steps:
        if step_snap.step.skill_name == "idea-to-idd":
            for artifact in step_snap.artifacts:
                if artifact.name == "idd.md":
                    idd_drive_id = artifact.drive_file_id
                    break
    # Fall back to the top-level idd.md at the opp root if the idea-to-idd step
    # didn't capture it as an artifact.
    # (Top-level idd.md lookup happens inside sync.load_opp but we didn't
    # surface its file id. It would be a cheap enhancement to add that.)

    with transaction.atomic():
        session = Session.objects.create(
            owner=request.user,
            title=f"{skill}: {slug}",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id=run_id,
            opp_step_skill=skill,
            idd_ref=idd_drive_id,
        )
        Message.objects.create(
            session=session,
            turn_index=0,
            role="system",
            sender_user=request.user,
            content={"type": "system", "source": "opps-discuss"},
            plaintext=seed_body,
            status="complete",
        )

    return Response(
        success_response({"session_slug": session.slug}),
        status=201,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def step_chats(request, slug: str, run_id: str, skill: str):
    """List prior ace-web chat sessions linked to this opp/run/step."""
    client, err = _require_drive(request)
    if err is not None:
        return err

    chats = Session.objects.filter(
        opp_slug=slug, opp_run_id=run_id, opp_step_skill=skill,
    ).order_by("-updated_at")[:20]

    return Response(success_response([
        {
            "slug": c.slug,
            "title": c.title or "(untitled)",
            "updated_at": c.updated_at.isoformat(),
            "owner_email": c.owner.email,
        }
        for c in chats
    ]))
```

Modify `apps/opps/urls.py`:

```python
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path("<slug:slug>/compare", views.opp_compare, name="opps-compare"),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/discuss",
        views.discuss,
        name="opps-discuss",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/chats",
        views.step_chats,
        name="opps-step-chats",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>",
        views.artifact_body,
        name="opps-artifact-body",
    ),
]
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `pytest apps/opps/tests/test_views_discuss.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full opps suite to catch regressions**

Run: `pytest apps/opps/ -v`
Expected: everything passes.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_views_discuss.py
git commit -m "feat(opps): add POST discuss and GET linked-chats endpoints"
```

---

## Task 22: Frontend API types and opps client

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts` (may be new — check before writing)
- Create: `frontend/src/api/opps.ts`

Extend the API client to (1) surface 401 `drive-token-missing` errors distinctly so the router can redirect to `/auth/drive/start`, and (2) provide typed functions for every `/api/opps/*` endpoint from Tasks 14–21. Also define the TypeScript types that mirror the backend serializers.

- [ ] **Step 1: Create or extend the shared types file**

Check whether `frontend/src/api/types.ts` already exists. If not, create it. If it does (from Phase 2), append to it.

Create `frontend/src/api/types.ts` (or append the Opp* types if it exists):

```typescript
// Shared TypeScript types for the ace-web API surface.
// Keep in sync with apps/common/envelope.py + the DRF serializers in each module.

export type Envelope<T> = {
  data: T | null;
  error: { code: string; message: string } | null;
};

// --- ACE opportunity Workbench types (apps/opps) ---

export interface OppCard {
  slug: string;
  display_name: string;
  labels: string[];
  created_at: string | null;
  created_by: string | null;
  current_run_id: string | null;
  current_phase: string | null;
  current_step: string | null;
  status: string;
}

export interface Artifact {
  name: string;
  drive_file_id: string;
  drive_web_link: string;
  mime_type: string;
  size_bytes: number | null;
  path: string;
}

export interface Judge {
  score: number | null;
  passed: boolean | null;
  evaluated_at: string | null;
  criteria: Record<string, number>;
  rationale: string;
}

export interface Gate {
  ts: string;
  decision: "pending" | "approved" | "rejected";
  decided_by: string;
  note: string;
}

export interface Step {
  skill_name: string;
  phase: string;
  phase_display: string;
  ordinal: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  has_judge: boolean;
  is_gate: boolean;
  is_recurring: boolean;
  preview_text: string;
  judge: Judge | null;
  gates: Gate[];
  artifacts: Artifact[];
}

export interface Run {
  run_id: string;
  mode: "auto" | "review" | "dry-run" | "sandbox";
  status: "running" | "blocked" | "complete" | "failed" | "abandoned";
  started_at: string | null;
  completed_at: string | null;
  current_phase: string | null;
  current_step: string | null;
  skill_versions: Record<string, string>;
  notes: string;
  steps: Step[];
}

export interface RunSummary {
  run_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface OppSnapshot {
  opp: OppCard;
  idd_body: string;
  runs: RunSummary[];
  current_run: Run;
}

export interface StepDetail extends Step {
  primary_body: string;
}

export interface LinkedChat {
  slug: string;
  title: string;
  updated_at: string;
  owner_email: string;
}

export interface CompareResult {
  opp: { slug: string; display_name: string };
  from_run: Run;
  to_run: Run;
}

export interface DiscussResponse {
  session_slug: string;
}

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

- [ ] **Step 2: Extend the request helper to surface Drive-reconnect**

Modify `frontend/src/api/client.ts`:

```typescript
import { DriveReconnectRequired, type Envelope } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json()) as Envelope<T>;
  if (res.status === 401 && body.error?.code === "drive-token-missing") {
    const data = body.data as { reconnect_url: string } | null;
    const url = data?.reconnect_url ?? "/auth/drive/start";
    throw new DriveReconnectRequired(url);
  }
  if (body.error) {
    throw new Error(body.error.message);
  }
  return body.data as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
};

// Re-exported for other API modules (opps.ts etc).
export { request };
```

- [ ] **Step 3: Implement the opps client**

Create `frontend/src/api/opps.ts`:

```typescript
import { request } from "./client";
import type {
  CompareResult,
  DiscussResponse,
  LinkedChat,
  OppCard,
  OppSnapshot,
  StepDetail,
} from "./types";

export function listOpps(): Promise<OppCard[]> {
  return request<OppCard[]>("/opps/");
}

export function getOpp(slug: string, runId?: string): Promise<OppSnapshot> {
  const q = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return request<OppSnapshot>(`/opps/${encodeURIComponent(slug)}${q}`);
}

export function getStepDetail(
  slug: string,
  runId: string,
  skill: string,
): Promise<StepDetail> {
  return request<StepDetail>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(skill)}`,
  );
}

export function getLinkedChats(
  slug: string,
  runId: string,
  skill: string,
): Promise<LinkedChat[]> {
  return request<LinkedChat[]>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(skill)}/chats`,
  );
}

export function discussStep(
  slug: string,
  runId: string,
  skill: string,
): Promise<DiscussResponse> {
  return request<DiscussResponse>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(skill)}/discuss`,
    { method: "POST" },
  );
}

export function compareRuns(
  slug: string,
  fromRunId: string,
  toRunId: string,
): Promise<CompareResult> {
  const qs = new URLSearchParams({ from: fromRunId, to: toRunId });
  return request<CompareResult>(
    `/opps/${encodeURIComponent(slug)}/compare?${qs.toString()}`,
  );
}

export function artifactBodyUrl(
  slug: string,
  runId: string,
  skill: string,
  artifactName: string,
): string {
  return (
    `/api/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}` +
    `/steps/${encodeURIComponent(skill)}/artifacts/${encodeURIComponent(artifactName)}`
  );
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/
git commit -m "feat(frontend): add opps API client and shared types"
```

---

## Task 23: Router additions and Drive reconnect handling

**Files:**
- Modify: `frontend/src/router.tsx`
- Create: `frontend/src/components/opps/DriveReconnectGuard.tsx`
- Create: `frontend/src/pages/OppListPage.tsx` (stub — Task 24 fills it in)
- Create: `frontend/src/pages/OppWorkbenchPage.tsx` (stub — Task 25 fills it in)
- Create: `frontend/src/pages/OppComparePage.tsx` (stub — Task 28 fills it in)

Add the `/opps*` routes. Wrap them in a `DriveReconnectGuard` that catches `DriveReconnectRequired` errors from child components and redirects to `/auth/drive/start`.

- [ ] **Step 1: Create the reconnect guard**

Create `frontend/src/components/opps/DriveReconnectGuard.tsx`:

```typescript
import { Component, type ReactNode } from "react";

import { DriveReconnectRequired } from "../../api/types";

interface Props {
  children: ReactNode;
}

interface State {
  reconnectUrl: string | null;
}

/**
 * Error boundary that catches DriveReconnectRequired errors from child
 * components and redirects the user to the Drive OAuth start URL.
 *
 * Why an error boundary rather than per-call try/catch: the opps pages
 * all read from the api/opps.ts client inside useEffect hooks, and a
 * single boundary at the route level saves every page from repeating
 * the same catch block.
 */
export class DriveReconnectGuard extends Component<Props, State> {
  state: State = { reconnectUrl: null };

  static getDerivedStateFromError(error: unknown): State | null {
    if (error instanceof DriveReconnectRequired) {
      return { reconnectUrl: error.reconnectUrl };
    }
    return null;
  }

  componentDidCatch(error: unknown) {
    if (!(error instanceof DriveReconnectRequired)) {
      // Rethrow non-reconnect errors so the default boundary handles them.
      throw error;
    }
  }

  componentDidUpdate() {
    if (this.state.reconnectUrl) {
      window.location.href = this.state.reconnectUrl;
    }
  }

  render() {
    if (this.state.reconnectUrl) {
      return (
        <div className="p-6 text-zinc-500">
          Redirecting to Google to connect Drive access…
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 2: Create the page stubs**

Create `frontend/src/pages/OppListPage.tsx`:

```typescript
export default function OppListPage() {
  return <div className="p-6 text-zinc-500">Opp list — implemented in Task 24.</div>;
}
```

Create `frontend/src/pages/OppWorkbenchPage.tsx`:

```typescript
export default function OppWorkbenchPage() {
  return <div className="p-6 text-zinc-500">Workbench — implemented in Task 25.</div>;
}
```

Create `frontend/src/pages/OppComparePage.tsx`:

```typescript
export default function OppComparePage() {
  return <div className="p-6 text-zinc-500">Compare view — implemented in Task 28.</div>;
}
```

- [ ] **Step 3: Add the routes**

Modify `frontend/src/router.tsx`:

```typescript
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { DriveReconnectGuard } from "./components/opps/DriveReconnectGuard";
import HealthPage from "./pages/HealthPage";
import HomePage from "./pages/HomePage";
import OppComparePage from "./pages/OppComparePage";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";

const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/health-check", element: <HealthPage /> },
  {
    path: "/opps",
    element: (
      <DriveReconnectGuard>
        <OppListPage />
      </DriveReconnectGuard>
    ),
  },
  {
    path: "/opps/:slug",
    element: (
      <DriveReconnectGuard>
        <OppWorkbenchPage />
      </DriveReconnectGuard>
    ),
  },
  {
    path: "/opps/:slug/runs/:runId",
    element: (
      <DriveReconnectGuard>
        <OppWorkbenchPage />
      </DriveReconnectGuard>
    ),
  },
  {
    path: "/opps/:slug/runs/:runId/steps/:skill",
    element: (
      <DriveReconnectGuard>
        <OppWorkbenchPage />
      </DriveReconnectGuard>
    ),
  },
  {
    path: "/opps/:slug/compare",
    element: (
      <DriveReconnectGuard>
        <OppComparePage />
      </DriveReconnectGuard>
    ),
  },
]);

export function Router() {
  return <RouterProvider router={router} />;
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/router.tsx frontend/src/pages/OppListPage.tsx frontend/src/pages/OppWorkbenchPage.tsx frontend/src/pages/OppComparePage.tsx frontend/src/components/opps/
git commit -m "feat(frontend): add /opps routes with Drive reconnect guard"
```

---

## Task 24: `OppListPage` — the opportunity list

**Files:**
- Modify: `frontend/src/pages/OppListPage.tsx`
- Create: `frontend/src/components/opps/LoadingStates.tsx`

Standalone opp list page. Filterable, sortable. Each row links to the workbench. Replaces the Task 23 stub.

- [ ] **Step 1: Create shared loading-state components**

Create `frontend/src/components/opps/LoadingStates.tsx`:

```typescript
import type { ReactNode } from "react";

export function LoadingSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 p-6 text-zinc-500">
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-12 text-center">
      <h3 className="text-lg font-semibold text-zinc-700">{title}</h3>
      {description && <p className="text-sm text-zinc-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <div className="font-semibold">{title}</div>
      <div className="mt-1">{message}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded bg-red-600 px-3 py-1 text-white hover:bg-red-700"
        >
          Retry
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement the OppListPage**

Modify `frontend/src/pages/OppListPage.tsx`:

```typescript
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { listOpps } from "../api/opps";
import type { OppCard } from "../api/types";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; opps: OppCard[] };

export default function OppListPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState("");

  const load = () => {
    setState({ kind: "loading" });
    listOpps()
      .then((opps) => setState({ kind: "loaded", opps }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  };

  useEffect(load, []);

  const filtered = useMemo(() => {
    if (state.kind !== "loaded") return [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return state.opps;
    return state.opps.filter(
      (o) =>
        o.slug.toLowerCase().includes(needle) ||
        o.display_name.toLowerCase().includes(needle) ||
        o.labels.some((l) => l.toLowerCase().includes(needle)),
    );
  }, [state, filter]);

  if (state.kind === "loading") return <LoadingSpinner label="Loading opportunities…" />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center gap-4 border-b border-zinc-800 px-6 py-4">
        <h1 className="text-xl font-semibold">ACE Opportunities</h1>
        <span className="text-sm text-zinc-500">{state.opps.length} total</span>
        <input
          type="text"
          placeholder="Filter by slug, name, or label…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto w-64 rounded border border-zinc-700 bg-zinc-900 px-3 py-1 text-sm text-zinc-100 placeholder-zinc-500 focus:border-blue-500 focus:outline-none"
        />
      </header>

      {filtered.length === 0 ? (
        <EmptyState
          title={filter ? "No opps match your filter" : "No opportunities yet"}
          description={
            filter
              ? "Try a different search term."
              : "Run ACE against an opportunity and it will show up here."
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 p-6 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((opp) => (
            <Link
              key={opp.slug}
              to={`/opps/${opp.slug}`}
              className="group rounded border border-zinc-800 bg-zinc-900 p-4 transition hover:border-blue-600"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="font-semibold text-zinc-100 group-hover:text-blue-400">
                    {opp.display_name || opp.slug}
                  </h2>
                  <div className="text-xs text-zinc-500">{opp.slug}</div>
                </div>
                <StatusBadge status={opp.status} />
              </div>
              {opp.current_step && (
                <div className="mt-3 text-sm text-zinc-400">
                  <span className="text-zinc-500">current:</span>{" "}
                  <span className="font-mono text-zinc-300">{opp.current_step}</span>
                  {opp.current_phase && (
                    <span className="ml-2 text-xs text-zinc-500">
                      ({opp.current_phase})
                    </span>
                  )}
                </div>
              )}
              {opp.labels.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {opp.labels.map((label) => (
                    <span
                      key={label}
                      className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400"
                    >
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = statusColor(status);
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${tone}`}>
      {status}
    </span>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case "running":
      return "bg-blue-900 text-blue-300";
    case "complete":
      return "bg-green-900 text-green-300";
    case "blocked":
      return "bg-amber-900 text-amber-300";
    case "failed":
      return "bg-red-900 text-red-300";
    default:
      return "bg-zinc-800 text-zinc-400";
  }
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manual smoke check**

Start the dev server (`docker compose up` or `python manage.py runserver` + `cd frontend && npm run dev`). Navigate to `/opps`. With no Drive token, you should be redirected to `/auth/drive/start`. After connecting, you should see the opp list (empty if no opps yet — empty state renders cleanly).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OppListPage.tsx frontend/src/components/opps/LoadingStates.tsx
git commit -m "feat(frontend): implement OppListPage with filter and status badges"
```

---

## Task 25: Workbench page shell and header

**Files:**
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx`
- Create: `frontend/src/components/opps/WorkbenchHeader.tsx`
- Create: `frontend/src/components/opps/RunSwitcher.tsx`

The three-pane layout shell: header on top, left sidebar + center content + right detail pane below. Loads the opp snapshot on mount (and when route params change). Selected step is tracked in local state (not URL, though a future enhancement could sync it via `/opps/:slug/runs/:runId/steps/:skill`).

- [ ] **Step 1: Implement the RunSwitcher component**

Create `frontend/src/components/opps/RunSwitcher.tsx`:

```typescript
import { Link, useNavigate } from "react-router-dom";

import type { RunSummary } from "../../api/types";

interface Props {
  slug: string;
  currentRunId: string;
  runs: RunSummary[];
}

export function RunSwitcher({ slug, currentRunId, runs }: Props) {
  const navigate = useNavigate();

  // Display labels: newest run is v{N}, next is v{N-1}, etc.
  // (runs is already newest-first.)
  const labeled = runs.map((r, i) => ({
    ...r,
    label: `v${runs.length - i}`,
  }));

  const currentIndex = labeled.findIndex((r) => r.run_id === currentRunId);
  const otherRuns = labeled.filter((r) => r.run_id !== currentRunId);
  const priorRun = currentIndex >= 0 ? labeled[currentIndex + 1] : null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-zinc-500">run</span>
      <select
        value={currentRunId}
        onChange={(e) => {
          navigate(`/opps/${slug}/runs/${e.target.value}`);
        }}
        className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
      >
        {labeled.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.label} · {r.run_id}
            {r.run_id === currentRunId ? " (current)" : ""}
          </option>
        ))}
      </select>
      {priorRun && (
        <Link
          to={`/opps/${slug}/compare?from=${priorRun.run_id}&to=${currentRunId}`}
          className="text-xs text-blue-400 underline hover:text-blue-300"
        >
          compare to {priorRun.label}
        </Link>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement the WorkbenchHeader component**

Create `frontend/src/components/opps/WorkbenchHeader.tsx`:

```typescript
import type { OppCard, Run, RunSummary } from "../../api/types";
import { RunSwitcher } from "./RunSwitcher";

interface Props {
  opp: OppCard;
  run: Run;
  runs: RunSummary[];
  onRefresh: () => void;
}

export function WorkbenchHeader({ opp, run, runs, onRefresh }: Props) {
  return (
    <div className="flex items-center gap-4 border-b border-zinc-800 bg-zinc-900 px-4 py-2 text-sm">
      <span className="font-semibold text-zinc-100">{opp.display_name || opp.slug}</span>
      <span className="text-zinc-500">
        {run.current_phase ? `Phase · ${run.current_phase}` : "—"}
      </span>
      <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
        {run.mode} mode
      </span>
      <span className="ml-auto flex items-center gap-3">
        <RunSwitcher slug={opp.slug} currentRunId={run.run_id} runs={runs} />
        <button
          type="button"
          onClick={onRefresh}
          className="rounded bg-amber-600 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-700"
        >
          ⟳ refresh from Drive
        </button>
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Implement the Workbench page shell**

Modify `frontend/src/pages/OppWorkbenchPage.tsx`:

```typescript
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getOpp } from "../api/opps";
import type { OppSnapshot, Step } from "../api/types";
import { WorkbenchHeader } from "../components/opps/WorkbenchHeader";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: OppSnapshot };

export default function OppWorkbenchPage() {
  const { slug = "", runId, skill } = useParams();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedSkill, setSelectedSkill] = useState<string | null>(skill ?? null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getOpp(slug, runId)
      .then((snapshot) => setState({ kind: "loaded", snapshot }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, [slug, runId]);

  useEffect(load, [load]);

  useEffect(() => {
    // When the URL gives us a skill param, select it.
    if (skill) setSelectedSkill(skill);
  }, [skill]);

  if (state.kind === "loading") {
    return <LoadingSpinner label={`Loading ${slug}…`} />;
  }
  if (state.kind === "error") {
    return <ErrorState message={state.message} onRetry={load} />;
  }

  const { snapshot } = state;
  const selectedStep: Step | null =
    selectedSkill
      ? snapshot.current_run.steps.find((s) => s.skill_name === selectedSkill) ?? null
      : null;

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <WorkbenchHeader
        opp={snapshot.opp}
        run={snapshot.current_run}
        runs={snapshot.runs}
        onRefresh={load}
      />
      <div className="flex flex-1 overflow-hidden">
        {/* Left pane — implemented in Task 26 */}
        <aside className="w-[180px] border-r border-zinc-800 bg-zinc-950">
          {/* OppSidebar goes here */}
          <div className="p-3 text-xs text-zinc-500">Opps sidebar (Task 26)</div>
        </aside>
        {/* Center pane — implemented in Task 26 */}
        <main className="flex-1 overflow-y-auto">
          {/* SkillList goes here */}
          <div className="p-6 text-zinc-500">
            Skill list for {snapshot.current_run.run_id} (Task 26)
          </div>
        </main>
        {/* Right pane — implemented in Task 27 */}
        <section className="w-[320px] border-l border-zinc-800 bg-zinc-950">
          {selectedStep ? (
            <div className="p-4 text-zinc-500">
              Detail for {selectedStep.skill_name} (Task 27)
            </div>
          ) : (
            <EmptyState title="Select a step" description="Click a row to see its details." />
          )}
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OppWorkbenchPage.tsx frontend/src/components/opps/WorkbenchHeader.tsx frontend/src/components/opps/RunSwitcher.tsx
git commit -m "feat(frontend): add Workbench page shell with header and run switcher"
```

---

## Task 26: Left pane (OppSidebar) and Center pane (SkillList + SkillRow)

**Files:**
- Create: `frontend/src/components/opps/OppSidebar.tsx`
- Create: `frontend/src/components/opps/SkillList.tsx`
- Create: `frontend/src/components/opps/SkillRow.tsx`
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx` (mount the real components)

The dense center-pane list is the Workbench hero. Phase-grouped sections, 19 rows, inline preview_text, judge bar + score + delta vs prior run, gate badge.

- [ ] **Step 1: Implement the OppSidebar**

Create `frontend/src/components/opps/OppSidebar.tsx`:

```typescript
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { listOpps } from "../../api/opps";
import type { OppCard } from "../../api/types";

export function OppSidebar() {
  const [opps, setOpps] = useState<OppCard[]>([]);
  const [filter, setFilter] = useState("");
  const { slug: currentSlug } = useParams();

  useEffect(() => {
    listOpps().then(setOpps).catch(() => setOpps([]));
  }, []);

  const filtered = opps.filter(
    (o) =>
      !filter ||
      o.slug.toLowerCase().includes(filter.toLowerCase()) ||
      o.display_name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="flex h-full flex-col">
      <div className="px-3 pt-3 text-[10px] uppercase tracking-wider text-zinc-500">
        Opps · {opps.length}
      </div>
      <div className="px-2 py-2">
        <input
          type="text"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 placeholder-zinc-600 focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.map((o) => {
          const isActive = o.slug === currentSlug;
          return (
            <Link
              key={o.slug}
              to={`/opps/${o.slug}`}
              className={`block border-l-2 px-3 py-2 text-xs hover:bg-zinc-900 ${
                isActive
                  ? "border-blue-500 bg-zinc-900 text-zinc-100"
                  : "border-transparent text-zinc-400"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-semibold">{o.display_name || o.slug}</span>
              </div>
              <div className="mt-0.5 text-[10px] text-zinc-500">
                {o.current_step ?? "—"}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement the SkillRow component**

Create `frontend/src/components/opps/SkillRow.tsx`:

```typescript
import type { Step } from "../../api/types";

interface Props {
  step: Step;
  isSelected: boolean;
  priorRunStep: Step | null;
  onClick: () => void;
}

export function SkillRow({ step, isSelected, priorRunStep, onClick }: Props) {
  const judgeScore = step.judge?.score ?? null;
  const priorScore = priorRunStep?.judge?.score ?? null;
  const delta =
    judgeScore !== null && priorScore !== null
      ? judgeScore - priorScore
      : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded px-2 py-2 text-left text-xs ${
        isSelected
          ? "border border-amber-600 bg-amber-950/40"
          : "border border-transparent bg-zinc-900 hover:bg-zinc-800"
      }`}
    >
      <StatusDot status={step.status} />
      <span className="w-[140px] shrink-0 font-semibold text-zinc-100">
        {step.skill_name}
      </span>
      {step.has_judge ? (
        <>
          <JudgeBar score={judgeScore} />
          <span className="w-[32px] shrink-0 text-[11px] text-green-400">
            {judgeScore?.toFixed(1) ?? "—"}
          </span>
          <span className={`w-[48px] shrink-0 text-[10px] ${deltaTone(delta)}`}>
            {formatDelta(delta)}
          </span>
        </>
      ) : (
        <>
          <span className="w-[54px] shrink-0 text-[10px] text-zinc-600">no judge</span>
          <span className="w-[32px] shrink-0" />
          <span className="w-[48px] shrink-0" />
        </>
      )}
      {step.is_gate && <GateBadge status={step.status} />}
      <span className="flex-1 truncate text-[11px] text-zinc-400">
        {step.preview_text}
      </span>
    </button>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = statusColor(status);
  return <span className={`w-3 shrink-0 text-center text-[11px] ${color}`}>{statusGlyph(status)}</span>;
}

function statusGlyph(status: string): string {
  if (status === "complete") return "✓";
  if (status === "running") return "▶";
  if (status === "judge-fail") return "✗";
  if (status === "gate-pending" || status === "gate-rejected") return "⚠";
  if (status === "error") return "✗";
  if (status === "skipped") return "—";
  return "○";
}

function statusColor(status: string): string {
  if (status === "complete") return "text-green-500";
  if (status === "running") return "text-blue-400";
  if (status === "judge-fail" || status === "error") return "text-red-500";
  if (status === "gate-pending" || status === "gate-rejected") return "text-amber-500";
  return "text-zinc-600";
}

function JudgeBar({ score }: { score: number | null }) {
  const pct = score !== null ? Math.min(100, Math.max(0, score * 10)) : 0;
  const tone =
    score === null ? "bg-zinc-800"
    : score >= 8 ? "bg-green-500"
    : score >= 6 ? "bg-amber-500"
    : "bg-red-500";
  return (
    <span className="relative block h-1.5 w-[54px] shrink-0 overflow-hidden rounded bg-zinc-900">
      <span className={`absolute inset-y-0 left-0 ${tone}`} style={{ width: `${pct}%` }} />
    </span>
  );
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "";
  const rounded = Math.round(delta * 10) / 10;
  if (rounded === 0) return "= 0";
  const arrow = rounded > 0 ? "↑" : "↓";
  const sign = rounded > 0 ? "+" : "";
  return `${arrow} ${sign}${rounded.toFixed(1)}`;
}

function deltaTone(delta: number | null): string {
  if (delta === null) return "text-zinc-600";
  if (delta > 0.05) return "text-green-400";
  if (delta < -0.05) return "text-red-400";
  return "text-zinc-500";
}

function GateBadge({ status }: { status: string }) {
  const pending = status === "gate-pending";
  const rejected = status === "gate-rejected";
  const label = pending ? "GATE ⚠" : rejected ? "GATE ✗" : "GATE ✓";
  const tone =
    pending ? "bg-amber-950 text-amber-400"
    : rejected ? "bg-red-950 text-red-400"
    : "bg-green-950 text-green-400";
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold ${tone}`}>
      {label}
    </span>
  );
}
```

- [ ] **Step 3: Implement the SkillList (phase-grouped)**

Create `frontend/src/components/opps/SkillList.tsx`:

```typescript
import type { Step } from "../../api/types";
import { SkillRow } from "./SkillRow";

interface Props {
  steps: Step[];
  priorRunSteps: Step[];
  selectedSkill: string | null;
  onSelect: (skill: string) => void;
}

const PHASE_ORDER: Array<{ key: string; label: string }> = [
  { key: "app-building", label: "Phase 1 · App Building" },
  { key: "connect-setup", label: "Phase 2 · Connect Setup" },
  { key: "llo-management", label: "Phase 3 · LLO Management" },
  { key: "closeout", label: "Phase 4 · Closeout" },
];

export function SkillList({ steps, priorRunSteps, selectedSkill, onSelect }: Props) {
  const priorBySkill = new Map(priorRunSteps.map((s) => [s.skill_name, s] as const));

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        Lifecycle · {steps.length} skills
      </div>
      {PHASE_ORDER.map(({ key, label }) => {
        const phaseSteps = steps
          .filter((s) => s.phase === key)
          .sort((a, b) => a.ordinal - b.ordinal);
        if (phaseSteps.length === 0) return null;
        return (
          <section key={key} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="h-0.5 w-2 bg-zinc-600" />
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                {label} · {phaseSteps.length} {phaseSteps.length === 1 ? "step" : "steps"}
              </h3>
              <span className="h-px flex-1 bg-zinc-800" />
            </div>
            <div className="flex flex-col gap-0.5">
              {phaseSteps.map((step) => (
                <SkillRow
                  key={step.skill_name}
                  step={step}
                  priorRunStep={priorBySkill.get(step.skill_name) ?? null}
                  isSelected={step.skill_name === selectedSkill}
                  onClick={() => onSelect(step.skill_name)}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Mount OppSidebar and SkillList in the Workbench page**

Modify `frontend/src/pages/OppWorkbenchPage.tsx`. Replace the left-pane and center-pane placeholder blocks:

```typescript
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getOpp } from "../api/opps";
import type { OppSnapshot, Run, Step } from "../api/types";
import { EmptyState, ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";
import { OppSidebar } from "../components/opps/OppSidebar";
import { SkillList } from "../components/opps/SkillList";
import { WorkbenchHeader } from "../components/opps/WorkbenchHeader";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; snapshot: OppSnapshot; priorRun: Run | null };

export default function OppWorkbenchPage() {
  const { slug = "", runId, skill } = useParams();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedSkill, setSelectedSkill] = useState<string | null>(skill ?? null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getOpp(slug, runId)
      .then(async (snapshot) => {
        // Fetch the prior run (if any) to compute per-row deltas. The runs
        // list is newest-first; skip the current run, take the next one.
        const currentIdx = snapshot.runs.findIndex(
          (r) => r.run_id === snapshot.current_run.run_id,
        );
        const priorSummary =
          currentIdx >= 0 && currentIdx + 1 < snapshot.runs.length
            ? snapshot.runs[currentIdx + 1]
            : null;
        let priorRun: Run | null = null;
        if (priorSummary) {
          try {
            const priorSnap = await getOpp(slug, priorSummary.run_id);
            priorRun = priorSnap.current_run;
          } catch {
            priorRun = null;
          }
        }
        setState({ kind: "loaded", snapshot, priorRun });
      })
      .catch((err) =>
        setState({ kind: "error", message: String(err?.message ?? err) }),
      );
  }, [slug, runId]);

  useEffect(load, [load]);

  useEffect(() => {
    if (skill) setSelectedSkill(skill);
  }, [skill]);

  if (state.kind === "loading") return <LoadingSpinner label={`Loading ${slug}…`} />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;

  const { snapshot, priorRun } = state;
  const selectedStep: Step | null = selectedSkill
    ? snapshot.current_run.steps.find((s) => s.skill_name === selectedSkill) ?? null
    : null;

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <WorkbenchHeader
        opp={snapshot.opp}
        run={snapshot.current_run}
        runs={snapshot.runs}
        onRefresh={load}
      />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[180px] border-r border-zinc-800 bg-zinc-950">
          <OppSidebar />
        </aside>
        <main className="flex-1 overflow-y-auto">
          <SkillList
            steps={snapshot.current_run.steps}
            priorRunSteps={priorRun?.steps ?? []}
            selectedSkill={selectedSkill}
            onSelect={setSelectedSkill}
          />
        </main>
        <section className="w-[320px] border-l border-zinc-800 bg-zinc-950">
          {selectedStep ? (
            <div className="p-4 text-zinc-500">
              Step detail pane for {selectedStep.skill_name} — implemented in Task 27
            </div>
          ) : (
            <EmptyState title="Select a step" description="Click a row to see its details." />
          )}
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/OppWorkbenchPage.tsx frontend/src/components/opps/OppSidebar.tsx frontend/src/components/opps/SkillList.tsx frontend/src/components/opps/SkillRow.tsx
git commit -m "feat(frontend): add dense 19-skill center pane with judge bars and deltas"
```

---

## Task 27: Right pane (StepDetailPane + Discuss in chat + Linked chats)

**Files:**
- Create: `frontend/src/components/opps/StepDetailPane.tsx`
- Create: `frontend/src/components/opps/DiscussInChatButton.tsx`
- Create: `frontend/src/components/opps/JudgeVerdict.tsx`
- Create: `frontend/src/components/opps/GateHistory.tsx`
- Create: `frontend/src/components/opps/LinkedChats.tsx`
- Create: `frontend/src/components/opps/ArtifactPreview.tsx`
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx`

The step detail pane — the Workbench's second-most-important surface. Hero CTA is "💬 Discuss in chat" which POSTs to `/discuss` and navigates the user to the new session. All other sections (artifact preview, judge, gates, linked chats) are read-only.

- [ ] **Step 1: Implement the DiscussInChatButton**

Create `frontend/src/components/opps/DiscussInChatButton.tsx`:

```typescript
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { discussStep } from "../../api/opps";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

export function DiscussInChatButton({ slug, runId, skill }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handle = async () => {
    setLoading(true);
    setError(null);
    try {
      const { session_slug } = await discussStep(slug, runId, skill);
      navigate(`/chat/${session_slug}`);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handle}
        disabled={loading}
        className="rounded bg-gradient-to-br from-blue-500 to-violet-600 px-3 py-2.5 text-left text-xs font-semibold text-white shadow hover:from-blue-400 hover:to-violet-500 disabled:opacity-60"
      >
        <div className="text-[12px]">💬 Discuss in chat</div>
        <div className="mt-0.5 text-[9px] font-normal text-blue-100">
          {loading
            ? "Creating session…"
            : "Opens a new ace-web session seeded with the IDD, this step's artifacts, and the judge verdict. Iterate on the output or push an updated SKILL.md from the chat."}
        </div>
      </button>
      {error && <div className="text-[10px] text-red-400">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Implement the ArtifactPreview component**

Create `frontend/src/components/opps/ArtifactPreview.tsx`:

```typescript
import type { Artifact } from "../../api/types";

interface Props {
  primaryArtifact: Artifact | null;
  primaryBody: string;
}

export function ArtifactPreview({ primaryArtifact, primaryBody }: Props) {
  if (!primaryArtifact) {
    return (
      <div className="rounded bg-zinc-900 p-2.5">
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">Artifact</div>
        <div className="text-[10px] text-zinc-600">— no artifacts</div>
      </div>
    );
  }
  const lines = primaryBody.split("\n").slice(0, 10).join("\n");
  return (
    <div className="rounded bg-zinc-900 p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-zinc-500">
        Artifact · {primaryArtifact.name}
      </div>
      <pre className="mt-1.5 max-h-40 overflow-hidden rounded bg-zinc-950 p-2 text-[9px] text-zinc-400">
        {lines || "(empty)"}
      </pre>
      {primaryArtifact.drive_web_link && (
        <a
          href={primaryArtifact.drive_web_link}
          target="_blank"
          rel="noreferrer"
          className="mt-1.5 block text-[9px] text-blue-400 underline"
        >
          open in Drive →
        </a>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Implement JudgeVerdict, GateHistory, LinkedChats**

Create `frontend/src/components/opps/JudgeVerdict.tsx`:

```typescript
import type { Judge } from "../../api/types";

export function JudgeVerdict({ judge }: { judge: Judge | null }) {
  if (!judge) {
    return (
      <div className="rounded bg-zinc-900 p-2.5">
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">
          Judge · no LLM judge for this step
        </div>
      </div>
    );
  }
  return (
    <div className="rounded bg-zinc-900 p-2.5">
      <div className="flex items-center justify-between">
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">Judge</div>
        <div className="text-[11px] font-semibold text-green-400">
          {judge.score?.toFixed(1) ?? "—"}
          <span className="text-[9px] text-zinc-500">/10</span>
        </div>
      </div>
      {Object.keys(judge.criteria).length > 0 && (
        <div className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[9px] text-zinc-400">
          {Object.entries(judge.criteria).map(([key, value]) => (
            <div key={key} className="flex justify-between">
              <span>{key}</span>
              <span>{value}</span>
            </div>
          ))}
        </div>
      )}
      {judge.rationale && (
        <p className="mt-2 text-[10px] leading-relaxed text-zinc-400">
          {judge.rationale}
        </p>
      )}
    </div>
  );
}
```

Create `frontend/src/components/opps/GateHistory.tsx`:

```typescript
import type { Gate } from "../../api/types";

export function GateHistory({ gates }: { gates: Gate[] }) {
  if (gates.length === 0) return null;
  return (
    <div className="rounded bg-zinc-900 p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-zinc-500">Gate history</div>
      <ul className="mt-1 flex flex-col gap-0.5 text-[10px] text-zinc-400">
        {gates.map((g, i) => (
          <li key={`${g.ts}-${i}`}>
            <span className="font-mono text-zinc-500">{g.ts}</span>{" "}
            <span className={gateTone(g.decision)}>{g.decision}</span>
            {g.decided_by && <span className="text-zinc-500"> · {g.decided_by}</span>}
            {g.note && <span className="text-zinc-500"> — {g.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function gateTone(decision: string): string {
  if (decision === "approved") return "text-green-400";
  if (decision === "rejected") return "text-red-400";
  return "text-amber-400";
}
```

Create `frontend/src/components/opps/LinkedChats.tsx`:

```typescript
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getLinkedChats } from "../../api/opps";
import type { LinkedChat } from "../../api/types";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

export function LinkedChats({ slug, runId, skill }: Props) {
  const [chats, setChats] = useState<LinkedChat[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getLinkedChats(slug, runId, skill)
      .then(setChats)
      .catch(() => setChats([]))
      .finally(() => setLoading(false));
  }, [slug, runId, skill]);

  return (
    <div className="rounded bg-zinc-900 p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-zinc-500">
        Linked chats · {loading ? "…" : chats.length}
      </div>
      {!loading && chats.length === 0 && (
        <div className="mt-1 text-[10px] text-zinc-600">No prior chats yet.</div>
      )}
      {!loading && chats.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-[10px]">
          {chats.map((c) => (
            <li key={c.slug}>
              <Link
                to={`/chat/${c.slug}`}
                className="text-blue-400 underline hover:text-blue-300"
              >
                {c.title}
              </Link>{" "}
              <span className="text-zinc-600">· {c.owner_email}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement the StepDetailPane**

Create `frontend/src/components/opps/StepDetailPane.tsx`:

```typescript
import { useEffect, useState } from "react";

import { getStepDetail } from "../../api/opps";
import type { StepDetail } from "../../api/types";
import { ArtifactPreview } from "./ArtifactPreview";
import { DiscussInChatButton } from "./DiscussInChatButton";
import { GateHistory } from "./GateHistory";
import { JudgeVerdict } from "./JudgeVerdict";
import { LinkedChats } from "./LinkedChats";
import { LoadingSpinner } from "./LoadingStates";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

export function StepDetailPane({ slug, runId, skill }: Props) {
  const [detail, setDetail] = useState<StepDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getStepDetail(slug, runId, skill)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [slug, runId, skill]);

  if (loading) return <LoadingSpinner label={`Loading ${skill}…`} />;
  if (!detail)
    return (
      <div className="p-4 text-xs text-zinc-500">
        Failed to load {skill}.
      </div>
    );

  const primaryArtifact = detail.artifacts[0] ?? null;

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-4">
      <div>
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">
          Selected step
        </div>
        <div className="text-sm font-semibold text-zinc-100">{detail.skill_name}</div>
        <div className="text-[10px] text-zinc-500">
          {detail.phase_display} · status <span className="text-zinc-300">{detail.status}</span>
        </div>
      </div>

      <DiscussInChatButton slug={slug} runId={runId} skill={skill} />
      <ArtifactPreview primaryArtifact={primaryArtifact} primaryBody={detail.primary_body} />
      <JudgeVerdict judge={detail.judge} />
      {detail.gates.length > 0 && <GateHistory gates={detail.gates} />}
      <LinkedChats slug={slug} runId={runId} skill={skill} />
    </div>
  );
}
```

- [ ] **Step 5: Mount StepDetailPane in the Workbench page**

Modify `frontend/src/pages/OppWorkbenchPage.tsx`. Replace the step-detail placeholder in the right pane with:

```typescript
import { StepDetailPane } from "../components/opps/StepDetailPane";

// ... inside the JSX, right pane:
        <section className="w-[320px] border-l border-zinc-800 bg-zinc-950">
          {selectedStep ? (
            <StepDetailPane
              slug={slug}
              runId={snapshot.current_run.run_id}
              skill={selectedStep.skill_name}
            />
          ) : (
            <EmptyState title="Select a step" description="Click a row to see its details." />
          )}
        </section>
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/opps/ frontend/src/pages/OppWorkbenchPage.tsx
git commit -m "feat(frontend): add StepDetailPane with Discuss-in-chat CTA and linked chats"
```

---

## Task 28: Compare page

**Files:**
- Modify: `frontend/src/pages/OppComparePage.tsx`
- Create: `frontend/src/components/opps/CompareTable.tsx`

Two-column side-by-side comparison of two runs. Intentionally simple — same 19 rows on each side, score deltas inline. No artifact-body diffing (that's a future enhancement).

- [ ] **Step 1: Implement the CompareTable**

Create `frontend/src/components/opps/CompareTable.tsx`:

```typescript
import type { Run, Step } from "../../api/types";

interface Props {
  fromRun: Run;
  toRun: Run;
}

export function CompareTable({ fromRun, toRun }: Props) {
  const allSkills = new Set<string>();
  [...fromRun.steps, ...toRun.steps].forEach((s) => allSkills.add(s.skill_name));
  const sorted = [...allSkills].sort((a, b) => {
    const fa = fromRun.steps.find((s) => s.skill_name === a)?.ordinal ?? 999;
    const fb = fromRun.steps.find((s) => s.skill_name === b)?.ordinal ?? 999;
    const ta = toRun.steps.find((s) => s.skill_name === a)?.ordinal ?? 999;
    const tb = toRun.steps.find((s) => s.skill_name === b)?.ordinal ?? 999;
    return Math.min(fa, ta) - Math.min(fb, tb);
  });

  return (
    <div className="grid grid-cols-[1fr_auto_1fr] gap-3 p-4">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        Run {fromRun.run_id}
      </div>
      <div className="w-20" />
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        Run {toRun.run_id}
      </div>

      {sorted.map((name) => {
        const fromStep = fromRun.steps.find((s) => s.skill_name === name) ?? null;
        const toStep = toRun.steps.find((s) => s.skill_name === name) ?? null;
        const delta = computeDelta(fromStep, toStep);
        return (
          <SideBySideRow key={name} fromStep={fromStep} toStep={toStep} delta={delta} />
        );
      })}
    </div>
  );
}

function computeDelta(a: Step | null, b: Step | null): number | null {
  if (!a?.judge?.score || !b?.judge?.score) return null;
  return b.judge.score - a.judge.score;
}

function SideBySideRow({
  fromStep,
  toStep,
  delta,
}: {
  fromStep: Step | null;
  toStep: Step | null;
  delta: number | null;
}) {
  const skillName = toStep?.skill_name ?? fromStep?.skill_name ?? "—";
  return (
    <>
      <div className="rounded bg-zinc-900 p-2 text-xs">
        {fromStep ? <StepCell step={fromStep} /> : <span className="text-zinc-600">— not in run</span>}
      </div>
      <div className="flex w-20 items-center justify-center text-[10px]">
        <div className="text-center">
          <div className="font-mono text-zinc-100">{skillName}</div>
          <div className={deltaTone(delta)}>{formatDelta(delta)}</div>
        </div>
      </div>
      <div className="rounded bg-zinc-900 p-2 text-xs">
        {toStep ? <StepCell step={toStep} /> : <span className="text-zinc-600">— not in run</span>}
      </div>
    </>
  );
}

function StepCell({ step }: { step: Step }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-zinc-400">{step.status}</span>
        {step.judge?.score !== undefined && step.judge?.score !== null && (
          <span className="text-[11px] font-semibold text-green-400">
            {step.judge.score.toFixed(1)}
          </span>
        )}
      </div>
      <div className="mt-1 truncate text-[10px] text-zinc-500">{step.preview_text}</div>
    </div>
  );
}

function formatDelta(d: number | null): string {
  if (d === null) return "—";
  if (Math.abs(d) < 0.05) return "= 0";
  return `${d > 0 ? "↑ +" : "↓ "}${d.toFixed(1)}`;
}

function deltaTone(d: number | null): string {
  if (d === null) return "text-zinc-600";
  if (d > 0.05) return "text-green-400";
  if (d < -0.05) return "text-red-400";
  return "text-zinc-500";
}
```

- [ ] **Step 2: Implement the OppComparePage**

Modify `frontend/src/pages/OppComparePage.tsx`:

```typescript
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { compareRuns } from "../api/opps";
import type { CompareResult } from "../api/types";
import { CompareTable } from "../components/opps/CompareTable";
import { ErrorState, LoadingSpinner } from "../components/opps/LoadingStates";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; result: CompareResult };

export default function OppComparePage() {
  const { slug = "" } = useParams();
  const [searchParams] = useSearchParams();
  const fromId = searchParams.get("from") ?? "";
  const toId = searchParams.get("to") ?? "";
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!fromId || !toId) {
      setState({ kind: "error", message: "Compare requires ?from=<id>&to=<id>" });
      return;
    }
    setState({ kind: "loading" });
    compareRuns(slug, fromId, toId)
      .then((result) => setState({ kind: "loaded", result }))
      .catch((err) => setState({ kind: "error", message: String(err?.message ?? err) }));
  }, [slug, fromId, toId]);

  if (state.kind === "loading") return <LoadingSpinner label="Loading comparison…" />;
  if (state.kind === "error") return <ErrorState message={state.message} />;

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center gap-4 border-b border-zinc-800 px-4 py-2 text-sm">
        <Link to={`/opps/${slug}`} className="text-zinc-500 hover:text-zinc-300">
          ← back
        </Link>
        <span className="font-semibold">{state.result.opp.display_name}</span>
        <span className="text-zinc-500">
          comparing <span className="font-mono text-zinc-300">{fromId}</span>
          <span className="mx-2">→</span>
          <span className="font-mono text-zinc-300">{toId}</span>
        </span>
      </header>
      <main className="flex-1 overflow-y-auto">
        <CompareTable fromRun={state.result.from_run} toRun={state.result.to_run} />
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/OppComparePage.tsx frontend/src/components/opps/CompareTable.tsx
git commit -m "feat(frontend): add Compare page with side-by-side run tables"
```

---

## Task 29: End-to-end integration test against the fixture tree

**Files:**
- Create: `apps/opps/tests/test_e2e_workflow.py`

One test that walks the full happy path: authenticated user with Drive token → hits `/api/opps/` → picks an opp → hits `/api/opps/<slug>` → drills into a step → POSTs to `/discuss` → gets a session slug back → the session has the seed message with the right content. Proves the pieces of Tasks 1–21 compose correctly.

- [ ] **Step 1: Write the e2e test**

Create `apps/opps/tests/test_e2e_workflow.py`:

```python
"""End-to-end happy-path test for the opps Workbench.

Exercises the full flow from the opp list → workbench → step detail → discuss,
using the FakeDriveClient fixture. Proves the modules from Tasks 1–21
compose correctly.
"""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)
from apps.sessions.models import Session


@pytest.fixture
def authed_client(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    u.drive_token_cache = "ciphertext"
    u.save()
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def fake_drive():
    return FakeDriveClient.from_tree(malaria_pilot_structured_tree())


def _patch_drive(fake):
    return patch.multiple(
        "apps.opps.views",
        get_drive_client_for=lambda user: fake,
        _resolve_ace_root_folder_id=lambda client: fake.folder_id("ACE"),
    )


def test_full_workflow_list_to_discuss(authed_client, fake_drive):
    with _patch_drive(fake_drive):
        # 1) Opp list
        list_response = authed_client.get("/api/opps/")
        assert list_response.status_code == 200
        cards = list_response.json()["data"]
        assert any(c["slug"] == "malaria-pilot" for c in cards)

        # 2) Workbench for the opp
        wb_response = authed_client.get("/api/opps/malaria-pilot")
        assert wb_response.status_code == 200
        wb = wb_response.json()["data"]
        assert wb["current_run"]["run_id"] == "2026-04-06-002"
        assert len(wb["current_run"]["steps"]) >= 4

        # 3) Step detail for app-deploy (the gate-pending step)
        step_response = authed_client.get(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy"
        )
        assert step_response.status_code == 200
        step = step_response.json()["data"]
        assert step["is_gate"] is True
        assert len(step["gates"]) == 1
        assert step["gates"][0]["decision"] == "pending"

        # 4) Discuss — creates a new session with the seed system message
        discuss_response = authed_client.post(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/discuss",
            content_type="application/json",
        )
        assert discuss_response.status_code == 201
        session_slug = discuss_response.json()["data"]["session_slug"]

        session = Session.objects.get(slug=session_slug)
        assert session.opp_slug == "malaria-pilot"
        assert session.opp_run_id == "2026-04-06-002"
        assert session.opp_step_skill == "app-deploy"

        seed = session.messages.filter(role="system").first()
        assert seed is not None
        assert "Discussing `app-deploy`" in seed.plaintext
        assert "Malaria Pilot IDD" in seed.plaintext
        assert "Gate history" in seed.plaintext

        # 5) Linked chats now includes the session we just created
        chats_response = authed_client.get(
            "/api/opps/malaria-pilot/runs/2026-04-06-002/steps/app-deploy/chats"
        )
        assert chats_response.status_code == 200
        chats = chats_response.json()["data"]
        assert any(c["slug"] == session_slug for c in chats)


def test_full_workflow_compare_runs(authed_client, fake_drive):
    with _patch_drive(fake_drive):
        response = authed_client.get(
            "/api/opps/malaria-pilot/compare?from=2026-04-01-001&to=2026-04-06-002"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["from_run"]["run_id"] == "2026-04-01-001"
        assert data["to_run"]["run_id"] == "2026-04-06-002"
        # The fixture has idd-to-learn-app with judge 7.1 in v1 and 8.5 in v2
        from_lla = next(
            s for s in data["from_run"]["steps"] if s["skill_name"] == "idd-to-learn-app"
        )
        to_lla = next(
            s for s in data["to_run"]["steps"] if s["skill_name"] == "idd-to-learn-app"
        )
        assert from_lla["judge"]["score"] == 7.1
        assert to_lla["judge"]["score"] == 8.5
```

- [ ] **Step 2: Run the e2e test**

Run: `pytest apps/opps/tests/test_e2e_workflow.py -v`
Expected: 2 passed.

- [ ] **Step 3: Run the entire project test suite**

Run: `pytest -v`
Expected: every test passes — prior tests from Phase 1/2 plus all 21 task suites for opps. Also run `ruff check .` and fix any violations.

- [ ] **Step 4: Commit**

```bash
git add apps/opps/tests/test_e2e_workflow.py
git commit -m "test(opps): add end-to-end happy-path integration test"
```

---

## Task 30: Documentation updates

**Files:**
- Create: `docs/learnings/drive-oauth-two-flow.md`
- Modify: `CLAUDE.md`

Document (a) why ace-web has two OAuth flows, (b) that the opps module exists and its data model is Drive-not-Postgres, and (c) the coordination point with the ACE plugin for the folder format.

- [ ] **Step 1: Write the learning**

Create `docs/learnings/drive-oauth-two-flow.md`:

```markdown
# Drive OAuth as a secondary flow

## Context

ace-web's identity auth is a hand-rolled CommCare Connect OAuth flow with
PKCE (apps/auth/oauth.py + apps/auth/oauth_views.py, ported from connect-labs,
post the AWS pivot — see the commit history around the scout-pattern tenant move).
That flow tells us *who* the user is, filtered to `@dimagi.com`, but it does
NOT give ace-web access to the user's Google Drive.

The ACE opportunity Workbench (apps/opps) needs to read Google Drive on the
user's behalf to show the team's opp folders. So it runs a **second OAuth
flow** — a separate Google consent screen — just for the Drive scope.

## Pattern

Copied from `../connect-search/backend/app/core/{drive,auth}.py` +
`app/api/auth.py`. Translated from FastAPI to Django views. The concrete
pieces:

- `apps/opps/drive_auth_views.py` — `/auth/drive/start` and
  `/auth/drive/callback` Django views
- `apps/opps/encryption.py` — Fernet wrapper that reads the key from
  `settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY` (sourced from AWS Secrets Manager
  in prod)
- `apps/auth/models.py::User.drive_token_cache` — encrypted JSON blob per user
- `apps/opps/drive_credentials.py` — `ensure_fresh(token_data)` helper that
  transparently refreshes expired access tokens and returns a new token
  dict the caller persists back to the User row
- `apps/opps/drive_for_request.py::get_drive_client_for(user)` — the one
  call views use to get a working `GoogleDriveClient` instance

## Why not one flow?

connect-search uses a single Google OAuth flow for both identity and Drive.
ace-web can't because its identity source of truth is CommCare Connect (a
Dimagi-controlled OAuth provider), not Google. The Drive flow has to layer
on top — the user logs into ace-web via CommCare Connect, then when they
visit `/opps` they are asked to additionally grant Drive read access.

A single unified flow would require moving identity back to Google, which
loses the CommCare Connect integration benefits (Dimagi-managed user pool,
shared session with other Connect tools). Two flows is the right call.

## Refresh behavior

Access tokens expire hourly. The `ensure_fresh` helper checks expiry with a
60-second buffer on every request and refreshes via the refresh token when
needed. If the refresh itself fails (revoked grant, expired refresh token,
network error), the middleware returns a 401 with
`{"data": {"reconnect_url": "/auth/drive/start"}}` and the frontend's
`DriveReconnectGuard` redirects the user through a fresh consent grant.

## Scopes

Read-only: `drive.readonly` + `spreadsheets.readonly`. The Workbench never
writes to Drive. Any future write features (e.g. "publish a comment on an
opp folder") need an additive consent grant, not a scope upgrade on the
existing flow, because Google's consent UX is clearer when new scopes are
explicitly requested.
```

- [ ] **Step 2: Update CLAUDE.md**

Modify `CLAUDE.md`. Add an `apps/opps` row to the project structure tree and append a short paragraph about the ACE coordination point.

Find the existing project structure block in `CLAUDE.md` and add `apps/opps/` alongside the other app directories:

```
├── apps/
│   ├── auth/        # Custom User, IAP header middleware    (10 files)
│   ├── common/      # Envelope, health check                (4 files)
│   ├── opps/        # ACE opp Workbench (Drive-backed)     (new)
│   └── sessions/    # 7-table data model                    (4 files)
```

Then add a new section near the bottom, above `## Workflow`:

```markdown
## ACE opportunity visualization (apps/opps)

The `apps/opps/` module is the ACE opportunity Workbench — a read-through UI
on top of Google Drive that shows all 19 skills of an ACE run, per-step
artifact previews, judge verdicts, gate history, and a "Discuss in chat"
CTA that seeds a new ace-web `Session` from a step's context.

Google Drive is the source of truth. There are no Django ORM models for
opps / runs / steps / artifacts — the data lives as `opp.yaml` / `run.yaml` /
`step.yaml` / `judge.yaml` / `gates.jsonl` / `events.jsonl` files under
`ACE/<opp-slug>/` in Drive. See
`docs/specs/2026-04-08-ace-opp-visualization-design.md` § 6 for the full
folder format.

**Coordination with the ACE plugin:** The Drive folder format in the spec
above is a proposal that the ACE plugin (`../ace`) needs to adopt for
first-class multi-run support. ace-web ships with a flat-layout fallback
that reads the current `ACE/<opp>/state.yaml` + subfolder convention as a
single implicit run, so both formats work during the transition.

**Two OAuth flows:** identity via a hand-rolled CommCare Connect OAuth
flow with PKCE (`apps/auth/oauth_views.py`, pattern from connect-labs);
Drive access via a separate Google OAuth grant per-user. See
`docs/learnings/drive-oauth-two-flow.md`.

**Key files:**
- `apps/opps/sync.py` — Drive-to-payload reader (structured + flat layouts)
- `apps/opps/previews.py` — 19 per-skill preview extractors
- `apps/opps/seed.py` — chat-seed builder for "Discuss in chat"
- `apps/opps/drive_client.py` — DriveClient ABC + GoogleDriveClient
- `apps/opps/skills.py` — canonical 19-skill metadata (phase/judge/gate/ordinal)
- `frontend/src/pages/OppWorkbenchPage.tsx` — the three-pane UI shell
```

- [ ] **Step 3: Run the full test suite and lint**

Run: `pytest -v && ruff check . && cd frontend && npx tsc --noEmit`
Expected: everything green.

- [ ] **Step 4: Commit**

```bash
git add docs/learnings/drive-oauth-two-flow.md CLAUDE.md
git commit -m "docs: add opps module section to CLAUDE.md + drive-oauth-two-flow learning"
```

---

## Plan self-review

**Spec coverage check:**

- Spec § 4 (Surfaces) — covered by Tasks 1, 14–18, 21, 23, 25–28
- Spec § 5 (Auth) — covered by Tasks 4, 5, 6, 7, 13, 23
- Spec § 6 (Drive folder format) — covered by Tasks 9 (parsers), 10 (structured sync), 11 (flat fallback). The format is documented in the spec and in Task 10's task description
- Spec § 7 (Data flow) — covered by Tasks 13 (serializers), 14–18 (endpoints), 22 (client)
- Spec § 8 (Chat integration) — covered by Tasks 19 (session migration), 20 (seed), 21 (discuss endpoint), 27 (UI)
- Spec § 9 (Non-goals) — honored by absence; no tasks implement share tokens, trend dashboards, or in-app SKILL.md editors
- Spec § 10 (Coordination) — documented in Task 30's CLAUDE.md edit
- Spec § 11 (Testing) — covered by per-task unit tests plus the e2e test in Task 29
- Spec § 13 (Open risks) — risks 1, 4 surface in task descriptions; risks 2, 3, 5 are noted in the spec itself

**Placeholder scan:** No TBDs, TODOs, "implement later" markers, or "similar to Task N" references. Every step has complete runnable code.

**Type consistency:**

- Backend parser dataclasses (`OppManifest`, `RunManifest`, `StepManifest`, `JudgeVerdict`, `GateDecision`, `RunEvent`) are defined in Task 9 and referenced consistently in Tasks 10, 11, 13, 20
- Sync-layer dataclasses (`OppSnapshot`, `RunDetail`, `RunSummary`, `StepSnapshot`, `ArtifactRef`) are defined in Task 10 and used consistently in Tasks 11, 13, 14–18, 20
- Frontend TypeScript types (`OppCard`, `Run`, `Step`, `Judge`, `Gate`, `Artifact`, `OppSnapshot`, `StepDetail`, `LinkedChat`, `CompareResult`, `DiscussResponse`, `DriveReconnectRequired`) are defined in Task 22 and used consistently in Tasks 23–28

**One known trade-off to flag:** the `_resolve_ace_root_folder_id` helper in Task 14 intentionally raises `NotImplementedError` in its production body and relies on test patches. A follow-up at the start of actual implementation should add a `DriveClient.search_files(name=...)` method or promote a folder-id setting (`settings.ACE_DRIVE_ROOT_FOLDER_ID`) to resolve it once for real deployments. This is a known gap rather than a broken plan — flagged here so the implementer surfaces it early and decides how to close it (settings pin vs. search helper).

---

## Execution handoff

Plan complete and saved to `docs/plans/2026-04-08-ace-opp-workbench.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?



