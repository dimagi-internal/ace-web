import json
from unittest.mock import MagicMock, patch

import pytest

from apps.service_accounts.exceptions import ImpersonationDenied
from apps.service_accounts.providers import ApiKeyProvider, GoogleSAProvider


class TestGoogleSAProvider:
    def test_returns_credentials_without_subject(self):
        fake_key = json.dumps({
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIE...\n-----END RSA PRIVATE KEY-----\n",
            "client_email": "test@test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        provider = GoogleSAProvider()
        with patch("apps.service_accounts.providers.service_account") as mock_sa:
            mock_creds = MagicMock()
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            result = provider.get_credentials(fake_key, subject=None, scopes=["drive"])
            mock_sa.Credentials.from_service_account_info.assert_called_once_with(
                json.loads(fake_key), scopes=["drive"],
            )
            mock_creds.with_subject.assert_not_called()
            assert result is mock_creds

    def test_returns_delegated_credentials_with_subject(self):
        fake_key = json.dumps({"type": "service_account", "project_id": "test"})
        provider = GoogleSAProvider()
        with patch("apps.service_accounts.providers.service_account") as mock_sa:
            mock_creds = MagicMock()
            mock_delegated = MagicMock()
            mock_sa.Credentials.from_service_account_info.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_delegated
            result = provider.get_credentials(
                fake_key, subject="alice@dimagi.com", scopes=["drive"],
            )
            mock_creds.with_subject.assert_called_once_with("alice@dimagi.com")
            assert result is mock_delegated


class TestApiKeyProvider:
    def test_returns_raw_key(self):
        provider = ApiKeyProvider()
        result = provider.get_credentials("my-api-key-123", subject=None, scopes=[])
        assert result == "my-api-key-123"

    def test_rejects_impersonation(self):
        provider = ApiKeyProvider()
        with pytest.raises(ImpersonationDenied):
            provider.get_credentials(
                "my-api-key-123", subject="alice@dimagi.com", scopes=[],
            )
