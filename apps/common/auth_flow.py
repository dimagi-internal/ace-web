"""Claude CLI credential storage.

The server does not run ``claude setup-token`` itself anymore. Instead a
developer runs ``scripts/ace_cli_login.py`` from their laptop, which reads
the already-working credentials out of the local machine's store
(macOS Keychain or Linux ~/.claude/.credentials.json) and POSTs the full
OAuth blob to ``POST /api/auth/cli/upload``. This module persists that
blob, writes it to the expected file path so ``claude -p`` reads it
natively (enabling refresh via the refresh token), and exposes a live
validation check.

Blob shape — matches what the claude CLI itself stores::

    {"claudeAiOauth": {
        "accessToken":  "sk-ant-oat01-...",
        "refreshToken": "...",
        "expiresAt":    1234567890,
        "scopes":       [...]
    }}

SystemConfig keys:
  * ``claude_credentials_blob`` — full JSON blob (canonical)
  * ``claude_oauth_token``      — extracted access token (legacy row,
    kept for deploys that predate the blob migration)

The DB is the sole source of truth. There is no ``CLAUDE_CODE_OAUTH_TOKEN``
env-var hot-cache: that path existed when only one ECS task ran per
service, but with 2+ tasks behind the ALB one task's env var would go
stale after an upload hit a different task, causing that task to keep
returning ``authenticated=false`` for the rest of its lifetime. Every
read now hits the DB so any task picks up a fresh upload on the next
call, and the ``.credentials.json`` file on disk is refreshed lazily
when the blob actually changes.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

_TOKEN_DB_KEY = "claude_oauth_token"
_BLOB_DB_KEY = "claude_credentials_blob"


# ── Blob persistence ──────────────────────────────────────────────

def store_credentials_blob(blob: dict) -> str:
    """Persist the full credential blob + extracted access token.

    Writes:
      1. SystemConfig[claude_credentials_blob] — full JSON
      2. SystemConfig[claude_oauth_token]       — access token string
      3. $ACE_CLAUDE_HOME/.claude/.credentials.json — so ``claude -p`` reads
         it natively and can refresh via the refresh token

    Returns the extracted access token.
    Raises ValueError if the blob shape is wrong or the access token is
    missing / not real.
    """
    token = _extract_access_token(blob)
    if not token_looks_real(token):
        raise ValueError(
            "Credential blob missing or malformed access token "
            "(expected claudeAiOauth.accessToken matching sk-ant-oat...)"
        )

    _invalidate_validation_cache()
    blob_json = json.dumps(blob)

    try:
        from .models import SystemConfig

        SystemConfig.objects.update_or_create(
            key=_BLOB_DB_KEY, defaults={"value": blob_json}
        )
        SystemConfig.objects.update_or_create(
            key=_TOKEN_DB_KEY, defaults={"value": token}
        )
    except Exception:
        logger.exception("Failed to persist credentials to DB")

    _write_credentials_file(blob)
    _FILE_SYNC_CACHE["blob_json"] = blob_json
    logger.info(
        "store_credentials_blob: saved (prefix=%s, token_len=%d)",
        token[:15], len(token),
    )
    return token


def _extract_access_token(blob: dict) -> str:
    """Pull the access token string out of the stored shape."""
    try:
        return blob["claudeAiOauth"]["accessToken"]
    except (KeyError, TypeError):
        return ""


def _write_credentials_file(blob: dict) -> None:
    """Write the blob to ``$HOME/.claude/.credentials.json``.

    The claude CLI reads and writes this file natively — if we keep it in
    sync, the CLI handles refresh using the stored refreshToken without
    any help from us.
    """
    from django.conf import settings

    claude_home = getattr(settings, "ACE_CLAUDE_HOME", None)
    if not claude_home:
        claude_home = os.environ.get("HOME", "")
    if not claude_home:
        logger.warning("No ACE_CLAUDE_HOME or HOME — skipping credentials file write")
        return
    path = os.path.join(claude_home, ".claude", ".credentials.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(blob, f)
        os.chmod(path, 0o600)
        logger.info("wrote credentials file: %s", path)
    except OSError:
        logger.exception("Failed to write credentials file to %s", path)


# Tracks the last blob JSON we synced to disk so repeated get_stored_token()
# calls don't rewrite .credentials.json when nothing has changed.
_FILE_SYNC_CACHE: dict = {"blob_json": None}


def get_stored_token() -> str | None:
    """Return the current access token, reading fresh from the DB on every call.

    Also ensures ``.credentials.json`` on disk reflects the current DB blob
    (required so ``claude -p`` subprocesses can authenticate and refresh
    natively). The file is only rewritten when the blob actually changes,
    so the hot path is a single SELECT.
    """
    try:
        from .models import SystemConfig

        row = SystemConfig.objects.filter(key=_BLOB_DB_KEY).first()
        if row and row.value:
            if _FILE_SYNC_CACHE.get("blob_json") != row.value:
                try:
                    blob = json.loads(row.value)
                except ValueError:
                    logger.warning("stored credentials blob is not valid JSON")
                    return None
                token = _extract_access_token(blob)
                if not token:
                    return None
                _write_credentials_file(blob)
                _FILE_SYNC_CACHE["blob_json"] = row.value
                return token
            return _extract_access_token(json.loads(row.value)) or None

        # Legacy token-only row — for deploys that predate the blob
        # migration. No credentials file to write in this case (we don't
        # have the refreshToken), so claude -p can't auto-refresh. Still
        # usable until the token expires, at which point the user needs
        # to re-upload via scripts/ace_cli_login.py.
        legacy = SystemConfig.objects.filter(key=_TOKEN_DB_KEY).first()
        if legacy and legacy.value:
            return legacy.value
    except Exception:
        logger.debug("Could not load credentials (migrations may not have run)")
    return None


# Kept as an alias so older callers (and a stable import surface) continue
# to work. The DB is the sole source of truth — this is now just
# get_stored_token() under a legacy name.
load_stored_token = get_stored_token


def token_looks_real(token: str | None) -> bool:
    """Cheap format check — rejects empty, placeholders, obvious junk."""
    if not token:
        return False
    if not token.startswith("sk-ant-oat"):
        return False
    if len(token) < 40:
        return False
    if "placeholder" in token.lower():
        return False
    return True


# ── Live validation (cached) ──────────────────────────────────────

# Positive results are cached for longer — running ``claude -p`` once per
# 30-second status poll would thrash the CLI and is wasted work when the
# token is clearly valid. Negative results are cached briefly so recovery
# after a fresh upload happens within seconds rather than minutes.
_POSITIVE_CACHE_TTL = float(os.environ.get("ACE_TOKEN_VALIDATION_TTL", "300"))
_NEGATIVE_CACHE_TTL = float(os.environ.get("ACE_TOKEN_VALIDATION_NEGATIVE_TTL", "15"))
_validation_cache: dict = {"valid": False, "checked_at": 0.0, "token": ""}


def _invalidate_validation_cache() -> None:
    _validation_cache["checked_at"] = 0.0
    _validation_cache["token"] = ""


def validate_stored_token() -> bool:
    """Return True only if the stored token passes a live CLI check.

    Runs ``claude -p "ok"`` as a subprocess — same auth path as real chat
    — and looks for a ``result`` event with ``subtype == "success"`` and no
    auth-error markers. ``store_credentials_blob`` invalidates the cache on
    write, and because ``get_stored_token()`` always reads fresh from the
    DB, other tasks pick up the new token on their next call (the cache
    key is the token value, so a DB change naturally invalidates stale
    cached verdicts).
    """
    token = get_stored_token()
    logger.info(
        "validate_stored_token: token_present=%s, looks_real=%s, prefix=%s",
        bool(token), token_looks_real(token),
        token[:15] + "..." if token else "None",
    )
    if not token_looks_real(token):
        return False

    now = time.time()
    cached_age = now - _validation_cache["checked_at"]
    cache_ttl = _POSITIVE_CACHE_TTL if _validation_cache["valid"] else _NEGATIVE_CACHE_TTL
    if _validation_cache["token"] == token and cached_age < cache_ttl:
        logger.info(
            "validate_stored_token: returning cached result=%s (age=%.0fs, ttl=%ds)",
            _validation_cache["valid"], cached_age, int(cache_ttl),
        )
        return _validation_cache["valid"]

    logger.info("validate_stored_token: cache miss, running CLI check")
    valid = _check_token_via_cli()
    _validation_cache.update(valid=valid, checked_at=now, token=token)
    logger.info("validate_stored_token: token %s CLI check", "PASSED" if valid else "FAILED")
    return valid


# Public canonical name. Both /api/auth/cli/status and the chat backend
# selector call this so they never disagree on "is the CLI usable?".
cli_is_ready = validate_stored_token


def _check_token_via_cli() -> bool:
    """Run ``claude -p "ok"`` and look for a successful terminal result."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    from django.conf import settings

    claude_home = getattr(settings, "ACE_CLAUDE_HOME", None)
    if claude_home:
        env["HOME"] = claude_home

    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "stream-json", "--verbose", "ok"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("claude -p probe failed: %s", exc)
        return False

    if proc.returncode != 0:
        logger.warning(
            "claude -p returned %d: stdout=%r stderr=%r",
            proc.returncode, proc.stdout[:300], proc.stderr[:300],
        )
        return False

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result" and event.get("subtype") == "success":
            return True

    logger.warning("claude -p emitted no success result")
    return False
