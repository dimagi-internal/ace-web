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
  * ``claude_oauth_token``      — extracted access token (legacy, env-var path)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)

_TOKEN_DB_KEY = "claude_oauth_token"

_TOKEN_REDACT_PATTERN = re.compile(r"sk-ant-oat\S+")


def _redact_token(text: str) -> str:
    """Replace any sk-ant-oat... token in text with a placeholder.

    Defense-in-depth for log lines that dump CLI subprocess stdout/stderr —
    today's claude binary doesn't echo the bearer token, but a future version
    that does would leak via these logs without this scrub.
    """
    return _TOKEN_REDACT_PATTERN.sub("sk-ant-oat[REDACTED]", text)
_BLOB_DB_KEY = "claude_credentials_blob"


# ── Blob persistence ──────────────────────────────────────────────

def store_credentials_blob(blob: dict) -> str:
    """Persist the full credential blob + extracted access token.

    Writes:
      1. SystemConfig[claude_credentials_blob] — full JSON
      2. SystemConfig[claude_oauth_token]       — access token string
      3. $ACE_CLAUDE_HOME/.claude/.credentials.json — so ``claude -p`` reads
         it natively and can refresh via the refresh token
      4. os.environ[CLAUDE_CODE_OAUTH_TOKEN]    — hot-cache for subprocess

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

    try:
        from .models import SystemConfig

        SystemConfig.objects.update_or_create(
            key=_BLOB_DB_KEY, defaults={"value": json.dumps(blob)}
        )
        SystemConfig.objects.update_or_create(
            key=_TOKEN_DB_KEY, defaults={"value": token}
        )
    except Exception:
        logger.exception("Failed to persist credentials to DB")

    _write_credentials_file(blob)
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    logger.info(
        "store_credentials_blob: saved (prefix=%s, token_len=%d)",
        token[:15], len(token),
    )
    return token


def store_user_credentials_blob(user, blob: dict) -> str:
    """Persist ``blob`` as ``user``'s UserCredential. Returns the access token."""
    from django.utils import timezone

    from .models import UserCredential

    token = _extract_access_token(blob)
    if not token_looks_real(token):
        raise ValueError(
            "Credential blob missing or malformed access token "
            "(expected claudeAiOauth.accessToken matching sk-ant-oat...)"
        )
    _invalidate_validation_cache()
    cred, _ = UserCredential.objects.update_or_create(
        user=user,
        defaults={
            "blob_encrypted": json.dumps(blob),
            "token_prefix": token[:15],
        },
    )
    # auto_now_add only fires on CREATE; on re-upload, explicitly bump.
    cred.uploaded_at = timezone.now()
    cred.save(update_fields=["uploaded_at"])
    logger.info(
        "store_user_credentials_blob: saved user=%s prefix=%s len=%d",
        user.pk, token[:15], len(token),
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


def load_stored_token() -> str | None:
    """Load persisted credentials at boot.

    Reads the full blob from DB (preferred), writes the credentials file
    so claude CLI can read + refresh natively, hot-caches the access token
    in CLAUDE_CODE_OAUTH_TOKEN. Falls back to the legacy token-only DB row
    for deploys that predate the blob migration, and to an env-injected
    token as the last resort (also backfilled into the DB).
    """
    try:
        from .models import SystemConfig

        row = SystemConfig.objects.filter(key=_BLOB_DB_KEY).first()
        if row and row.value:
            try:
                blob = json.loads(row.value)
            except ValueError:
                logger.warning("stored credentials blob is not valid JSON")
                return None
            token = _extract_access_token(blob)
            if token:
                _write_credentials_file(blob)
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
                return token

        legacy = SystemConfig.objects.filter(key=_TOKEN_DB_KEY).first()
        if legacy and legacy.value:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = legacy.value
            return legacy.value

        env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if env_token and token_looks_real(env_token):
            logger.info("load_stored_token: backfilling injected env token into DB")
            SystemConfig.objects.update_or_create(
                key=_TOKEN_DB_KEY, defaults={"value": env_token}
            )
            return env_token
    except Exception:
        logger.debug("Could not load credentials (migrations may not have run)")
    return None


def get_stored_token(user=None) -> tuple[str, str] | None:
    """Return (access_token, source) where source in {"user", "global", "env"}, or None.

    Resolution order (first real token wins):
      1. UserCredential for ``user`` (if provided, blob valid, not marked invalid).
      2. Global SystemConfig[claude_credentials_blob].
      3. ``CLAUDE_CODE_OAUTH_TOKEN`` env var.
    """
    # 1. per-user
    if user is not None:
        try:
            from .models import UserCredential

            cred = UserCredential.objects.filter(user=user).first()
            # last_validation_ok=False means the last upload-time live check
            # failed; skip to global fallback so chat still works. The user
            # sees "Uploaded but failing" in the Settings UI and can re-upload.
            if cred and cred.blob_encrypted and cred.last_validation_ok is not False:
                try:
                    blob = json.loads(cred.blob_encrypted)
                except ValueError:
                    logger.warning(
                        "UserCredential blob for user=%s is not valid JSON", user.pk
                    )
                    blob = None
                if blob:
                    token = _extract_access_token(blob)
                    if token_looks_real(token):
                        return (token, "user")
        except Exception:
            logger.warning(
                "UserCredential lookup failed for user=%s",
                getattr(user, "pk", None),
                exc_info=True,
            )

    # 2. global (load_stored_token reads the SystemConfig blob, writes the
    #    creds file, and sets the env var as a side effect — preserve that).
    #    Snapshot row-existence BEFORE the call, since load_stored_token
    #    backfills an injected env token into the legacy _TOKEN_DB_KEY row
    #    and would otherwise make an env-only path look like "global".
    had_global_row = _global_row_exists()
    token = load_stored_token()
    if token_looks_real(token):
        return (token, "global") if had_global_row else (token, "env")

    # 3. explicit env fallback (covers the case where load_stored_token didn't run)
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if token_looks_real(env_token):
        return (env_token, "env")

    return None


def _global_row_exists() -> bool:
    try:
        from .models import SystemConfig

        return SystemConfig.objects.filter(
            key__in=[_BLOB_DB_KEY, _TOKEN_DB_KEY]
        ).exists()
    except Exception:
        return False


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

_VALIDATION_CACHE_TTL = float(os.environ.get("ACE_TOKEN_VALIDATION_TTL", "300"))
_validation_cache: dict = {"valid": False, "checked_at": 0.0, "token": "", "source": ""}


def _invalidate_validation_cache() -> None:
    _validation_cache["checked_at"] = 0.0
    _validation_cache["token"] = ""
    _validation_cache["source"] = ""


def _load_blob_for_source(user, source: str) -> str:
    """Fetch the full blob JSON for the resolver's source. Returns "" if missing."""
    if source == "user" and user is not None:
        from .models import UserCredential

        cred = UserCredential.objects.filter(user=user).first()
        return cred.blob_encrypted if cred else ""
    if source == "global":
        from .models import SystemConfig

        row = SystemConfig.objects.filter(key=_BLOB_DB_KEY).first()
        return row.value if row else ""
    return ""


def validate_stored_token(user=None) -> bool:
    """Return True only if the resolved token (per-user or global) passes a live CLI check.

    Runs ``claude -p "ok"`` as a subprocess — same auth path as real chat
    — and looks for a ``result`` event with ``subtype == "success"`` and no
    auth-error markers. Cached for ``_VALIDATION_CACHE_TTL`` seconds so the
    /api/auth/cli/status poll (every 30 s) doesn't thrash the CLI.
    ``store_credentials_blob`` invalidates the cache on write. The cache is
    keyed on ``(token, source)`` so per-user results don't collide with
    global.
    """
    resolved = get_stored_token(user=user)
    if resolved is None:
        logger.info(
            "validate_stored_token: no token found (user=%s)",
            getattr(user, "pk", None),
        )
        return False
    token, source = resolved
    logger.info(
        "validate_stored_token: token_present=True, looks_real=%s, prefix=%s, source=%s",
        token_looks_real(token),
        token[:15] + "..." if token else "None",
        source,
    )
    if not token_looks_real(token):
        return False

    now = time.time()
    if (
        _validation_cache["token"] == token
        and _validation_cache.get("source") == source
        and now - _validation_cache["checked_at"] < _VALIDATION_CACHE_TTL
    ):
        logger.info(
            "validate_stored_token: returning cached result=%s (age=%.0fs)",
            _validation_cache["valid"], now - _validation_cache["checked_at"],
        )
        return _validation_cache["valid"]

    logger.info("validate_stored_token: cache miss, running CLI check")
    # Pick the blob that matches the resolved source so the live check uses
    # the SAME credentials we'd actually hand a chat subprocess.
    blob_json = (
        _load_blob_for_source(user, source)
        if source != "env"
        else json.dumps({"claudeAiOauth": {"accessToken": token}})
    )
    valid = _check_token_via_cli(blob_json=blob_json)
    _validation_cache.update(valid=valid, checked_at=now, token=token, source=source)
    logger.info("validate_stored_token: token %s CLI check", "PASSED" if valid else "FAILED")
    return valid


# Public canonical name. Both /api/auth/cli/status and the chat backend
# selector call this so they never disagree on "is the CLI usable?".
cli_is_ready = validate_stored_token


def _check_token_via_cli(blob_json: str | None = None) -> bool:
    """Run ``claude -p "ok"`` and look for a successful terminal result.

    When ``blob_json`` is provided (per-user validation), stage it into a
    fresh temp HOME for this single subprocess so we validate THIS user's
    token, not whatever happens to be in the global ACE_CLAUDE_HOME.
    When ``blob_json`` is None, fall back to the legacy behavior of using
    the shared ACE_CLAUDE_HOME (covers the no-user / startup-check paths).
    """
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    staged_home: str | None = None

    if blob_json:
        staged_root = os.path.join(
            tempfile.gettempdir(), "ace-cli-validate", uuid.uuid4().hex[:12]
        )
        claude_dir = os.path.join(staged_root, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        creds_path = os.path.join(claude_dir, ".credentials.json")
        with open(creds_path, "w") as f:
            f.write(blob_json)
        try:
            os.chmod(creds_path, 0o600)
        except OSError:
            pass
        env["HOME"] = staged_root
        staged_home = staged_root
    else:
        claude_home = getattr(settings, "ACE_CLAUDE_HOME", None)
        if claude_home:
            env["HOME"] = claude_home

    try:
        proc = subprocess.run(
            ["claude", "-p", "--verbose", "--output-format", "stream-json"],
            input="respond with ok",
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        got_success = '"subtype":"success"' in proc.stdout
        saw_auth_error = any(
            marker in proc.stdout
            for marker in (
                "authentication_error",
                "Invalid bearer token",
                "API Error: 401",
            )
        )
        logger.info(
            "CLI token check: rc=%s got_success=%s auth_error=%s stdout_len=%d staged=%s",
            proc.returncode, got_success, saw_auth_error, len(proc.stdout),
            bool(staged_home),
        )
        if got_success and not saw_auth_error:
            return True
        logger.warning(
            "CLI token check FAILED: stderr=%s stdout_tail=%s",
            _redact_token(proc.stderr[:500]),
            _redact_token(proc.stdout[-1000:]),
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("CLI token check timed out after 30s")
        return False
    except FileNotFoundError:
        logger.warning("claude binary not found for token check")
        return False
    finally:
        if staged_home:
            shutil.rmtree(staged_home, ignore_errors=True)
