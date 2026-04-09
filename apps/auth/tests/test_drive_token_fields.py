import pytest

from apps.auth.models import User


@pytest.mark.django_db
def test_drive_token_cache_defaults_to_empty_string():
    """drive_token_cache should default to an empty string."""
    user = User.objects.create_user(email="user@example.com", display_name="Test User")
    assert user.drive_token_cache == ""


@pytest.mark.django_db
def test_drive_token_cache_can_store_and_retrieve():
    """drive_token_cache should accept and persist arbitrary string values."""
    user = User.objects.create_user(email="user@example.com", display_name="Test User")
    user.drive_token_cache = "encrypted-token-value"
    user.save()

    user.refresh_from_db()
    assert user.drive_token_cache == "encrypted-token-value"


@pytest.mark.django_db
def test_has_drive_token_helper_method():
    """has_drive_token() should return True iff drive_token_cache is non-empty."""
    user = User.objects.create_user(email="user@example.com", display_name="Test User")

    # Empty cache should return False
    assert not user.has_drive_token()

    # Non-empty cache should return True
    user.drive_token_cache = "some-token"
    assert user.has_drive_token()

    # Empty string should return False
    user.drive_token_cache = ""
    assert not user.has_drive_token()
