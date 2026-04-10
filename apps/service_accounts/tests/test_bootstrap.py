import pytest

from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.service_accounts.models import ServiceAccount
from apps.service_accounts.registry import get_credentials

pytestmark = pytest.mark.django_db


def test_bootstrap_creates_sa_from_env(settings, monkeypatch):
    monkeypatch.setenv("ACE_DRIVE_SA_KEY_JSON", "test-key-json")
    settings.SERVICE_ACCOUNTS = {
        "PROVIDERS": {
            "api_key": "apps.service_accounts.providers.ApiKeyProvider",
        },
        "BOOTSTRAP_FROM_ENV": {
            "bootstrap-test": {
                "credential_type": "api_key",
                "env_var": "ACE_DRIVE_SA_KEY_JSON",
                "default_scopes": ["read"],
            },
        },
    }
    result = get_credentials("bootstrap-test")
    assert result == "test-key-json"
    assert ServiceAccount.objects.filter(name="bootstrap-test").exists()


def test_bootstrap_is_idempotent(settings, monkeypatch):
    monkeypatch.setenv("ACE_DRIVE_SA_KEY_JSON", "first-value")
    settings.SERVICE_ACCOUNTS = {
        "PROVIDERS": {
            "api_key": "apps.service_accounts.providers.ApiKeyProvider",
        },
        "BOOTSTRAP_FROM_ENV": {
            "idempotent-test": {
                "credential_type": "api_key",
                "env_var": "ACE_DRIVE_SA_KEY_JSON",
                "default_scopes": ["read"],
            },
        },
    }
    get_credentials("idempotent-test")
    monkeypatch.setenv("ACE_DRIVE_SA_KEY_JSON", "second-value")
    result = get_credentials("idempotent-test")
    assert result == "first-value"


def test_bootstrap_missing_env_var_raises(settings, monkeypatch):
    monkeypatch.delenv("ACE_DRIVE_SA_KEY_JSON", raising=False)
    settings.ACE_DRIVE_SA_KEY_JSON = ""
    settings.SERVICE_ACCOUNTS = {
        "PROVIDERS": {},
        "BOOTSTRAP_FROM_ENV": {
            "missing-env": {
                "credential_type": "api_key",
                "env_var": "ACE_DRIVE_SA_KEY_JSON",
                "default_scopes": [],
            },
        },
    }
    with pytest.raises(ServiceAccountNotFound):
        get_credentials("missing-env")
