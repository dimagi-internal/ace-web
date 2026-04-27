"""Smoke tests for the seed-and-backfill data migration.

We invoke the migration's `seed_and_backfill` function directly with a
shim `apps` object that returns the live Django models, rather than
running the migration through migrate. The function's logic doesn't
depend on the historical schema, so this is sufficient and much faster.

After Phase B's PK pivot, OppWorkspace.workspace is non-nullable, so
the backfill-of-NULLs branch can no longer be exercised in tests
(which run all migrations to head). The tests below cover the still-
meaningful paths: workspace creation, membership seeding, idempotency,
and the oldest-user fallback.
"""
import importlib

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


_seed_module = importlib.import_module("apps.workspaces.migrations.0002_seed_dimagi_team")
seed_and_backfill = _seed_module.seed_and_backfill


class _AppShim:
    """Mimics the `apps` argument that RunPython passes."""
    def get_model(self, app_label, name):
        from django.apps import apps as django_apps
        return django_apps.get_model(app_label, name)


@pytest.mark.django_db
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="folder-test-1")
def test_seed_creates_dimagi_team_workspace_and_owner_membership():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    User.objects.create_user(email="ace@dimagi-ai.com")

    seed_and_backfill(_AppShim(), schema_editor=None)

    ws = Workspace.objects.get(slug="dimagi-team")
    assert ws.drive_root_folder_id == "folder-test-1"
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user=founder, role="owner",
    ).exists()
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user__email="ace@dimagi-ai.com", role="editor",
    ).exists()


@pytest.mark.django_db
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="")
def test_seed_skips_when_no_root_folder():
    User.objects.create_user(email="jjackson@dimagi.com")
    seed_and_backfill(_AppShim(), schema_editor=None)
    assert Workspace.objects.filter(slug="dimagi-team").count() == 0


@pytest.mark.django_db
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="folder-test-3")
def test_seed_is_idempotent():
    User.objects.create_user(email="jjackson@dimagi.com")
    seed_and_backfill(_AppShim(), schema_editor=None)
    seed_and_backfill(_AppShim(), schema_editor=None)  # second run
    assert Workspace.objects.filter(slug="dimagi-team").count() == 1


@pytest.mark.django_db
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="folder-test-4")
def test_seed_falls_back_to_oldest_user_when_no_jjackson():
    """No jjackson@dimagi.com → use oldest user as Owner."""
    oldest = User.objects.create_user(email="someone@example.com")
    seed_and_backfill(_AppShim(), schema_editor=None)
    ws = Workspace.objects.get(slug="dimagi-team")
    assert ws.created_by == oldest
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user=oldest, role="owner",
    ).exists()
