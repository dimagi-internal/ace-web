"""Tests for the mint_personal_token management command."""
import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.auth.models import PersonalToken, User


def _run(**kwargs):
    out = io.StringIO()
    call_command("mint_personal_token", stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
def test_mints_token_that_authenticates_for_existing_user():
    user = User.objects.create_user(email="ace@dimagi-ai.com")
    output = _run(email="ace@dimagi-ai.com", label="ace-bot")

    tokens = PersonalToken.objects.filter(user=user, label="ace-bot", revoked_at__isnull=True)
    assert tokens.count() == 1
    # The printed raw token must resolve back to this token via lookup().
    raw = output.strip().splitlines()[-1]
    resolved = PersonalToken.lookup(raw)
    assert resolved is not None
    assert resolved.user == user


@pytest.mark.django_db
def test_errors_when_user_absent_without_create_flag():
    with pytest.raises(CommandError):
        _run(email="nobody@dimagi-ai.com", label="ace-bot")
    assert PersonalToken.objects.count() == 0


@pytest.mark.django_db
def test_create_user_bootstraps_principal():
    _run(email="ace@dimagi-ai.com", label="ace-bot", create_user=True)
    user = User.objects.get(email="ace@dimagi-ai.com")
    assert user.display_name == "ace"
    assert PersonalToken.objects.filter(user=user, label="ace-bot").count() == 1


@pytest.mark.django_db
def test_rotate_revokes_prior_active_tokens_with_same_label():
    user = User.objects.create_user(email="ace@dimagi-ai.com")
    _run(email="ace@dimagi-ai.com", label="ace-bot")
    _run(email="ace@dimagi-ai.com", label="ace-bot", rotate=True)

    active = PersonalToken.objects.filter(user=user, label="ace-bot", revoked_at__isnull=True)
    revoked = PersonalToken.objects.filter(user=user, label="ace-bot", revoked_at__isnull=False)
    assert active.count() == 1
    assert revoked.count() == 1


@pytest.mark.django_db
def test_rotate_leaves_other_labels_untouched():
    user = User.objects.create_user(email="ace@dimagi-ai.com")
    _run(email="ace@dimagi-ai.com", label="other")
    _run(email="ace@dimagi-ai.com", label="ace-bot", rotate=True)
    assert PersonalToken.objects.filter(
        user=user, label="other", revoked_at__isnull=True
    ).count() == 1
