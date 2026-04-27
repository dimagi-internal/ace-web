# Multi-Tenant Workspaces — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the multi-tenancy substrate to ace-web — `Workspace`, `WorkspaceMembership`, `WorkspaceInvite` models with membership-gated reads on every existing opp/session/upload endpoint, the `@dimagi.com` filter dropped, and existing data migrated into a single seeded `dimagi-team` workspace. After Phase A, the product behaves identically for the founding user, but the plumbing for third-party self-onboarding is in place.

**Architecture:** New `apps/workspaces/` Django app with three tables. Existing models (`OppWorkspace`, `Session`, `ShareToken`, `IngestUpload`) gain a nullable `workspace` FK that's populated by a one-shot data migration. URL structure pivots to `/w/<slug>/...` on the frontend with redirects from legacy paths. Read endpoints scope by `request.user`'s workspace memberships. CLI `/ace:run --ace-web-url` upload contract gets one new field (`ace_root_folder_id`); the plugin counterpart change is documented but lives in the sibling `../ace` repo.

**Tech Stack:** Django 5, DRF, Postgres (migrations + data backfill), pytest + pytest-django for tests, React 19 + react-router 6 for frontend routing changes.

**Spec reference:** `docs/specs/2026-04-27-multi-tenant-workspaces-design.md`

---

## File Structure

**New backend files:**
- `apps/workspaces/__init__.py` — empty marker
- `apps/workspaces/apps.py` — `WorkspacesConfig` (label `ace_workspaces`)
- `apps/workspaces/models.py` — `Workspace`, `WorkspaceMembership`, `WorkspaceInvite`
- `apps/workspaces/admin.py` — Django admin registrations
- `apps/workspaces/permissions.py` — `is_member`, `role_for`, decorators
- `apps/workspaces/serializers.py` — DRF serializers for the API
- `apps/workspaces/views.py` — REST endpoints
- `apps/workspaces/urls.py` — URL routes
- `apps/workspaces/migrations/0001_initial.py` — schema for the three tables
- `apps/workspaces/migrations/0002_seed_dimagi_team.py` — data migration: seed workspace + backfill FKs
- `apps/workspaces/tests/__init__.py` — package marker
- `apps/workspaces/tests/test_models.py` — model invariants
- `apps/workspaces/tests/test_permissions.py` — role + membership checks
- `apps/workspaces/tests/test_views.py` — API surface
- `apps/workspaces/tests/test_seed_migration.py` — migration backfill correctness

**New frontend files:**
- `frontend/src/api/workspaces.ts` — fetch helpers
- `frontend/src/components/WorkspaceSwitcher.tsx` — top-nav dropdown
- `frontend/src/hooks/useWorkspace.ts` — current workspace from URL + membership context
- `frontend/src/pages/WelcomePage.tsx` — stub for users with zero memberships (full content in Phase B)
- `frontend/src/pages/NoWorkspaceRedirect.tsx` — redirect helper from legacy `/opps` etc. to `/w/<slug>/opps`

**Modified backend files:**
- `config/settings/base.py` — add `apps.workspaces.apps.WorkspacesConfig` to `INSTALLED_APPS`; set `ACE_ALLOWED_EMAIL_DOMAINS = []` to disable the filter (kept for backward-compat); annotate `ACE_DRIVE_ROOT_FOLDER_ID` as a migration-only seed value
- `config/urls.py` — wire `apps.workspaces.urls`
- `apps/auth/oauth_views.py:213-220` — bypass domain check when `ACE_ALLOWED_EMAIL_DOMAINS` is empty; redirect new users with zero memberships to `/welcome`
- `apps/opps/models.py` — `OppWorkspace` gets `workspace` FK; PK switches from `slug` to a synthetic `id`; `unique_together = [("workspace", "slug")]`
- `apps/opps/migrations/00XX_workspace_fk.py` — new migration for the schema change
- `apps/opps/views.py` — `_require_drive` now resolves workspace from URL/header, scopes reads by membership
- `apps/opps/opp_creator.py:54` — slug uniqueness check is per-workspace
- `apps/opps/drive_client.py:239-251` — `get_drive_client` accepts a workspace and uses its folder ID; falls back to `ACE_DRIVE_ROOT_FOLDER_ID` only during migration
- `apps/sessions/models.py` — `Session`, `ShareToken`, `IngestUpload` gain `workspace` FK
- `apps/sessions/migrations/00XX_workspace_fk.py` — schema migration
- `apps/sessions/views.py` — workspace-scoped reads
- `apps/ingest/views.py` — accept `ace_root_folder_id` field, resolve workspace, validate membership

**Modified frontend files:**
- `frontend/src/router.tsx` — pivot all opp/session/chat routes under `/w/:workspaceSlug/`; add legacy redirects
- `frontend/src/App.tsx` — render `WorkspaceSwitcher` in the top nav
- `frontend/src/pages/OppListPage.tsx` — read workspace slug from URL params; pass to `listOpps`
- `frontend/src/pages/OppWorkbenchPage.tsx` — same
- `frontend/src/pages/SessionsPage.tsx` — same
- `frontend/src/pages/ChatPage.tsx` — same
- `frontend/src/api/opps.ts` — every call sends `X-ACE-Workspace` header
- `frontend/src/api/sessions.ts` — same

**Cross-repo (documented, executed against `../ace`):**
- `../ace/skills/upload-transcript/SKILL.md` (or wherever the skill lives) — add `ace_root_folder_id` field to multipart upload payload

---

## Test Strategy

This plan uses TDD: tests come before implementation for each task that has testable behavior. Run `pytest -v` from repo root for the backend, `bun run test` (if configured) or manual browser checks for frontend changes. The full backend suite runs in-memory SQLite (per `pytest.ini`) so it's fast.

For the data migration in Task 11, the test uses pytest-django's `migrator` fixture to run the migration against a populated DB and assert backfill correctness.

---

## Task 1: Scaffold the `apps/workspaces/` app

**Files:**
- Create: `apps/workspaces/__init__.py`
- Create: `apps/workspaces/apps.py`
- Create: `apps/workspaces/tests/__init__.py`
- Modify: `config/settings/base.py:37-54` (add to `INSTALLED_APPS`)

- [ ] **Step 1: Create the empty package markers**

```bash
mkdir -p apps/workspaces/tests apps/workspaces/migrations
touch apps/workspaces/__init__.py apps/workspaces/tests/__init__.py apps/workspaces/migrations/__init__.py
```

- [ ] **Step 2: Write the AppConfig**

`apps/workspaces/apps.py`:
```python
from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workspaces"
    label = "ace_workspaces"
```

The `label` is `ace_workspaces` (not the default `workspaces`) to mirror the pattern used by `apps.auth.apps.AuthConfig` (label `ace_auth`) and avoid collisions with any future `django.contrib.workspaces` style app.

- [ ] **Step 3: Add to `INSTALLED_APPS`**

In `config/settings/base.py`, in the `INSTALLED_APPS` list, after the `apps.system.apps.SystemConfig` line, add:
```python
    "apps.workspaces.apps.WorkspacesConfig",
```

- [ ] **Step 4: Verify Django can load the app**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add apps/workspaces/ config/settings/base.py
git commit -m "feat(workspaces): scaffold apps/workspaces/ app"
```

---

## Task 2: Define the `Workspace` model

**Files:**
- Create: `apps/workspaces/models.py`
- Create: `apps/workspaces/tests/test_models.py`

- [ ] **Step 1: Write the failing test for `Workspace` basics**

`apps/workspaces/tests/test_models.py`:
```python
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from apps.workspaces.models import Workspace

User = get_user_model()


@pytest.mark.django_db
def test_workspace_creation_minimal():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme",
        display_name="Acme Co",
        drive_root_folder_id="folder-1",
        created_by=user,
    )
    assert ws.slug == "acme"
    assert ws.created_by == user
    assert ws.settings == {}


@pytest.mark.django_db
def test_workspace_drive_root_folder_id_is_unique():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    with pytest.raises(IntegrityError):
        Workspace.objects.create(
            slug="acme-2", display_name="Acme 2",
            drive_root_folder_id="folder-1", created_by=user,
        )


@pytest.mark.django_db
def test_workspace_str():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme Co",
        drive_root_folder_id="folder-1", created_by=user,
    )
    assert str(ws) == "Acme Co (acme)"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/workspaces/tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Workspace'`

- [ ] **Step 3: Write the `Workspace` model**

`apps/workspaces/models.py`:
```python
"""ORM models for ACE Workspaces — the unit of multi-tenancy.

A Workspace owns a Google Drive folder (the `ace-drive` SA must be shared
on it as Editor) and a list of members with roles. All ACE opps live
under exactly one workspace.

See: docs/specs/2026-04-27-multi-tenant-workspaces-design.md
"""
from django.conf import settings
from django.db import models


class Workspace(models.Model):
    slug = models.CharField(primary_key=True, max_length=64)
    display_name = models.CharField(max_length=200)
    drive_root_folder_id = models.CharField(max_length=100, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workspaces_created",
    )
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspaces"
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        return f"{self.display_name} ({self.slug})"
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations workspaces`
Expected: `Migrations for 'ace_workspaces': apps/workspaces/migrations/0001_initial.py`

- [ ] **Step 5: Run the tests**

Run: `pytest apps/workspaces/tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/workspaces/models.py apps/workspaces/migrations/ apps/workspaces/tests/
git commit -m "feat(workspaces): add Workspace model"
```

---

## Task 3: Define `WorkspaceMembership`

**Files:**
- Modify: `apps/workspaces/models.py`
- Modify: `apps/workspaces/tests/test_models.py`

- [ ] **Step 1: Add failing tests for `WorkspaceMembership`**

Append to `apps/workspaces/tests/test_models.py`:
```python
from apps.workspaces.models import WorkspaceMembership


@pytest.mark.django_db
def test_membership_creation():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    m = WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    assert m.role == "owner"
    assert m.invited_by is None


@pytest.mark.django_db
def test_membership_unique_per_user_per_workspace():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    with pytest.raises(IntegrityError):
        WorkspaceMembership.objects.create(workspace=ws, user=user, role="editor")


@pytest.mark.django_db
def test_membership_role_choices():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    for role in ("owner", "editor", "viewer"):
        u = User.objects.create_user(email=f"{role}@example.com", username=role)
        m = WorkspaceMembership(workspace=ws, user=u, role=role)
        m.full_clean()  # raises if invalid choice
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/workspaces/tests/test_models.py -v -k membership`
Expected: FAIL — `ImportError: cannot import name 'WorkspaceMembership'`

- [ ] **Step 3: Add `WorkspaceMembership` to `models.py`**

Append to `apps/workspaces/models.py`:
```python
class WorkspaceMembership(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("editor", "Editor"),
        ("viewer", "Viewer"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_memberships"
        unique_together = [("workspace", "user")]
        indexes = [models.Index(fields=["user", "workspace"])]

    def __str__(self):
        return f"{self.user.email} = {self.role} on {self.workspace.slug}"
```

- [ ] **Step 4: Generate and apply the migration**

Run: `python manage.py makemigrations workspaces`

- [ ] **Step 5: Run the tests**

Run: `pytest apps/workspaces/tests/test_models.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/workspaces/
git commit -m "feat(workspaces): add WorkspaceMembership model"
```

---

## Task 4: Define `WorkspaceInvite`

**Files:**
- Modify: `apps/workspaces/models.py`
- Modify: `apps/workspaces/tests/test_models.py`

- [ ] **Step 1: Add failing tests for `WorkspaceInvite`**

Append to `apps/workspaces/tests/test_models.py`:
```python
from datetime import timedelta
from django.utils import timezone

from apps.workspaces.models import WorkspaceInvite


@pytest.mark.django_db
def test_invite_token_unique():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=user, expires_at=timezone.now() + timedelta(days=7),
    )
    assert len(inv.token) >= 32
    with pytest.raises(IntegrityError):
        WorkspaceInvite.objects.create(
            workspace=ws, email="charlie@example.com", role="editor",
            invited_by=user, expires_at=timezone.now() + timedelta(days=7),
            token=inv.token,
        )


@pytest.mark.django_db
def test_invite_is_pending():
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="acme", display_name="Acme",
        drive_root_folder_id="folder-1", created_by=user,
    )
    inv = WorkspaceInvite.objects.create(
        workspace=ws, email="bob@example.com", role="editor",
        invited_by=user, expires_at=timezone.now() + timedelta(days=7),
    )
    assert inv.is_pending() is True
    inv.accepted_at = timezone.now()
    assert inv.is_pending() is False
    inv2 = WorkspaceInvite.objects.create(
        workspace=ws, email="dora@example.com", role="editor",
        invited_by=user, expires_at=timezone.now() - timedelta(days=1),
    )
    assert inv2.is_pending() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/workspaces/tests/test_models.py -v -k invite`
Expected: FAIL — `ImportError: cannot import name 'WorkspaceInvite'`

- [ ] **Step 3: Implement `WorkspaceInvite`**

Append to `apps/workspaces/models.py`:
```python
import secrets


def generate_invite_token() -> str:
    """48-char URL-safe random token."""
    return secrets.token_urlsafe(36)[:48]


class WorkspaceInvite(models.Model):
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invites"
    )
    email = models.CharField(max_length=200)
    role = models.CharField(
        max_length=16, choices=WorkspaceMembership.ROLE_CHOICES, default="editor"
    )
    token = models.CharField(max_length=64, unique=True, default=generate_invite_token)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invites_sent",
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_invites"
        indexes = [
            models.Index(fields=["email", "-created_at"]),
            models.Index(fields=["workspace", "-created_at"]),
        ]

    def __str__(self):
        return f"Invite {self.email} to {self.workspace.slug} as {self.role}"

    def is_pending(self) -> bool:
        if self.accepted_at is not None or self.revoked_at is not None:
            return False
        from django.utils import timezone
        return self.expires_at > timezone.now()
```

- [ ] **Step 4: Generate and apply the migration**

Run: `python manage.py makemigrations workspaces`

- [ ] **Step 5: Run the tests**

Run: `pytest apps/workspaces/tests/test_models.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/workspaces/
git commit -m "feat(workspaces): add WorkspaceInvite model"
```

---

## Task 5: Permissions helpers

**Files:**
- Create: `apps/workspaces/permissions.py`
- Create: `apps/workspaces/tests/test_permissions.py`

- [ ] **Step 1: Write failing tests for the permission helpers**

`apps/workspaces/tests/test_permissions.py`:
```python
import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.workspaces.permissions import (
    is_member,
    role_for,
    require_role,
    user_workspaces,
)

User = get_user_model()


def make_user(email):
    return User.objects.create_user(email=email, username=email.split("@")[0])


def make_ws(slug, owner):
    return Workspace.objects.create(
        slug=slug, display_name=slug.title(),
        drive_root_folder_id=f"folder-{slug}", created_by=owner,
    )


@pytest.mark.django_db
def test_is_member_true_when_member():
    alice = make_user("alice@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    assert is_member(alice, ws) is True


@pytest.mark.django_db
def test_is_member_false_when_not_member():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    assert is_member(bob, ws) is False


@pytest.mark.django_db
def test_role_for_returns_role_or_none():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="editor")
    assert role_for(alice, ws) == "editor"
    assert role_for(bob, ws) is None


@pytest.mark.django_db
def test_user_workspaces_returns_only_member_workspaces():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws_a = make_ws("acme", alice)
    ws_b = make_ws("beta", alice)
    WorkspaceMembership.objects.create(workspace=ws_a, user=alice, role="owner")
    WorkspaceMembership.objects.create(workspace=ws_a, user=bob, role="viewer")
    WorkspaceMembership.objects.create(workspace=ws_b, user=alice, role="owner")
    slugs_for_bob = set(user_workspaces(bob).values_list("slug", flat=True))
    assert slugs_for_bob == {"acme"}


@pytest.mark.django_db
def test_require_role_passes_when_role_meets_minimum():
    alice = make_user("alice@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="editor")
    # Editor satisfies viewer requirement
    assert require_role(alice, ws, "viewer") is True
    # Editor satisfies editor
    assert require_role(alice, ws, "editor") is True
    # Editor does NOT satisfy owner
    assert require_role(alice, ws, "owner") is False


@pytest.mark.django_db
def test_require_role_false_for_non_member():
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    ws = make_ws("acme", alice)
    WorkspaceMembership.objects.create(workspace=ws, user=alice, role="owner")
    assert require_role(bob, ws, "viewer") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/workspaces/tests/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.workspaces.permissions`

- [ ] **Step 3: Implement permissions module**

`apps/workspaces/permissions.py`:
```python
"""Membership + role helpers for workspace-scoped views.

Roles form a hierarchy: viewer < editor < owner. `require_role(user, ws, "editor")`
returns True for editors AND owners.
"""
from __future__ import annotations

from django.db.models import QuerySet

from apps.workspaces.models import Workspace, WorkspaceMembership

ROLE_LEVELS = {"viewer": 0, "editor": 1, "owner": 2}


def is_member(user, workspace: Workspace) -> bool:
    if not user.is_authenticated:
        return False
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user
    ).exists()


def role_for(user, workspace: Workspace) -> str | None:
    if not user.is_authenticated:
        return None
    m = WorkspaceMembership.objects.filter(
        workspace=workspace, user=user
    ).only("role").first()
    return m.role if m else None


def require_role(user, workspace: Workspace, minimum: str) -> bool:
    """Return True iff user is a member of workspace with role >= minimum."""
    role = role_for(user, workspace)
    if role is None:
        return False
    return ROLE_LEVELS[role] >= ROLE_LEVELS[minimum]


def user_workspaces(user) -> QuerySet[Workspace]:
    """Workspaces the user is a member of, ordered by most-recent membership first."""
    if not user.is_authenticated:
        return Workspace.objects.none()
    return Workspace.objects.filter(memberships__user=user).order_by(
        "-memberships__joined_at"
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest apps/workspaces/tests/test_permissions.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/workspaces/permissions.py apps/workspaces/tests/test_permissions.py
git commit -m "feat(workspaces): membership + role helpers"
```

---

## Task 6: Add `workspace` FK to `OppWorkspace` (schema only, nullable)

**Files:**
- Modify: `apps/opps/models.py:14` — add `workspace` FK
- Create: new migration `apps/opps/migrations/00XX_add_workspace_fk.py`

This task only adds the FK as **nullable** so existing rows can survive the schema change. Task 11's data migration backfills it; Task 12 makes it non-nullable.

- [ ] **Step 1: Add the FK to the model**

In `apps/opps/models.py`, modify the `OppWorkspace` class to add (after the existing `tags` field, before the `created_at` field):
```python
    workspace = models.ForeignKey(
        "ace_workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="opps",
        null=True, blank=True,  # Temporarily nullable; backfilled by 0002_seed_dimagi_team
    )
```

- [ ] **Step 2: Generate the migration**

Run: `python manage.py makemigrations opps`
Expected: a new file `apps/opps/migrations/000X_oppworkspace_workspace.py`

- [ ] **Step 3: Apply the migration locally**

Run: `python manage.py migrate`
Expected: clean apply, no errors.

- [ ] **Step 4: Verify existing tests still pass**

Run: `pytest apps/opps/tests/ -v`
Expected: all passing (the FK is nullable; existing fixtures don't set it).

- [ ] **Step 5: Commit**

```bash
git add apps/opps/
git commit -m "feat(opps): add nullable workspace FK to OppWorkspace"
```

---

## Task 7: Add `workspace` FK to `Session`, `ShareToken`, `IngestUpload`

**Files:**
- Modify: `apps/sessions/models.py:26-50, 244-255, 260-277`
- Create: new migration in `apps/sessions/migrations/`

- [ ] **Step 1: Add FKs to all three models**

In `apps/sessions/models.py`:

For the `Session` class (after the `source` field, before any meta), add:
```python
    workspace = models.ForeignKey(
        "ace_workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sessions",
    )
```

For the `ShareToken` class (after the `revoked_at` field), add:
```python
    workspace = models.ForeignKey(
        "ace_workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="share_tokens",
    )
```

For the `IngestUpload` class (after `cli_session_id`), add:
```python
    workspace = models.ForeignKey(
        "ace_workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ingest_uploads",
    )
```

- [ ] **Step 2: Generate the migration**

Run: `python manage.py makemigrations sessions`

- [ ] **Step 3: Apply locally**

Run: `python manage.py migrate`

- [ ] **Step 4: Run existing sessions tests**

Run: `pytest apps/sessions/tests/ apps/ingest/tests/ -v`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add apps/sessions/
git commit -m "feat(sessions): add nullable workspace FK to Session/ShareToken/IngestUpload"
```

---

## Task 8: Workspace API serializers

**Files:**
- Create: `apps/workspaces/serializers.py`

- [ ] **Step 1: Write the serializers**

`apps/workspaces/serializers.py`:
```python
"""DRF serializers for the workspaces API."""
from rest_framework import serializers

from apps.workspaces.models import Workspace, WorkspaceMembership


class WorkspaceSummarySerializer(serializers.ModelSerializer):
    """List view: minimal fields for the switcher dropdown."""

    role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["slug", "display_name", "role", "created_at"]

    def get_role(self, obj):
        # The view annotates `_my_role` for performance; fall back to a query.
        if hasattr(obj, "_my_role"):
            return obj._my_role
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            from apps.workspaces.permissions import role_for
            return role_for(request.user, obj)
        return None


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_display_name = serializers.CharField(
        source="user.get_full_name", read_only=True
    )

    class Meta:
        model = WorkspaceMembership
        fields = ["user_email", "user_display_name", "role", "joined_at"]


class WorkspaceDetailSerializer(serializers.ModelSerializer):
    members = WorkspaceMemberSerializer(source="memberships", many=True, read_only=True)
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "slug", "display_name", "drive_root_folder_id",
            "created_at", "updated_at", "settings",
            "members", "my_role",
        ]

    def get_my_role(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            from apps.workspaces.permissions import role_for
            return role_for(request.user, obj)
        return None
```

- [ ] **Step 2: Commit**

```bash
git add apps/workspaces/serializers.py
git commit -m "feat(workspaces): API serializers"
```

(No tests yet — covered by Task 9 view tests.)

---

## Task 9: Workspace list + detail API

**Files:**
- Create: `apps/workspaces/views.py`
- Create: `apps/workspaces/urls.py`
- Modify: `config/urls.py`
- Create: `apps/workspaces/tests/test_views.py`

- [ ] **Step 1: Write failing tests**

`apps/workspaces/tests/test_views.py`:
```python
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


def make_user(email):
    return User.objects.create_user(email=email, username=email.split("@")[0])


def make_ws(slug, owner, **extra):
    ws = Workspace.objects.create(
        slug=slug, display_name=extra.get("display_name", slug.title()),
        drive_root_folder_id=extra.get("drive_root_folder_id", f"folder-{slug}"),
        created_by=owner,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner")
    return ws


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


@pytest.fixture
def auth_client(alice):
    c = APIClient()
    c.force_authenticate(alice)
    return c


@pytest.mark.django_db
def test_list_workspaces_returns_only_member_workspaces(auth_client, alice, bob):
    ws_a = make_ws("acme", alice)
    ws_b = make_ws("beta", bob)  # alice is NOT a member
    resp = auth_client.get("/api/workspaces/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    slugs = {w["slug"] for w in body}
    assert slugs == {"acme"}


@pytest.mark.django_db
def test_list_workspaces_includes_my_role(auth_client, alice):
    make_ws("acme", alice)
    resp = auth_client.get("/api/workspaces/")
    body = resp.json()["data"]
    assert body[0]["role"] == "owner"


@pytest.mark.django_db
def test_workspace_detail_for_member(auth_client, alice):
    ws = make_ws("acme", alice)
    resp = auth_client.get(f"/api/workspaces/{ws.slug}/")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["slug"] == "acme"
    assert body["my_role"] == "owner"
    assert len(body["members"]) == 1
    assert body["members"][0]["user_email"] == "alice@example.com"


@pytest.mark.django_db
def test_workspace_detail_returns_404_for_non_member(auth_client, alice, bob):
    make_ws("acme", alice)
    ws_b = make_ws("beta", bob)
    resp = auth_client.get(f"/api/workspaces/{ws_b.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_workspaces_unauth_401():
    c = APIClient()
    resp = c.get("/api/workspaces/")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run failing tests**

Run: `pytest apps/workspaces/tests/test_views.py -v`
Expected: FAIL — 404s for missing URLs

- [ ] **Step 3: Implement the views**

`apps/workspaces/views.py`:
```python
"""REST endpoints for the workspaces API.

Phase A surface:
- GET /api/workspaces/         — list my workspaces
- GET /api/workspaces/<slug>/  — detail (members + my role)
- GET /api/workspaces/drive-config/ — service-account email for "share with this"

POST/PATCH/DELETE for workspaces, members, invites are Phase B.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member, user_workspaces
from apps.workspaces.serializers import (
    WorkspaceDetailSerializer,
    WorkspaceSummarySerializer,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_list(request):
    qs = user_workspaces(request.user)
    serializer = WorkspaceSummarySerializer(qs, many=True, context={"request": request})
    return Response(success_response(serializer.data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_detail(request, slug):
    try:
        ws = Workspace.objects.get(slug=slug)
    except Workspace.DoesNotExist:
        return Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    if not is_member(request.user, ws):
        # Return 404 (not 403) to avoid leaking workspace existence
        return Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    serializer = WorkspaceDetailSerializer(ws, context={"request": request})
    return Response(success_response(serializer.data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def drive_config(request):
    """Returns the service-account email used by all workspaces.

    The user copy-pastes this into Google Drive's "Share" dialog when
    setting up a new workspace. Reading the SA email from the
    decrypted credential is acceptable here — it's a public identifier,
    not a secret.
    """
    from apps.service_accounts.models import ServiceAccount
    try:
        sa = ServiceAccount.objects.get(name="ace-drive", is_active=True)
    except ServiceAccount.DoesNotExist:
        return Response(
            error_response(
                "ace-drive service account not configured",
                code="drive-not-configured",
            ),
            status=500,
        )
    import json
    try:
        info = json.loads(sa.credential_json)
        email = info.get("client_email", "")
    except Exception:  # noqa: BLE001
        email = ""
    return Response(success_response({"service_account_email": email}))
```

- [ ] **Step 4: Wire the URLs**

`apps/workspaces/urls.py`:
```python
from django.urls import path

from apps.workspaces import views

app_name = "workspaces"

urlpatterns = [
    path("", views.workspace_list, name="list"),
    path("drive-config/", views.drive_config, name="drive-config"),
    path("<slug:slug>/", views.workspace_detail, name="detail"),
]
```

In `config/urls.py`, add (alongside the other `path("api/...")` entries):
```python
    path("api/workspaces/", include("apps.workspaces.urls", namespace="workspaces")),
```

- [ ] **Step 5: Run tests**

Run: `pytest apps/workspaces/tests/test_views.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/workspaces/views.py apps/workspaces/urls.py apps/workspaces/tests/test_views.py config/urls.py
git commit -m "feat(workspaces): GET /api/workspaces/ list + detail + drive-config"
```

---

## Task 10: Django admin registrations

**Files:**
- Create: `apps/workspaces/admin.py`

- [ ] **Step 1: Write the admin classes**

`apps/workspaces/admin.py`:
```python
from django.contrib import admin

from apps.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMembership


class MembershipInline(admin.TabularInline):
    model = WorkspaceMembership
    extra = 0
    autocomplete_fields = ["user"]
    fields = ["user", "role", "invited_by", "joined_at"]
    readonly_fields = ["joined_at"]


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["slug", "display_name", "drive_root_folder_id", "created_by", "created_at"]
    search_fields = ["slug", "display_name", "drive_root_folder_id"]
    autocomplete_fields = ["created_by"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [MembershipInline]


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ["workspace", "user", "role", "joined_at"]
    list_filter = ["role"]
    search_fields = ["workspace__slug", "user__email"]
    autocomplete_fields = ["workspace", "user", "invited_by"]


@admin.register(WorkspaceInvite)
class WorkspaceInviteAdmin(admin.ModelAdmin):
    list_display = ["email", "workspace", "role", "created_at", "accepted_at", "revoked_at"]
    list_filter = ["role"]
    search_fields = ["email", "workspace__slug"]
    autocomplete_fields = ["workspace", "invited_by"]
    readonly_fields = ["token", "created_at"]
```

- [ ] **Step 2: Verify the admin loads**

Run: `python manage.py check`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add apps/workspaces/admin.py
git commit -m "feat(workspaces): Django admin registrations"
```

---

## Task 11: Data migration — seed `dimagi-team` and backfill FKs

**Files:**
- Create: `apps/workspaces/migrations/0002_seed_dimagi_team.py`
- Create: `apps/workspaces/tests/test_seed_migration.py`

- [ ] **Step 1: Write the migration**

`apps/workspaces/migrations/0002_seed_dimagi_team.py`:
```python
"""Seed the dimagi-team workspace and backfill FKs on existing rows.

This migration is idempotent. If the dimagi-team workspace already
exists, the seed step is skipped; only backfill runs.

Founding member: jjackson@dimagi.com (Owner). The ace@dimagi-ai.com bot
is added as Editor if it exists.
"""
from django.conf import settings
from django.db import migrations


FOUNDING_OWNER_EMAIL = "jjackson@dimagi.com"
BOT_EMAIL = "ace@dimagi-ai.com"


def seed_and_backfill(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    Membership = apps.get_model("ace_workspaces", "WorkspaceMembership")
    User = apps.get_model("ace_auth", "User")
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    Session = apps.get_model("sessions", "Session")
    ShareToken = apps.get_model("sessions", "ShareToken")
    IngestUpload = apps.get_model("sessions", "IngestUpload")

    folder_id = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "")
    if not folder_id:
        # No drive root configured — skip seed (test envs, fresh installs).
        return

    owner = User.objects.filter(email__iexact=FOUNDING_OWNER_EMAIL).first()
    if owner is None:
        # Fall back to the oldest user. Pure fresh DB? skip everything.
        owner = User.objects.order_by("date_joined", "id").first()
    if owner is None:
        return

    ws, created = Workspace.objects.get_or_create(
        slug="dimagi-team",
        defaults={
            "display_name": "Dimagi Team",
            "drive_root_folder_id": folder_id,
            "created_by": owner,
        },
    )

    # Owner membership
    Membership.objects.get_or_create(
        workspace=ws, user=owner,
        defaults={"role": "owner"},
    )

    # Bot as Editor (if present)
    bot = User.objects.filter(email__iexact=BOT_EMAIL).first()
    if bot is not None:
        Membership.objects.get_or_create(
            workspace=ws, user=bot,
            defaults={"role": "editor"},
        )

    # Backfill OppWorkspace.workspace
    OppWorkspace.objects.filter(workspace__isnull=True).update(workspace=ws)

    # Backfill Session.workspace for opp-tied sessions
    # (Sessions have an `opp_slug` text field referring to OppWorkspace.slug.)
    opp_slugs = set(
        OppWorkspace.objects.filter(workspace=ws).values_list("slug", flat=True)
    )
    if opp_slugs:
        Session.objects.filter(
            workspace__isnull=True, opp_slug__in=opp_slugs
        ).update(workspace=ws)

    # Backfill ShareToken.workspace via the related session
    for tok in ShareToken.objects.filter(workspace__isnull=True).select_related("session"):
        if tok.session.workspace_id is not None:
            tok.workspace_id = tok.session.workspace_id
            tok.save(update_fields=["workspace"])

    # Backfill IngestUpload.workspace via the related session
    for up in IngestUpload.objects.filter(workspace__isnull=True).select_related("session"):
        if up.session.workspace_id is not None:
            up.workspace_id = up.session.workspace_id
            up.save(update_fields=["workspace"])


def reverse_seed(apps, schema_editor):
    Workspace = apps.get_model("ace_workspaces", "Workspace")
    Workspace.objects.filter(slug="dimagi-team").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0001_initial"),
        # Replace 000X below with the actual migration filenames generated in
        # tasks 6 and 7 (e.g. 0007_oppworkspace_workspace).
        ("opps", "000X_oppworkspace_workspace"),
        ("sessions", "000X_workspace_fks"),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, reverse_code=reverse_seed),
    ]
```

> The dependency strings above are placeholders. After running Tasks 6 and 7's `makemigrations`, look at the generated filenames in `apps/opps/migrations/` and `apps/sessions/migrations/` and replace `000X_*` with the actual names.

- [ ] **Step 2: Apply migration locally**

Run: `python manage.py migrate`
Expected: clean apply with output `Applying ace_workspaces.0002_seed_dimagi_team... OK` (and no rows backfilled because dev DB is empty unless you've created test data).

- [ ] **Step 3: Write a migration correctness test**

`apps/workspaces/tests/test_seed_migration.py`:
```python
"""Verify the seed-and-backfill data migration end-to-end on a fresh DB.

Uses django-test-migrations to run the migration against pre-seeded
state and assert backfill correctness.
"""
import pytest
from django.test import override_settings


@pytest.mark.django_db(transaction=True)
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="folder-test-1")
def test_seed_migration_creates_dimagi_team_and_backfills(django_db_blocker):
    """Smoke test: seed founding user + an opp + a session, run the
    `seed_and_backfill` function, and assert all FKs are populated."""
    from django.contrib.auth import get_user_model

    from apps.opps.models import OppWorkspace
    from apps.sessions.models import Session, ShareToken, IngestUpload
    from apps.workspaces.migrations.0002_seed_dimagi_team import seed_and_backfill
    from apps.workspaces.models import Workspace, WorkspaceMembership

    User = get_user_model()

    # Pre-seed: founding user + bot + one opp + one session
    founder = User.objects.create_user(
        email="jjackson@dimagi.com", username="jjackson"
    )
    User.objects.create_user(email="ace@dimagi-ai.com", username="ace-bot")

    opp = OppWorkspace.objects.create(
        slug="acme-opp", display_name="ACME",
        created_by=founder,
    )
    session = Session.objects.create(
        title="seed test", owner=founder,
        opp_slug="acme-opp",
    )
    tok = ShareToken.objects.create(session=session, created_by=founder)
    upload = IngestUpload.objects.create(
        session=session, uploaded_by=founder, line_count=1, raw_bytes=10,
    )

    # Run via the shim that mimics what RunPython would call.
    class _AppShim:
        def get_model(self, app_label, name):
            from django.apps import apps as django_apps
            return django_apps.get_model(app_label, name)
    seed_and_backfill(_AppShim(), schema_editor=None)

    ws = Workspace.objects.get(slug="dimagi-team")
    assert ws.drive_root_folder_id == "folder-test-1"
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user=founder, role="owner"
    ).exists()
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user__email="ace@dimagi-ai.com", role="editor"
    ).exists()

    opp.refresh_from_db()
    assert opp.workspace == ws

    session.refresh_from_db()
    assert session.workspace == ws

    tok.refresh_from_db()
    assert tok.workspace == ws

    upload.refresh_from_db()
    assert upload.workspace == ws


@pytest.mark.django_db(transaction=True)
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="")
def test_seed_migration_skips_when_no_root_folder():
    """If ACE_DRIVE_ROOT_FOLDER_ID is empty (fresh installs), the migration
    is a no-op."""
    from apps.workspaces.migrations.0002_seed_dimagi_team import seed_and_backfill
    from apps.workspaces.models import Workspace

    class _AppShim:
        def get_model(self, app_label, name):
            from django.apps import apps as django_apps
            return django_apps.get_model(app_label, name)

    seed_and_backfill(_AppShim(), schema_editor=None)
    assert Workspace.objects.filter(slug="dimagi-team").count() == 0
```

> Note: `from apps.workspaces.migrations.0002_seed_dimagi_team import seed_and_backfill` won't work with a leading-numeric module name. Use `importlib`:
> ```python
> import importlib
> mod = importlib.import_module("apps.workspaces.migrations.0002_seed_dimagi_team")
> seed_and_backfill = mod.seed_and_backfill
> ```

- [ ] **Step 4: Run the migration test**

Run: `pytest apps/workspaces/tests/test_seed_migration.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/workspaces/migrations/0002_seed_dimagi_team.py apps/workspaces/tests/test_seed_migration.py
git commit -m "feat(workspaces): seed-and-backfill data migration"
```

---

## Task 12: Drop the `@dimagi.com` filter

**Files:**
- Modify: `config/settings/base.py:222`
- Modify: `apps/auth/oauth_views.py:213-220`

- [ ] **Step 1: Update the setting**

In `config/settings/base.py`, change line 222 from:
```python
ACE_ALLOWED_EMAIL_DOMAINS = ["dimagi.com", "dimagi-ai.com"]
```
to:
```python
# Empty list = allow any Connect-authenticated user. Multi-tenancy
# (workspaces + memberships) is the actual access-control gate; the
# domain filter is preserved as a deployment safety knob (set to a
# non-empty list to revert to allow-listed signups).
ACE_ALLOWED_EMAIL_DOMAINS = env.list("ACE_ALLOWED_EMAIL_DOMAINS", default=[])
```

- [ ] **Step 2: Update the OAuth callback**

In `apps/auth/oauth_views.py`, replace lines 211-221 (the filter block) with:
```python
    # Enforce allowed email domains (only when the list is non-empty).
    # Empty list = allow any Connect-authenticated user; per-workspace
    # membership is the real access-control gate.
    email = (profile_data.get("email") or "").strip().lower()
    logger.info(f"Final email for domain check: {email!r}")
    allowed_domains = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    if allowed_domains:
        _, _, email_domain = email.rpartition("@")
        if email_domain not in allowed_domains:
            logger.warning(f"Rejected login for non-allowed email: {email!r}")
            allowed_str = ", ".join(f"@{d}" for d in allowed_domains)
            messages.error(request, f"Access is restricted to {allowed_str} accounts.")
            return redirect("auth:login")
```

- [ ] **Step 3: Add a regression test**

In `apps/auth/tests/test_oauth_callback.py` (or wherever existing OAuth tests live — check first with `ls apps/auth/tests/`), add:
```python
@pytest.mark.django_db
def test_oauth_callback_allows_any_domain_when_list_empty(client, monkeypatch):
    """With ACE_ALLOWED_EMAIL_DOMAINS = [], a non-Dimagi email signs in."""
    # Set up the same mocks the existing callback tests use, but with
    # email='charlie@example.com' and assert the redirect is to /opps
    # (or /welcome), NOT back to the login page with an error message.
    ...  # mirror the patterns from the surrounding test file
```

If no existing OAuth callback test file exists, skip this step — the change is a one-line predicate flip and is low-risk.

- [ ] **Step 4: Run the existing auth tests**

Run: `pytest apps/auth/tests/ -v`
Expected: existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add config/settings/base.py apps/auth/oauth_views.py apps/auth/tests/
git commit -m "feat(auth): drop @dimagi.com filter — workspace membership is the gate"
```

---

## Task 13: Workspace-scoped reads on `apps/opps/`

**Files:**
- Modify: `apps/opps/views.py` — `_require_drive`, `_resolve_ace_root_folder_id`, all list/detail handlers
- Modify: `apps/opps/drive_client.py:239-251` — `get_drive_client` accepts a workspace
- Modify: `apps/opps/tests/test_views_opp_list.py` — update fixtures

The `apps/opps/views.py` file uses a single `_resolve_ace_root_folder_id` helper that reads from `settings.ACE_DRIVE_ROOT_FOLDER_ID`. After this task, the helper accepts a `Workspace` and reads `workspace.drive_root_folder_id` instead. Membership is checked at the entry point.

- [ ] **Step 1: Update `_require_drive` to resolve workspace from URL**

In `apps/opps/views.py`, change `_require_drive` from its current form to:
```python
def _require_drive(request, workspace_slug: str | None = None):
    """Return (workspace, drive_client, error_response_or_None).

    `workspace_slug` is read from the URL kwarg. The membership check
    is the access-control gate; non-members get 404 (not 403).
    """
    if not request.user.is_authenticated:
        return None, None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    if not workspace_slug:
        return None, None, Response(
            error_response("workspace required", code="workspace-required"),
            status=400,
        )
    from apps.workspaces.models import Workspace
    from apps.workspaces.permissions import is_member
    try:
        ws = Workspace.objects.get(slug=workspace_slug)
    except Workspace.DoesNotExist:
        return None, None, Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    if not is_member(request.user, ws):
        return None, None, Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    try:
        client = get_drive_client(workspace=ws)
        return ws, client, None
    except ServiceAccountNotFound as exc:
        return ws, None, Response(
            error_response(str(exc), code="drive-not-configured"), status=500,
        )
```

- [ ] **Step 2: Update `_resolve_ace_root_folder_id`**

Replace the existing helper with:
```python
def _resolve_ace_root_folder_id(workspace) -> str | None:
    """Return the Drive folder id for the given workspace's root."""
    if workspace is None:
        return None
    return workspace.drive_root_folder_id or None
```

- [ ] **Step 3: Update `get_drive_client` to accept a workspace**

In `apps/opps/drive_client.py`, change `get_drive_client` to:
```python
def get_drive_client(workspace=None, on_behalf_of: str | None = None) -> GoogleDriveClient:
    """Return a Drive client backed by the 'ace-drive' service account.

    Args:
        workspace: Optional Workspace; when provided, the AccessLog row
            is annotated with `workspace_slug`.
        on_behalf_of: Optional email to impersonate via DWD.
    """
    context = {"caller": "opps.drive_client"}
    if workspace is not None:
        context["workspace_slug"] = workspace.slug
    creds = registry.get_credentials(
        "ace-drive",
        on_behalf_of=on_behalf_of,
        context=context,
    )
    return GoogleDriveClient(creds)
```

- [ ] **Step 4: Update each list/detail handler to take `workspace_slug`**

For each handler in `apps/opps/views.py` that currently has `request` as its only argument and calls `_require_drive(request)`, change the signature to take `workspace_slug` and pass it through:

Example for `_opp_list_impl`:
```python
def _opp_list_impl(request, workspace_slug: str):
    ws, client, err = _require_drive(request, workspace_slug)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(ws)
    # ... rest of existing logic, using ace_folder_id
```

Apply the same pattern to: `opp_collection`, opp detail view, scorecard view, all the other handlers in this file. Verify by grepping `_require_drive(` after the change — every call should pass `workspace_slug`.

- [ ] **Step 5: Update `apps/opps/urls.py` to mount under `/api/workspaces/<slug>/opps/`**

Examine the current URL patterns in `apps/opps/urls.py`. They likely live under `/api/opps/`. We will keep the existing routes registered (for backward-compat redirects) but ALSO mount them under the workspace-scoped path.

Two-step approach:
1. In `config/urls.py`, in addition to the existing `path("api/opps/", include("apps.opps.urls"))`, add:
   ```python
   path("api/workspaces/<slug:workspace_slug>/opps/", include("apps.opps.urls", namespace="opps_ws")),
   ```
2. The existing flat `/api/opps/...` routes return 410 Gone with a deprecation message (frontend will be updated in Task 18 to use the workspace-scoped path).

For step 2, modify each handler's first lines:
```python
def _opp_list_impl(request, workspace_slug: str = None):
    if workspace_slug is None:
        return Response(
            error_response(
                "this endpoint requires workspace context — use /api/workspaces/<slug>/opps/",
                code="workspace-required",
            ),
            status=410,
        )
    # ... rest of the logic
```

- [ ] **Step 6: Update opp creation to scope slug uniqueness per workspace**

In `apps/opps/opp_creator.py:54`, change:
```python
if OppWorkspace.objects.filter(slug=slug).exists():
```
to:
```python
if OppWorkspace.objects.filter(workspace=workspace, slug=slug).exists():
```

And add a `workspace` parameter to the `create_opp` function signature (just before `owner`). Pass `workspace=ws` from the calling view (`_create_opp_impl` or similar — find the call site by grepping `create_opp(`).

> If `OppWorkspace.slug` is still the primary key (not yet pivoted to per-workspace uniqueness), this query change is a no-op for correctness but prepares for Task 14. Defer the actual PK pivot to Task 14.

- [ ] **Step 7: Update existing opp tests**

The fixtures in `apps/opps/tests/test_views_opp_list.py` and friends create users + opps without a workspace. Update each test fixture to:
1. Create a `Workspace` (via a `make_workspace(user, slug="test-ws")` helper)
2. Make the user a member
3. Use the workspace-scoped URL `/api/workspaces/<slug>/opps/...` instead of `/api/opps/...`

Add a shared fixture in `apps/opps/tests/conftest.py`:
```python
import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership


@pytest.fixture
def workspace(db):
    User = get_user_model()
    user = User.objects.create_user(email="alice@example.com", username="alice")
    ws = Workspace.objects.create(
        slug="test-ws", display_name="Test WS",
        drive_root_folder_id="folder-test", created_by=user,
    )
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="owner")
    return ws


@pytest.fixture
def workspace_member(workspace):
    return workspace.memberships.first().user
```

Then in each test, use the `workspace` and `workspace_member` fixtures and target `/api/workspaces/test-ws/opps/...`.

- [ ] **Step 8: Run the opps test suite**

Run: `pytest apps/opps/tests/ -v`
Expected: all passing.

- [ ] **Step 9: Commit**

```bash
git add apps/opps/ config/urls.py
git commit -m "feat(opps): workspace-scoped reads + writes"
```

---

## Task 14: (Deferred to Phase B) — `OppWorkspace` PK pivot

The spec calls for `OppWorkspace.slug` to become per-workspace unique
(`unique_together = [("workspace", "slug")]`) instead of a global primary
key. This is **not required for Phase A** because Phase A seeds exactly
one workspace (`dimagi-team`); slug collisions across workspaces can't
happen until workspace creation lands.

The PK pivot is high-risk (changing a Postgres primary key with FK
references is delicate), so it belongs at the **start of Phase B**,
landed in its own migration before the workspace-creation endpoint
ships. Phase B's plan will own this work.

Phase A leaves `OppWorkspace.slug` as the global primary key. The query
in `apps/opps/opp_creator.py:54` (already updated in Task 13 Step 6 to
filter by workspace) becomes the actual constraint enforcer once Task
14 lands in Phase B.

(No Phase A action.)

---

## Task 15: Workspace-scoped reads on `apps/sessions/` and `apps/ingest/`

**Files:**
- Modify: `apps/sessions/views.py` — every list endpoint
- Modify: `apps/ingest/views.py:21-50` — accept `ace_root_folder_id`, resolve workspace
- Modify: corresponding tests

- [ ] **Step 1: Update sessions list endpoints**

In `apps/sessions/views.py`, find any view that lists sessions for the current user (e.g. `/api/sessions/`). Add a `workspace_slug` URL kwarg and filter:
```python
def session_list(request, workspace_slug: str):
    from apps.workspaces.models import Workspace
    from apps.workspaces.permissions import is_member
    try:
        ws = Workspace.objects.get(slug=workspace_slug)
    except Workspace.DoesNotExist:
        return Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    if not is_member(request.user, ws):
        return Response(
            error_response("workspace not found", code="not-found"), status=404
        )
    qs = Session.objects.filter(workspace=ws).order_by("-created_at")
    # ... rest of pagination/serialization unchanged
```

For session detail views: load the session, check `is_member(request.user, session.workspace)`, return 404 if not a member or if workspace is None and the requesting user isn't the session owner (orphan sessions stay creator-only).

- [ ] **Step 2: Update ingest upload to require `ace_root_folder_id`**

In `apps/ingest/views.py`, after the existing `opp_slug` lookup (around line 35), add:
```python
    ace_root_folder_id = (request.data.get("ace_root_folder_id") or "").strip()
    workspace = None
    if ace_root_folder_id:
        from apps.workspaces.models import Workspace
        from apps.workspaces.permissions import is_member
        try:
            workspace = Workspace.objects.get(drive_root_folder_id=ace_root_folder_id)
        except Workspace.DoesNotExist:
            return Response(
                error_response(
                    "no workspace claims this drive_root_folder_id",
                    code="workspace-not-found",
                ),
                status=404,
            )
        if not is_member(request.user, workspace):
            return Response(
                error_response(
                    "you are not a member of this workspace",
                    code="not-a-member",
                ),
                status=403,
            )
    # else: orphan upload (allowed) — workspace stays None
```

Then when creating the `Session` and `IngestUpload`, pass `workspace=workspace`:
```python
    session = Session.objects.create(
        owner=request.user, title=parsed.title, source="upload",
        opp_slug=opp_slug, opp_run_id=opp_run_id,
        workspace=workspace,
    )
    upload = IngestUpload.objects.create(
        session=session, uploaded_by=request.user,
        cli_session_id=parsed.cli_session_id,
        line_count=parsed.line_count, raw_bytes=parsed.raw_bytes,
        workspace=workspace,
    )
```

- [ ] **Step 3: Add a test for the new ingest behavior**

In `apps/ingest/tests/test_upload.py` (or wherever existing upload tests live), add:
```python
@pytest.mark.django_db
def test_upload_with_ace_root_folder_id_attaches_workspace(api_client, founder, workspace, sample_jsonl):
    """Upload sent with ace_root_folder_id matching a member's workspace
    populates IngestUpload.workspace."""
    api_client.force_authenticate(founder)
    resp = api_client.post(
        "/api/ingest/upload",
        {
            "file": sample_jsonl,
            "opp_slug": "any",
            "ace_root_folder_id": workspace.drive_root_folder_id,
        },
        format="multipart",
    )
    assert resp.status_code == 201
    from apps.sessions.models import IngestUpload
    upload = IngestUpload.objects.get(uploaded_by=founder)
    assert upload.workspace == workspace
    assert upload.session.workspace == workspace


@pytest.mark.django_db
def test_upload_with_unknown_folder_returns_404(api_client, founder, sample_jsonl):
    api_client.force_authenticate(founder)
    resp = api_client.post(
        "/api/ingest/upload",
        {
            "file": sample_jsonl,
            "ace_root_folder_id": "no-such-folder",
        },
        format="multipart",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_upload_without_folder_id_creates_orphan(api_client, founder, sample_jsonl):
    """Backward compat: older plugin uploads (no ace_root_folder_id) work
    as orphan uploads."""
    api_client.force_authenticate(founder)
    resp = api_client.post(
        "/api/ingest/upload",
        {"file": sample_jsonl},
        format="multipart",
    )
    assert resp.status_code == 201
    from apps.sessions.models import IngestUpload
    upload = IngestUpload.objects.get(uploaded_by=founder)
    assert upload.workspace is None
```

(`founder`, `workspace`, `sample_jsonl` fixtures: ensure they exist in `apps/ingest/tests/conftest.py` or add them.)

- [ ] **Step 4: Run sessions + ingest tests**

Run: `pytest apps/sessions/tests/ apps/ingest/tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add apps/sessions/views.py apps/ingest/views.py apps/sessions/tests/ apps/ingest/tests/
git commit -m "feat(sessions+ingest): workspace-scoped reads and uploads"
```

---

## Task 16: Frontend API client — `frontend/src/api/workspaces.ts`

**Files:**
- Create: `frontend/src/api/workspaces.ts`
- Modify: `frontend/src/api/types.ts` (or wherever types live) — add `Workspace` types

- [ ] **Step 1: Add types**

In `frontend/src/api/types.ts`, add:
```typescript
export type WorkspaceRole = "owner" | "editor" | "viewer";

export interface WorkspaceSummary {
  slug: string;
  display_name: string;
  role: WorkspaceRole | null;
  created_at: string;
}

export interface WorkspaceMember {
  user_email: string;
  user_display_name: string;
  role: WorkspaceRole;
  joined_at: string;
}

export interface WorkspaceDetail {
  slug: string;
  display_name: string;
  drive_root_folder_id: string;
  created_at: string;
  updated_at: string;
  settings: Record<string, unknown>;
  members: WorkspaceMember[];
  my_role: WorkspaceRole | null;
}

export interface DriveConfig {
  service_account_email: string;
}
```

- [ ] **Step 2: Add fetch helpers**

`frontend/src/api/workspaces.ts`:
```typescript
import type { DriveConfig, WorkspaceDetail, WorkspaceSummary } from "./types";

const PREFIX = "/ace";  // matches frontend basename

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${PREFIX}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json())?.error?.message ?? ""; } catch {}
    throw new Error(detail || `${resp.status} ${resp.statusText}`);
  }
  const body = await resp.json();
  return body.data as T;
}

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return fetchJSON<WorkspaceSummary[]>("/api/workspaces/");
}

export async function getWorkspace(slug: string): Promise<WorkspaceDetail> {
  return fetchJSON<WorkspaceDetail>(`/api/workspaces/${slug}/`);
}

export async function getDriveConfig(): Promise<DriveConfig> {
  return fetchJSON<DriveConfig>("/api/workspaces/drive-config/");
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/workspaces.ts frontend/src/api/types.ts
git commit -m "feat(frontend): workspaces API client"
```

---

## Task 17: `WorkspaceSwitcher` component + `useWorkspace` hook

**Files:**
- Create: `frontend/src/hooks/useWorkspace.ts`
- Create: `frontend/src/components/WorkspaceSwitcher.tsx`
- Modify: `frontend/src/App.tsx` — render the switcher in the top nav

- [ ] **Step 1: `useWorkspace` hook**

`frontend/src/hooks/useWorkspace.ts`:
```typescript
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { listWorkspaces } from "../api/workspaces";
import type { WorkspaceSummary } from "../api/types";

export interface WorkspaceContext {
  current: WorkspaceSummary | null;
  all: WorkspaceSummary[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useWorkspace(): WorkspaceContext {
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();
  const [all, setAll] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadCounter, setReloadCounter] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listWorkspaces()
      .then((ws) => { if (!cancelled) { setAll(ws); setError(null); } })
      .catch((e) => { if (!cancelled) setError(String(e?.message ?? e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reloadCounter]);

  const current = workspaceSlug
    ? all.find((w) => w.slug === workspaceSlug) ?? null
    : null;

  return {
    current,
    all,
    loading,
    error,
    reload: () => setReloadCounter((n) => n + 1),
  };
}
```

- [ ] **Step 2: `WorkspaceSwitcher` component**

`frontend/src/components/WorkspaceSwitcher.tsx`:
```typescript
import { useNavigate } from "react-router-dom";
import { ChevronDown } from "lucide-react";

import { useWorkspace } from "../hooks/useWorkspace";

export function WorkspaceSwitcher() {
  const { current, all, loading } = useWorkspace();
  const navigate = useNavigate();

  if (loading) return null;

  if (all.length === 0) {
    return (
      <button
        type="button"
        onClick={() => navigate("/welcome")}
        className="rounded border border-dashed border-input px-3 py-1.5 text-sm text-muted-foreground hover:border-input/80"
      >
        Set up a workspace
      </button>
    );
  }

  return (
    <div className="relative inline-block">
      <select
        className="appearance-none rounded border border-input bg-card px-3 py-1.5 pr-8 text-sm font-medium text-foreground"
        value={current?.slug ?? ""}
        onChange={(e) => {
          const target = e.target.value;
          if (target) navigate(`/w/${target}/opps`);
        }}
      >
        <option value="" disabled>
          {current ? current.display_name : "Pick a workspace"}
        </option>
        {all.map((w) => (
          <option key={w.slug} value={w.slug}>
            {w.display_name}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
```

- [ ] **Step 3: Render the switcher in the top nav**

In `frontend/src/App.tsx`, find the top-nav region (likely a `<header>` element) and render `<WorkspaceSwitcher />` to the right of the logo / title. Import it from `./components/WorkspaceSwitcher`.

- [ ] **Step 4: Manually verify in dev**

Run: `docker compose up`. Sign in. Verify the switcher appears in the nav and shows "Dimagi Team" (the seeded workspace). Selecting a workspace navigates to `/w/<slug>/opps`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useWorkspace.ts frontend/src/components/WorkspaceSwitcher.tsx frontend/src/App.tsx
git commit -m "feat(frontend): WorkspaceSwitcher + useWorkspace hook"
```

---

## Task 18: Pivot frontend routes to `/w/<slug>/...`

**Files:**
- Modify: `frontend/src/router.tsx`
- Create: `frontend/src/pages/NoWorkspaceRedirect.tsx`
- Create: `frontend/src/pages/WelcomePage.tsx` (stub for Phase A)
- Modify: `frontend/src/pages/OppListPage.tsx` — read `workspaceSlug` from `useParams`
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx` — same
- Modify: `frontend/src/pages/SessionsPage.tsx` — same
- Modify: `frontend/src/pages/ChatPage.tsx` — same
- Modify: `frontend/src/api/opps.ts` — every call takes a `workspaceSlug`
- Modify: `frontend/src/api/sessions.ts` — same

- [ ] **Step 1: `NoWorkspaceRedirect` helper**

`frontend/src/pages/NoWorkspaceRedirect.tsx`:
```typescript
import { useEffect } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useWorkspace } from "../hooks/useWorkspace";

/**
 * Resolves a legacy bare path like `/opps` to `/w/<defaultSlug>/opps`
 * for the user's most-recent or only workspace. Sends users with zero
 * memberships to /welcome.
 */
export function NoWorkspaceRedirect({ subPath }: { subPath: string }) {
  const { all, loading } = useWorkspace();
  const location = useLocation();

  if (loading) return null;
  if (all.length === 0) return <Navigate to="/welcome" replace />;
  const target = `/w/${all[0].slug}/${subPath}${location.search}`;
  return <Navigate to={target} replace />;
}
```

- [ ] **Step 2: `WelcomePage` stub**

`frontend/src/pages/WelcomePage.tsx`:
```typescript
export default function WelcomePage() {
  return (
    <div className="mx-auto max-w-xl px-6 py-12 text-center">
      <h1 className="text-2xl font-semibold text-foreground">Welcome to ACE</h1>
      <p className="mt-3 text-muted-foreground">
        You don't have a workspace yet. Workspace self-creation lands in
        Phase B; for now, ask an admin to add you to an existing workspace.
      </p>
    </div>
  );
}
```

(Phase B will replace this with the workspace-creation wizard.)

- [ ] **Step 3: Rewrite `frontend/src/router.tsx`**

```typescript
import { createBrowserRouter, Navigate } from "react-router-dom";

import { App } from "./App";
import HealthPage from "./pages/HealthPage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";
import SessionsPage from "./pages/SessionsPage";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import SettingsPage from "./pages/SettingsPage";
import ShareViewPage from "./pages/ShareViewPage";
import SystemPage from "./pages/SystemPage";
import { NoWorkspaceRedirect } from "./pages/NoWorkspaceRedirect";
import WelcomePage from "./pages/WelcomePage";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <App />,
      children: [
        // Workspace-scoped surface
        {
          path: "w/:workspaceSlug",
          children: [
            { index: true, element: <Navigate to="opps" replace /> },
            { path: "opps", element: <OppListPage /> },
            { path: "opps/:slug", element: <OppWorkbenchPage /> },
            { path: "opps/:slug/runs/:runId", element: <OppWorkbenchPage /> },
            { path: "opps/:slug/runs/:runId/steps/:skill", element: <OppWorkbenchPage /> },
            { path: "sessions", element: <SessionsPage /> },
            { path: "chat", element: <ChatRedirectPage /> },
            { path: "chat/:slug", element: <ChatPage /> },
          ],
        },

        // Welcome / onboarding
        { path: "welcome", element: <WelcomePage /> },

        // User-level (workspace-agnostic)
        { path: "settings", element: <SettingsPage /> },
        { path: "system", element: <SystemPage /> },
        { path: "health", element: <HealthPage /> },
        { path: "auth/cli", element: <AuthCliPage /> },
        { path: "share/:token", element: <ShareViewPage /> },

        // Legacy redirects
        { index: true, element: <NoWorkspaceRedirect subPath="opps" /> },
        { path: "opps", element: <NoWorkspaceRedirect subPath="opps" /> },
        { path: "opps/:slug", element: <NoWorkspaceRedirect subPath="opps/:slug" /> },
        { path: "sessions", element: <NoWorkspaceRedirect subPath="sessions" /> },
        { path: "chat", element: <NoWorkspaceRedirect subPath="chat" /> },
        { path: "chat/:slug", element: <NoWorkspaceRedirect subPath="chat/:slug" /> },
      ],
    },
  ],
  { basename: "/ace" },
);
```

> Note: the `path: "opps/:slug"` legacy redirect substitutes `:slug` literally — you'll need a small helper if the user lands on a deep link. For Phase A, accept that legacy `/opps/<slug>` deep links land at `/w/<defaultSlug>/opps/:slug` literally (which then 404s); fix in Phase C if it becomes a real annoyance.

- [ ] **Step 4: Update `OppListPage.tsx` to use the URL workspace**

In `frontend/src/pages/OppListPage.tsx`, modify the imports + hook:
```typescript
import { useParams } from "react-router-dom";
// ...
const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
```

Then update the `listOpps` call (in `frontend/src/api/opps.ts`) to require a `workspaceSlug` and use it to build the URL: `/api/workspaces/${workspaceSlug}/opps/`. Fix all call sites accordingly.

- [ ] **Step 5: Update `OppWorkbenchPage.tsx`, `SessionsPage.tsx`, `ChatPage.tsx`**

Same pattern: read `workspaceSlug` from `useParams`, pass to API calls.

- [ ] **Step 6: Update `frontend/src/api/opps.ts`**

Every exported function takes `workspaceSlug` as the first arg and prefixes URLs with `/api/workspaces/${workspaceSlug}/opps/...`. Mechanical change.

Same for `frontend/src/api/sessions.ts`.

- [ ] **Step 7: Manual smoke test**

Run: `docker compose up`. Sign in. Verify:
- `/opps` redirects to `/w/dimagi-team/opps`
- The opps page loads with the existing data
- The session list works
- The opp workbench works

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): pivot routes under /w/<slug>/ + legacy redirects"
```

---

## Task 19: Counterpart change in the `ace` plugin (cross-repo)

**Files:**
- Modify: in the sibling `../ace/` repo, the `upload-transcript` skill that calls `/api/ingest/upload`. Find with: `grep -rn 'ingest/upload' ../ace/`

This is the only change required outside ace-web. It is a one-line addition to the multipart payload.

- [ ] **Step 1: Locate the upload call**

```bash
grep -rn 'ingest/upload\|upload-transcript' ../ace/skills/ ../ace/agents/ 2>/dev/null
```

- [ ] **Step 2: Add `ace_root_folder_id` to the payload**

Wherever the skill builds the multipart form fields (looking for `opp_slug=...` likely), add a sibling field `ace_root_folder_id` populated from the local `.ace/config.yaml` value.

If no test infrastructure exists for the plugin skill, document this change in the plan summary and submit a PR against `../ace`.

- [ ] **Step 3: Commit in the `../ace` repo (separately)**

```bash
cd ../ace
git checkout -b feat/upload-transcript-workspace-resolution
git add skills/...
git commit -m "feat(upload-transcript): include ace_root_folder_id for workspace resolution

Counterpart to ace-web multi-tenancy Phase A. The web side uses this
field to resolve the originating workspace from the Drive folder ID."
```

(Open a PR or push directly per `../ace`'s conventions.)

- [ ] **Step 4: Document the cross-repo change**

In ace-web's `CLAUDE.md`, add a note in the workspaces section:
```
The plugin's `upload-transcript` skill sends `ace_root_folder_id` so
the web side can resolve workspace ownership of the upload. See
`../ace/skills/upload-transcript/` for the producer.
```

- [ ] **Step 5: Commit the doc note**

```bash
cd <back to ace-web>
git add CLAUDE.md
git commit -m "docs: document upload-transcript ace_root_folder_id field"
```

---

## Task 20: Update `CLAUDE.md` and verify the full build

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a Workspaces section to `CLAUDE.md`**

Insert after the "Key architectural decisions" section:
```markdown
## ACE Workspaces (multi-tenancy)

ace-web is multi-tenant. The unit of tenancy is the **Workspace** —
a name + a Drive root folder + a member list with roles
(Owner / Editor / Viewer). Spec:
`docs/specs/2026-04-27-multi-tenant-workspaces-design.md`.

- All opp/session/upload reads scope by `request.user`'s workspace
  memberships (not "any authenticated user"). Non-members get 404,
  not 403, to avoid leaking workspace existence.
- Drive folder IDs are unique across workspaces (`Workspace.drive_root_folder_id`).
  This is what lets the CLI plugin work without modification: when an
  ace-web request references folder X, we look up the workspace by
  `drive_root_folder_id=X`.
- Founding migration seeds a single `dimagi-team` workspace from
  `ACE_DRIVE_ROOT_FOLDER_ID`. After Phase A's deploy, that env var is
  no longer read at runtime — it's a migration-only seed value.
- The `@dimagi.com` filter at `apps/auth/oauth_views.py:213` is gone.
  `ACE_ALLOWED_EMAIL_DOMAINS` is preserved as an empty-list default
  (set non-empty to revert).
- URL structure: `/w/<slug>/opps/`, `/w/<slug>/sessions/`, etc.
  Legacy `/opps`, `/sessions` redirect to the user's default
  workspace.
- Phase B (onboarding wizard, invite/share UX) and Phase C (polish)
  are separate plans — see `docs/plans/2026-04-27-multi-tenant-workspaces-phase-{b,c}.md`.
```

- [ ] **Step 2: Run the full backend test suite**

Run: `pytest -v`
Expected: all passing.

- [ ] **Step 3: Run lint**

Run: `ruff check .`
Expected: clean.

- [ ] **Step 4: Manual end-to-end smoke test**

`docker compose up`, sign in, walk through:
1. `/opps` → redirects to `/w/dimagi-team/opps` ✓
2. Opp list shows existing data ✓
3. Click into an opp → workbench loads ✓
4. Switch via the workspace switcher (only one option in dev, but the dropdown should be visible) ✓
5. `/sessions` → redirects ✓
6. `/welcome` (manually navigate) → stub page renders ✓

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document multi-tenancy substrate (Phase A)"
```

---

## Self-review checklist

Before declaring Phase A complete, verify:

- [ ] Every spec section in §4 of `docs/specs/2026-04-27-multi-tenant-workspaces-design.md` either has a Phase A task or is explicitly deferred to Phase B/C
- [ ] Every existing opp/session/upload/share endpoint either takes `workspace_slug` or returns a 410 deprecation
- [ ] No `OppWorkspace.objects.get(slug=...)` query in `apps/` is missing a workspace filter
- [ ] The seed migration is idempotent (re-running it is a no-op)
- [ ] Tests cover: model invariants, permissions, view scoping, ingest folder resolution, migration backfill
- [ ] `ruff check .` is clean
- [ ] Frontend smoke test walks end-to-end with the seeded `dimagi-team` workspace

After Phase A is merged, return for the Phase B plan (onboarding wizard, invite/share, member management UI).
