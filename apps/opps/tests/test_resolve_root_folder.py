"""Tests for _resolve_ace_root_folder_id in apps/opps/views.py.

After multi-tenancy (Phase A, 2026-04-27), the resolver reads from a
Workspace's `drive_root_folder_id` instead of `settings.ACE_DRIVE_ROOT_FOLDER_ID`.
The settings value is now a migration-only seed, not a runtime value.
"""
from types import SimpleNamespace

from apps.opps.views import _resolve_ace_root_folder_id


def test_returns_workspace_drive_root_folder_id():
    ws = SimpleNamespace(drive_root_folder_id="folder-from-workspace")
    assert _resolve_ace_root_folder_id(ws) == "folder-from-workspace"


def test_returns_none_when_workspace_is_none():
    assert _resolve_ace_root_folder_id(None) is None


def test_returns_none_when_drive_root_folder_id_is_empty():
    ws = SimpleNamespace(drive_root_folder_id="")
    assert _resolve_ace_root_folder_id(ws) is None


def test_default_setting_is_empty_string():
    """ACE_DRIVE_ROOT_FOLDER_ID is migration-only (read by
    apps/workspaces/migrations/0002_seed_dimagi_team.py to seed the founding
    workspace) and not used at runtime. The default is empty so the public
    repo doesn't embed any specific tenant's folder id; deployments that
    need the seed inject it via the env (e.g. AWS Secrets Manager). The
    seed migration handles an empty value by skipping the seed."""
    from django.conf import settings

    assert settings.ACE_DRIVE_ROOT_FOLDER_ID == ""
