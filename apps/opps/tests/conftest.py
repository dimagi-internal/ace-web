"""Shared fixtures for apps/opps/tests/.

Two pieces of test infrastructure live here:

1. **Workspace membership shim** (function-scoped, autouse). The Phase A
   multi-tenancy work made every opp endpoint go through
   `_resolve_workspace`, which requires the request user to have at
   least one WorkspaceMembership. Existing tests authenticate a user
   via `force_login` but don't set up a workspace; the shim wraps
   `User.objects.create` so any new User automatically becomes Owner
   of the default test workspace.

2. **Hermetic skill registry stub** (session-scoped, autouse). Every
   apps/opps test asserts behavior that depends on
   `apps.opps.skills.SKILL_REGISTRY` being populated — `sync.py`
   iterates the registry to synthesize step rows. Production reads
   `ACE_PLUGIN_PATH` from settings; the Docker image vendors the
   plugin to `/app/vendor/ace`, but on local checkouts the dev-default
   walk-up in `config/settings/base.py` may not resolve to a real
   plugin dir. The stub at `apps/opps/tests/fixtures/stub_plugin/` is
   a frontmatter-only copy of the real plugin's `agents/*.md` plus the
   real `lib/artifact-manifest.ts` — enough to satisfy the registry
   loader without depending on host filesystem layout. Refresh the
   stub by re-copying from the upstream `ace` plugin when its agent
   frontmatter or artifact manifest changes.

The default workspace's `drive_root_folder_id` is left as a placeholder
because the tests that need a real folder id patch
`_resolve_ace_root_folder_id` directly to inject a `FakeDriveClient`
folder id.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


_STUB_PLUGIN_PATH = (Path(__file__).parent / "fixtures" / "stub_plugin").resolve()


@pytest.fixture(autouse=True, scope="session")
def _stub_ace_plugin_path():
    """Pin ACE_PLUGIN_PATH to the in-repo stub for the whole opps test
    session. See module docstring for context."""
    from apps.opps.skills import reset_cache

    dj_settings.ACE_PLUGIN_PATH = str(_STUB_PLUGIN_PATH)
    reset_cache()
    yield


@pytest.fixture(autouse=True)
def _ensure_workspace_membership(db, monkeypatch):
    """For every test in this package, monkey-patch User creation so any
    new User automatically becomes the Owner of the default test
    workspace. This keeps existing tests' fixture setup intact while
    satisfying the new membership-based access-control gate.
    """
    # Create the default test workspace lazily — only the first User
    # creation triggers it.
    state = {"workspace": None}

    def _ensure_ws():
        if state["workspace"] is not None:
            return state["workspace"]
        from apps.workspaces.models import Workspace as W

        # If anything else already created it (e.g. seed migration in a
        # different test fixture), reuse it.
        ws = W.objects.filter(slug="test-workspace").first()
        if ws is None:
            owner = User.objects.first()
            if owner is None:
                # Will be created momentarily by the test; defer.
                return None
            ws = W.objects.create(
                slug="test-workspace",
                display_name="Test Workspace",
                drive_root_folder_id="test-drive-root-folder-id",
                created_by=owner,
            )
        state["workspace"] = ws
        return ws

    original_create = User.objects.create
    original_create_user = User.objects.create_user

    def _wrap_create(*args, **kwargs):
        user = original_create(*args, **kwargs)
        ws = _ensure_ws()
        if ws is None:
            # First user — create the workspace now.
            ws = Workspace.objects.create(
                slug="test-workspace",
                display_name="Test Workspace",
                drive_root_folder_id="test-drive-root-folder-id",
                created_by=user,
            )
            state["workspace"] = ws
        WorkspaceMembership.objects.get_or_create(
            workspace=ws, user=user, defaults={"role": "owner"}
        )
        return user

    def _wrap_create_user(*args, **kwargs):
        user = original_create_user(*args, **kwargs)
        ws = _ensure_ws()
        if ws is None:
            ws = Workspace.objects.create(
                slug="test-workspace",
                display_name="Test Workspace",
                drive_root_folder_id="test-drive-root-folder-id",
                created_by=user,
            )
            state["workspace"] = ws
        WorkspaceMembership.objects.get_or_create(
            workspace=ws, user=user, defaults={"role": "owner"}
        )
        return user

    monkeypatch.setattr(User.objects, "create", _wrap_create)
    monkeypatch.setattr(User.objects, "create_user", _wrap_create_user)

    # Also auto-attach the test workspace to OppWorkspace creates that
    # don't supply one. Phase B made `workspace` non-nullable, but most
    # existing tests predate workspaces and create OppWorkspaces without
    # passing one. The shim defaults to the test workspace.
    from apps.opps.models import OppWorkspace
    original_opp_create = OppWorkspace.objects.create

    def _wrap_opp_create(*args, **kwargs):
        if "workspace" not in kwargs and "workspace_id" not in kwargs:
            ws = state.get("workspace") or _ensure_ws()
            if ws is None:
                # Force a User to exist so the workspace can be created.
                u = User.objects.first() or User.objects.create(
                    email="conftest@test", display_name="conftest",
                )
                ws = state.get("workspace")
                if ws is None:
                    ws = Workspace.objects.create(
                        slug="test-workspace",
                        display_name="Test Workspace",
                        drive_root_folder_id="test-drive-root-folder-id",
                        created_by=u,
                    )
                    state["workspace"] = ws
                WorkspaceMembership.objects.get_or_create(
                    workspace=ws, user=u, defaults={"role": "owner"},
                )
            kwargs["workspace"] = ws
        return original_opp_create(*args, **kwargs)

    monkeypatch.setattr(OppWorkspace.objects, "create", _wrap_opp_create)
    yield


@pytest.fixture
def workspace(db):
    """Returns the default test workspace (creates a placeholder user if needed)."""
    ws = Workspace.objects.filter(slug="test-workspace").first()
    if ws is None:
        owner = User.objects.first() or User.objects.create(
            email="placeholder@test", display_name="Placeholder"
        )
        ws = Workspace.objects.create(
            slug="test-workspace",
            display_name="Test Workspace",
            drive_root_folder_id="test-drive-root-folder-id",
            created_by=owner,
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=ws, user=owner, defaults={"role": "owner"}
        )
    return ws
