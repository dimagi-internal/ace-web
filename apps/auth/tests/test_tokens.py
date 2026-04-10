import hashlib

import pytest

from apps.auth.models import PersonalToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


def test_create_token_returns_raw(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    assert len(raw) >= 32
    assert token.pk is not None
    assert token.user == user
    assert token.label == "test"
    assert token.revoked_at is None


def test_raw_token_is_not_stored(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()
    assert token.token_hash == expected_hash


def test_lookup_by_raw_token(user):
    raw, created = PersonalToken.create_for_user(user=user, label="test")
    found = PersonalToken.lookup(raw)
    assert found is not None
    assert found.pk == created.pk


def test_lookup_returns_none_for_bad_token(user):
    PersonalToken.create_for_user(user=user, label="test")
    assert PersonalToken.lookup("bad-token-value") is None


def test_lookup_returns_none_for_revoked(user):
    from django.utils import timezone
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    token.revoked_at = timezone.now()
    token.save()
    assert PersonalToken.lookup(raw) is None
