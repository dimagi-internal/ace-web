"""Tests for _resolve_ace_root_folder_id in apps/opps/views.py.

These tests exercise the UNPATCHED resolver — the existing view tests
(test_views_opp_list / test_views_workbench / etc.) patch this function
to inject a fake folder id from FakeDriveClient, which is the right thing
for those tests. This file locks in the production behavior: the resolver
reads directly from settings.ACE_DRIVE_ROOT_FOLDER_ID.
"""
from unittest.mock import MagicMock

from django.test import override_settings

from apps.opps.views import _resolve_ace_root_folder_id


def test_returns_pinned_folder_id_from_settings():
    with override_settings(ACE_DRIVE_ROOT_FOLDER_ID="pinned-folder-123"):
        assert _resolve_ace_root_folder_id(MagicMock()) == "pinned-folder-123"


def test_returns_none_when_setting_is_empty():
    with override_settings(ACE_DRIVE_ROOT_FOLDER_ID=""):
        assert _resolve_ace_root_folder_id(MagicMock()) is None


def test_default_setting_is_the_shared_ace_folder_id():
    """The settings default should be the real shared ACE Drive folder id.

    If someone changes the default without coordinating with the team, this
    test fails loudly so the change is deliberate.
    """
    from django.conf import settings

    # Intentional literal — matches the folder id the team uses in prod.
    # If this needs to change, update the setting default AND this assertion
    # AND communicate it to the team. The setting is still env-overridable.
    assert settings.ACE_DRIVE_ROOT_FOLDER_ID == "1HThsA_0Lr5p1OdI5r-aQ446HlNBaySLz"


def test_ignores_client_argument():
    """The client arg is retained for a future name-based fallback but is
    currently unused. Passing None should still work."""
    with override_settings(ACE_DRIVE_ROOT_FOLDER_ID="pinned-folder-xyz"):
        assert _resolve_ace_root_folder_id(None) == "pinned-folder-xyz"  # type: ignore[arg-type]
