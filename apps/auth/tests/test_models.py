import pytest
from django.db import IntegrityError

from apps.auth.models import User


@pytest.mark.django_db
def test_create_user_normalizes_email_and_sets_unusable_password():
    user = User.objects.create_user(email="JJ@Example.com", display_name="Jonathan")
    assert user.email == "JJ@example.com"
    assert user.display_name == "Jonathan"
    assert not user.has_usable_password()


@pytest.mark.django_db
def test_email_is_unique():
    User.objects.create_user(email="a@b.c")
    with pytest.raises(IntegrityError):
        User.objects.create_user(email="a@b.c")


@pytest.mark.django_db
def test_two_users_without_google_sub_can_coexist():
    """Empty/None google_sub must not collide on the UNIQUE constraint."""
    User.objects.create_user(email="one@example.com")
    User.objects.create_user(email="two@example.com")
    # Both should succeed; assert both rows exist with NULL google_sub.
    assert User.objects.filter(google_sub__isnull=True).count() == 2
