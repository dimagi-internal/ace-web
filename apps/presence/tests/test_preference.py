import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db.utils import IntegrityError

from apps.presence.models import PresencePreference, show_presence_for

pytestmark = pytest.mark.django_db


def _user(email="a@x.com"):
    return get_user_model().objects.create_user(email=email, display_name="A")


def test_defaults_to_visible_when_no_row_exists():
    assert show_presence_for(_user()) is True


def test_honours_an_explicit_opt_out():
    user = _user()
    PresencePreference.objects.create(user=user, show_presence=False)
    assert show_presence_for(user) is False


def test_a_user_has_at_most_one_preference_row():
    user = _user()
    PresencePreference.objects.create(user=user, show_presence=False)
    with pytest.raises(IntegrityError):
        PresencePreference.objects.create(user=user, show_presence=True)


def test_defaults_to_visible_for_anonymous_user():
    assert show_presence_for(AnonymousUser()) is True


def test_defaults_to_visible_for_unsaved_user_instance():
    assert show_presence_for(get_user_model()(email="unsaved@x.com")) is True
