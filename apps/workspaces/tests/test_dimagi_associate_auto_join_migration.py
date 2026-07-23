"""Tests for the 0006 dimagi-associate auto-join data migration.

Invokes the migration's functions directly with a shim `apps` object (same
pattern as test_seed_migration / test_promote_ace_owner_migration), since the
logic doesn't depend on the historical schema.

The load-bearing property is APPEND-ONLY: unlike 0004, this migration must not
clobber `auto_join_domains` entries an Owner added via the Workspace Settings
page or PATCH /api/workspaces/{slug}.
"""
import importlib

import pytest
from django.contrib.auth import get_user_model

from apps.workspaces.models import Workspace

User = get_user_model()

_mod = importlib.import_module("apps.workspaces.migrations.0006_dimagi_associate_auto_join")
add_associate_domain = _mod.add_associate_domain
remove_associate_domain = _mod.remove_associate_domain


class _AppShim:
    def get_model(self, app_label, name):
        from django.apps import apps as django_apps
        return django_apps.get_model(app_label, name)


def _dimagi_team(domains):
    founder = User.objects.create_user(email="jjackson@dimagi.com")
    return Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-x",
        created_by=founder,
        auto_join_domains=domains,
    )


@pytest.mark.django_db
def test_appends_associate_domain_to_seeded_list():
    ws = _dimagi_team(["dimagi.com", "dimagi-ai.com"])

    add_associate_domain(_AppShim(), schema_editor=None)

    ws.refresh_from_db()
    assert ws.auto_join_domains == [
        "dimagi.com",
        "dimagi-ai.com",
        "dimagi-associate.com",
    ]


@pytest.mark.django_db
def test_preserves_operator_added_domains():
    """An Owner-edited list must survive — this is why we append, not overwrite."""
    ws = _dimagi_team(["dimagi.com", "dimagi-ai.com", "partner.example.org"])

    add_associate_domain(_AppShim(), schema_editor=None)

    ws.refresh_from_db()
    assert "partner.example.org" in ws.auto_join_domains
    assert "dimagi-associate.com" in ws.auto_join_domains


@pytest.mark.django_db
def test_is_idempotent():
    ws = _dimagi_team(["dimagi.com"])

    add_associate_domain(_AppShim(), schema_editor=None)
    add_associate_domain(_AppShim(), schema_editor=None)

    ws.refresh_from_db()
    assert ws.auto_join_domains.count("dimagi-associate.com") == 1


@pytest.mark.django_db
def test_dedupes_against_differently_formatted_existing_entry():
    """An operator may have typed "@Dimagi-Associate.com" in the settings UI."""
    ws = _dimagi_team(["dimagi.com", "@Dimagi-Associate.com "])

    add_associate_domain(_AppShim(), schema_editor=None)

    ws.refresh_from_db()
    assert ws.auto_join_domains == ["dimagi.com", "@Dimagi-Associate.com "]


@pytest.mark.django_db
def test_noop_when_workspace_absent():
    # Fresh install / test DB — must not raise.
    add_associate_domain(_AppShim(), schema_editor=None)
    remove_associate_domain(_AppShim(), schema_editor=None)
    assert Workspace.objects.count() == 0


@pytest.mark.django_db
def test_reverse_removes_only_the_associate_domain():
    ws = _dimagi_team(["dimagi.com", "dimagi-ai.com", "dimagi-associate.com"])

    remove_associate_domain(_AppShim(), schema_editor=None)

    ws.refresh_from_db()
    assert ws.auto_join_domains == ["dimagi.com", "dimagi-ai.com"]
