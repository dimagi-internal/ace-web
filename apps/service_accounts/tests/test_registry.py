from datetime import timedelta

import pytest
from django.utils import timezone

from apps.service_accounts.encryption import encrypt
from apps.service_accounts.exceptions import (
    ImpersonationDenied,
    InvalidScope,
    ServiceAccountNotFound,
)
from apps.service_accounts.models import (
    AccessLog,
    ImpersonationGrant,
    ServiceAccount,
)
from apps.service_accounts.registry import get_credentials

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa():
    return ServiceAccount.objects.create(
        name="test-sa",
        credential_type="api_key",
        credential_encrypted=encrypt("my-secret-key"),
        default_scopes=["read", "write"],
    )


@pytest.fixture
def sa_with_grant(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    return sa


# --- direct access ---

def test_direct_access_returns_credential(sa):
    result = get_credentials("test-sa")
    assert result == "my-secret-key"


def test_direct_access_logs(sa):
    get_credentials("test-sa", context={"caller": "test"})
    log = AccessLog.objects.get()
    assert log.action == "direct_access"
    assert log.subject == ""
    assert log.scopes_used == ["read", "write"]
    assert log.context == {"caller": "test"}


def test_missing_sa_raises():
    with pytest.raises(ServiceAccountNotFound):
        get_credentials("nonexistent")


def test_inactive_sa_raises(sa):
    sa.is_active = False
    sa.save()
    with pytest.raises(ServiceAccountNotFound):
        get_credentials("test-sa")


# --- impersonation ---

def test_impersonation_with_valid_grant(sa_with_grant):
    sa_with_grant.credential_type = "api_key"
    sa_with_grant.save()
    with pytest.raises(ImpersonationDenied, match="API keys do not support"):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")
    assert AccessLog.objects.filter(action="impersonation").exists()


def test_impersonation_denied_no_grant(sa):
    with pytest.raises(ImpersonationDenied):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")


def test_impersonation_denied_revoked_grant(sa_with_grant):
    grant = sa_with_grant.grants.first()
    grant.revoked_at = timezone.now()
    grant.save()
    with pytest.raises(ImpersonationDenied):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")


def test_impersonation_denied_expired_grant(sa_with_grant):
    grant = sa_with_grant.grants.first()
    grant.expires_at = timezone.now() - timedelta(hours=1)
    grant.save()
    with pytest.raises(ImpersonationDenied):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")


def test_wildcard_grant_matches():
    sa = ServiceAccount.objects.create(
        name="wildcard-sa",
        credential_type="api_key",
        credential_encrypted=encrypt("key"),
        default_scopes=["read"],
    )
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="*@dimagi.com",
        scopes=["read"],
    )
    with pytest.raises(ImpersonationDenied, match="API keys do not support"):
        get_credentials("wildcard-sa", on_behalf_of="anyone@dimagi.com")
    assert AccessLog.objects.filter(
        action="impersonation", subject="anyone@dimagi.com"
    ).exists()


def test_wildcard_grant_rejects_wrong_domain():
    sa = ServiceAccount.objects.create(
        name="wildcard-sa-2",
        credential_type="api_key",
        credential_encrypted=encrypt("key"),
        default_scopes=["read"],
    )
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="*@dimagi.com",
        scopes=["read"],
    )
    with pytest.raises(ImpersonationDenied):
        get_credentials("wildcard-sa-2", on_behalf_of="anyone@evil.com")
    assert not AccessLog.objects.filter(subject="anyone@evil.com").exists()


def test_case_insensitive_grant_match(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="Alice@Dimagi.com",
        scopes=["read"],
    )
    with pytest.raises(ImpersonationDenied, match="API keys do not support"):
        get_credentials("test-sa", on_behalf_of="alice@dimagi.com")
    assert AccessLog.objects.filter(action="impersonation").exists()


# --- scope validation ---

def test_explicit_scopes_subset(sa):
    result = get_credentials("test-sa", scopes=["read"])
    assert result == "my-secret-key"
    log = AccessLog.objects.get()
    assert log.scopes_used == ["read"]


def test_explicit_scopes_exceed_default_raises(sa):
    with pytest.raises(InvalidScope):
        get_credentials("test-sa", scopes=["admin"])


def test_impersonation_scopes_exceed_grant_raises(sa):
    ImpersonationGrant.objects.create(
        service_account=sa,
        subject_pattern="alice@dimagi.com",
        scopes=["read"],
    )
    with pytest.raises(InvalidScope):
        get_credentials(
            "test-sa",
            on_behalf_of="alice@dimagi.com",
            scopes=["write"],
        )
