"""Tests for the 0005 promote-ace-owner data migration.

Invokes the migration's `promote_bot_to_owner` function directly with a shim
`apps` object (same pattern as test_seed_migration), since the logic doesn't
depend on the historical schema.
"""
import importlib

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

_mod = importlib.import_module("apps.workspaces.migrations.0005_promote_ace_owner")
promote_bot_to_owner = _mod.promote_bot_to_owner
demote_bot_to_editor = _mod.demote_bot_to_editor


class _AppShim:
    def get_model(self, app_label, name):
        from django.apps import apps as django_apps
        return django_apps.get_model(app_label, name)


def _dimagi_team(owner):
    return Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-x",
        created_by=owner,
    )


@pytest.mark.django_db
def test_promotes_existing_editor_membership_to_owner():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    bot = User.objects.create_user(email="ace@dimagi-ai.com")
    ws = _dimagi_team(founder)
    WorkspaceMembership.objects.create(workspace=ws, user=bot, role="editor")

    promote_bot_to_owner(_AppShim(), schema_editor=None)

    assert WorkspaceMembership.objects.get(workspace=ws, user=bot).role == "owner"


@pytest.mark.django_db
def test_creates_owner_membership_when_missing():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    bot = User.objects.create_user(email="ace@dimagi-ai.com")
    ws = _dimagi_team(founder)

    promote_bot_to_owner(_AppShim(), schema_editor=None)

    assert WorkspaceMembership.objects.get(workspace=ws, user=bot).role == "owner"


@pytest.mark.django_db
def test_is_idempotent():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    bot = User.objects.create_user(email="ace@dimagi-ai.com")
    ws = _dimagi_team(founder)

    promote_bot_to_owner(_AppShim(), schema_editor=None)
    promote_bot_to_owner(_AppShim(), schema_editor=None)

    assert WorkspaceMembership.objects.filter(workspace=ws, user=bot).count() == 1
    assert WorkspaceMembership.objects.get(workspace=ws, user=bot).role == "owner"


@pytest.mark.django_db
def test_noop_when_workspace_or_bot_absent():
    # No workspace, no bot — must not raise.
    promote_bot_to_owner(_AppShim(), schema_editor=None)
    # Bot exists but no workspace — still a no-op.
    User.objects.create_user(email="ace@dimagi-ai.com")
    promote_bot_to_owner(_AppShim(), schema_editor=None)
    assert WorkspaceMembership.objects.count() == 0


@pytest.mark.django_db
def test_reverse_restores_editor():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    bot = User.objects.create_user(email="ace@dimagi-ai.com")
    ws = _dimagi_team(founder)
    WorkspaceMembership.objects.create(workspace=ws, user=bot, role="owner")

    demote_bot_to_editor(_AppShim(), schema_editor=None)

    assert WorkspaceMembership.objects.get(workspace=ws, user=bot).role == "editor"
