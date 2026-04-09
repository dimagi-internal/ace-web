"""Google OAuth credentials construction and refresh.

Two public helpers:

- `build_credentials(token_data)` — builds a google.oauth2.credentials.Credentials
  instance from a persisted token dict + the OAuth client ID/secret in settings.
  Used wherever callers need raw credentials (e.g. to pass into GoogleDriveClient).

- `ensure_fresh(token_data) -> (creds, updated_token_data | None)` — builds
  credentials and refreshes the access token if it has expired (60-second buffer).
  Returns (credentials, None) if no refresh was needed; (credentials, new_token_data)
  if the caller should persist the refreshed token back to the User row.

Refresh failures raise `CredentialsRefreshFailed`; the middleware catches this
and redirects the user to /auth/drive/start with a "reconnect" banner.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


class CredentialsRefreshFailed(RuntimeError):
    """Raised when the refresh-token exchange fails (revoked grant, network, etc)."""


def _require_client_config() -> tuple[str, str]:
    cid = settings.ACE_GOOGLE_OAUTH_CLIENT_ID
    cs = settings.ACE_GOOGLE_OAUTH_CLIENT_SECRET
    if not cid or not cs:
        raise RuntimeError(
            "Google OAuth client is not configured: set "
            "ACE_GOOGLE_OAUTH_CLIENT_ID and ACE_GOOGLE_OAUTH_CLIENT_SECRET"
        )
    return cid, cs


def build_credentials(token_data: dict) -> Credentials:
    """Build Credentials from a persisted token_data dict.

    token_data shape (exactly what the callback view stores):
        {
            "access_token": str,
            "refresh_token": str | None,
            "token_uri": str,
            "scopes": list[str],
            "expiry": str | None,  # ISO-8601, may be absent for never-expired tokens
        }
    """
    cid, cs = _require_client_config()
    expiry_iso = token_data.get("expiry")
    expiry = None
    if expiry_iso:
        # google-auth expects a naive UTC datetime, not tz-aware.
        dt = datetime.fromisoformat(expiry_iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        expiry = dt
    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=cid,
        client_secret=cs,
        scopes=token_data.get("scopes"),
        expiry=expiry,
    )
    return creds


def ensure_fresh(token_data: dict) -> tuple[Credentials, dict | None]:
    """Return (credentials, updated_token_data_or_None).

    If the access token is still valid (with a 60-second buffer), returns
    (creds, None). Otherwise refreshes via the refresh token and returns
    (creds, new_token_data) — callers must persist the new dict.
    """
    creds = build_credentials(token_data)
    if creds.expiry is None:
        return creds, None

    # google-auth uses naive UTC for expiry comparisons.
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    buffer = timedelta(seconds=60)
    if creds.expiry - buffer > now_naive:
        return creds, None

    try:
        creds.refresh(Request())
    except Exception as exc:
        raise CredentialsRefreshFailed(str(exc)) from exc

    new_expiry_iso = None
    if creds.expiry is not None:
        new_expiry_iso = creds.expiry.replace(tzinfo=UTC).isoformat()

    updated = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token or token_data.get("refresh_token"),
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes) if creds.scopes else token_data.get("scopes"),
        "expiry": new_expiry_iso,
    }
    return creds, updated
