import pytest

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
    with pytest.raises(Exception):
        User.objects.create_user(email="a@b.c")
