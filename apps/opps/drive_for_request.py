"""Build a GoogleDriveClient scoped to the current request's user.

Encapsulates the decrypt → refresh → re-encrypt → instantiate sequence so
every view has one line instead of six.
"""
from __future__ import annotations

from datetime import UTC, datetime

from apps.opps.drive_client import GoogleDriveClient
from apps.opps.drive_credentials import (
    CredentialsRefreshFailed,
    ensure_fresh,
)
from apps.opps.encryption import decrypt_token, encrypt_token


class DriveTokenMissing(RuntimeError):
    pass


def get_drive_client_for(user) -> GoogleDriveClient:
    """Return a GoogleDriveClient using the user's cached OAuth credentials.

    Raises DriveTokenMissing if the user has no token.
    Raises CredentialsRefreshFailed if the refresh-token exchange fails.
    """
    if not getattr(user, "drive_token_cache", ""):
        raise DriveTokenMissing("user has no cached Drive token")

    token_data = decrypt_token(user.drive_token_cache)
    try:
        creds, updated = ensure_fresh(token_data)
    except CredentialsRefreshFailed:
        raise

    if updated is not None:
        user.drive_token_cache = encrypt_token(updated)
        user.drive_token_refreshed_at = datetime.now(UTC)
        user.save(update_fields=["drive_token_cache", "drive_token_refreshed_at"])

    return GoogleDriveClient(creds)
