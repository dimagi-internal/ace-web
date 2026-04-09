"""Tests for DRF permissions used by the Workbench API."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

User = get_user_model()


@pytest.fixture
def user_without_token(db):
    u = User.objects.create(email="alice@dimagi.com", display_name="Alice")
    return u


@pytest.fixture
def user_with_token(db):
    u = User.objects.create(email="neal@dimagi.com", display_name="Neal")
    u.drive_token_cache = "some-ciphertext"
    u.save()
    return u


def test_denies_unauthenticated(db):
    from apps.opps.middleware import RequireDriveToken

    perm = RequireDriveToken()
    factory = APIRequestFactory()
    request = factory.get("/api/opps/")
    request.user = None
    assert perm.has_permission(request, view=None) is False


def test_denies_user_without_drive_token(user_without_token):
    from apps.opps.middleware import RequireDriveToken

    perm = RequireDriveToken()
    factory = APIRequestFactory()
    request = factory.get("/api/opps/")
    request.user = user_without_token
    assert perm.has_permission(request, view=None) is False


def test_allows_user_with_drive_token(user_with_token):
    from apps.opps.middleware import RequireDriveToken

    perm = RequireDriveToken()
    factory = APIRequestFactory()
    request = factory.get("/api/opps/")
    request.user = user_with_token
    assert perm.has_permission(request, view=None) is True


def test_denied_response_contains_reconnect_url():
    """When a view uses this permission and access is denied, the error body
    should include a reconnect URL so the frontend can redirect the user."""
    from apps.opps.middleware import RequireDriveToken

    perm = RequireDriveToken()
    # The permission itself just returns False; the reconnect hint is provided
    # via a custom exception raised by the view's permission_denied handler.
    # That handler is exposed via get_reconnect_payload() on the permission.
    payload = perm.get_reconnect_payload()
    assert payload == {"reconnect_url": "/auth/drive/start"}
