import pytest
from django.utils import timezone

from apps.service_accounts.models import (
    AccessLog,
    ImpersonationGrant,
    ServiceAccount,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa():
    return ServiceAccount.objects.create(
        name="test-sa",
        credential_type="api_key",
        credential_encrypted="not-real-encrypted",
        default_scopes=["read"],
    )


def test_create_service_account(sa):
    assert sa.name == "test-sa"
    assert sa.is_active is True
    assert sa.default_scopes == ["read"]


def test_service_account_name_is_unique(sa):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        ServiceAccount.objects.create(
            name="test-sa",
            credential_type="api_key",
            credential_encrypted="x",
        )


def test_credential_json_property():
    from apps.service_accounts.encryption import encrypt

    raw = '{"key": "secret"}'
    sa = ServiceAccount.objects.create(
        name="prop-test",
        credential_type="google_sa",
        credential_encrypted=encrypt(raw),
        default_scopes=["drive"],
    )
    assert sa.credential_json == raw


def test_credential_json_setter():
    sa = ServiceAccount(
        name="setter-test",
        credential_type="api_key",
    )
    sa.credential_json = "my-api-key"
    sa.save()
    sa.refresh_from_db()
    assert sa.credential_json == "my-api-key"


def test_create_grant(sa):
    grant = ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    assert grant.revoked_at is None
    assert grant.expires_at is None


def test_grant_revocation(sa):
    grant = ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    grant.revoked_at = timezone.now()
    grant.save()
    grant.refresh_from_db()
    assert grant.revoked_at is not None


def test_access_log_creation(sa):
    log = AccessLog.objects.create(
        service_account=sa,
        action="direct_access",
        scopes_used=["read"],
        context={"caller": "test"},
    )
    assert log.subject == ""
    assert log.context == {"caller": "test"}


def test_cascade_delete(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="*@dimagi.com",
        scopes=["read"],
    )
    AccessLog.objects.create(
        service_account=sa,
        action="direct_access",
        scopes_used=["read"],
    )
    sa.delete()
    assert ImpersonationGrant.objects.count() == 0
    assert AccessLog.objects.count() == 0
