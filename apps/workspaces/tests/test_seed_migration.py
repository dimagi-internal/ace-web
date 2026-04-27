"""Smoke tests for the seed-and-backfill data migration.

We invoke the migration's `seed_and_backfill` function directly with a
shim `apps` object that returns the live Django models, rather than
running the migration through migrate. The function's logic doesn't
depend on the historical schema, so this is sufficient and much faster.
"""
import importlib

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.opps.models import OppWorkspace
from apps.sessions.models import IngestUpload, Session, ShareToken
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
def test_seed_creates_dimagi_team_and_backfills_opp():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    User.objects.create_user(email="ace@dimagi-ai.com")
    opp = OppWorkspace.objects.create(
        slug="acme-opp", display_name="ACME", created_by=founder,
    )

    seed_and_backfill(_AppShim(), schema_editor=None)

    ws = Workspace.objects.get(slug="dimagi-team")
    assert ws.drive_root_folder_id == "folder-test-1"
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user=founder, role="owner",
    ).exists()
    assert WorkspaceMembership.objects.filter(
        workspace=ws, user__email="ace@dimagi-ai.com", role="editor",
    ).exists()

    opp.refresh_from_db()
    assert opp.workspace == ws


@pytest.mark.django_db
@override_settings(ACE_DRIVE_ROOT_FOLDER_ID="folder-test-2")
def test_seed_backfills_session_share_token_and_upload():
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    OppWorkspace.objects.create(
        slug="acme-opp", display_name="ACME", created_by=founder,
    )
    session = Session.objects.create(
        title="seed-test", owner=founder, opp_slug="acme-opp",
    )
    tok = ShareToken.objects.create(session=session, created_by=founder)
    upload = IngestUpload.objects.create(
        session=session, uploaded_by=founder, line_count=1, raw_bytes=10,
    )

    seed_and_backfill(_AppShim(), schema_editor=None)

    ws = Workspace.objects.get(slug="dimagi-team")
    session.refresh_from_db()
    assert session.workspace == ws
    tok.refresh_from_db()
    assert tok.workspace == ws
    upload.refresh_from_db()
    assert upload.workspace == ws


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
