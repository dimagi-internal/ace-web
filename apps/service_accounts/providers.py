"""Credential providers — one per credential_type.

Each provider knows how to take a decrypted credential string and return
a provider-specific credential object (e.g., google.oauth2 Credentials,
a raw API key string).
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from google.oauth2 import service_account

from .exceptions import ImpersonationDenied


class CredentialProvider(Protocol):
    """Interface for credential providers."""

    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any: ...


class GoogleSAProvider:
    """Wraps google.oauth2.service_account.Credentials."""

    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any:
        info = json.loads(decrypted_credential)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=scopes,
        )
        if subject:
            creds = creds.with_subject(subject)
        return creds


class ApiKeyProvider:
    """Returns the raw key string. For services that just need a key."""

    def get_credentials(
        self,
        decrypted_credential: str,
        subject: str | None,
        scopes: list[str],
    ) -> Any:
        if subject:
            raise ImpersonationDenied("API keys do not support impersonation.")
        return decrypted_credential
