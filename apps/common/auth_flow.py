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

Storage layers:
  * ``UserCredential`` rows — per-user blobs (preferred for chat)
  * ``SystemConfig[claude_credentials_blob]`` — global fallback blob (JSON)
  * ``SystemConfig[claude_oauth_token]``      — legacy token-only row
    (kept for deploys that predate the blob migration)

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
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)

_TOKEN_DB_KEY = "claude_oauth_token"
_BLOB_DB_KEY = "claude_credentials_blob"

_TOKEN_REDACT_PATTERN = re.compile(r"sk-ant-oat\S+")


def _redact_token(text: str) -> str:
    """Replace any sk-ant-oat... token in text with a placeholder.

    Defense-in-depth for log lines that dump CLI subprocess stdout/stderr —
    today's claude binary doesn't echo the bearer token, but a future version
    that does would leak via these logs without this scrub.
    """
    return _TOKEN_REDACT_PATTERN.sub("sk-ant-oat[REDACTED]", text)


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


# Tracks the last global blob JSON we synced to disk so repeated
# get_stored_token() calls don't rewrite .credentials.json when nothing has
# changed.
_FILE_SYNC_CACHE: dict = {"blob_json": None}


def _sync_global_blob_to_disk(row_value: str) -> str | None:
    """Read the global blob JSON, keep disk in sync, return the access token.

    Factored out of ``get_stored_token`` so the user-aware resolver can use
    the same "write-through-on-change" logic for the global path.
    """
    if _FILE_SYNC_CACHE.get("blob_json") != row_value:
        try:
            blob = json.loads(row_value)
        except ValueError:
            logger.warning("stored credentials blob is not valid JSON")
            return None
        token = _extract_access_token(blob)
        if not token:
            return None
        _write_credentials_file(blob)
        _FILE_SYNC_CACHE["blob_json"] = row_value
        return token
    # Blob already on disk; just re-extract the token without re-parsing twice.
    try:
        return _extract_access_token(json.loads(row_value)) or None
    except ValueError:
        return None


def _resolve_global_token() -> tuple[str, str] | None:
    """Return ``(token, "global")`` from the DB or None.

    Reads fresh from the DB on every call (no env-var fallback) and keeps
    the on-disk ``.credentials.json`` in sync.
    """
    try:
        from .models import SystemConfig

        row = SystemConfig.objects.filter(key=_BLOB_DB_KEY).first()
        if row and row.value:
            token = _sync_global_blob_to_disk(row.value)
            if token:
                return (token, "global")

        # Legacy token-only row — for deploys that predate the blob
        # migration. No credentials file to write in this case (we don't
        # have the refreshToken), so claude -p can't auto-refresh. Still
        # usable until the token expires, at which point the user needs
        # to re-upload via scripts/ace_cli_login.py.
        legacy = SystemConfig.objects.filter(key=_TOKEN_DB_KEY).first()
        if legacy and legacy.value:
            return (legacy.value, "global")
    except Exception:
        logger.debug("Could not load credentials (migrations may not have run)")
    return None


def get_stored_token(user=None) -> tuple[str, str] | None:
    """Return ``(access_token, source)`` where source in ``{"user", "global", "env"}``, or None.

    Resolution order (first real token wins):
      1. UserCredential for ``user`` (if provided, blob valid, not marked invalid).
      2. Global SystemConfig[claude_credentials_blob] (or the legacy
         ``claude_oauth_token`` row).
      3. ``CLAUDE_CODE_OAUTH_TOKEN`` env var (dev/test fallback only — the
         server never writes this).

    Also keeps ``$ACE_CLAUDE_HOME/.claude/.credentials.json`` in sync with
    the resolved global blob so ``claude -p`` subprocesses can authenticate
    and refresh natively. The file is only rewritten when the blob actually
    changes, so the hot path is a single SELECT.
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

    # 2. global (DB-backed; also syncs .credentials.json on disk if the blob changed)
    resolved = _resolve_global_token()
    if resolved is not None:
        return resolved

    # 3. env fallback (dev/test only; the server never writes this)
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if token_looks_real(env_token):
        return (env_token, "env")

    return None


def load_stored_token() -> str | None:
    """Legacy helper — returns just the access token from ``get_stored_token(user=None)``.

    Kept so older callers (status endpoints, docs) that want a plain string
    continue to work. New code should prefer ``get_stored_token(user=...)``
    and inspect the ``source`` to decide whether to stage user-scoped or
    global credentials.
    """
    resolved = get_stored_token(user=None)
    return resolved[0] if resolved else None


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
_validation_cache: dict = {
    "valid": False,
    "checked_at": 0.0,
    "token": "",
    "source": "",
}


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
    auth-error markers. Positive results cache for ``_POSITIVE_CACHE_TTL``
    seconds, negative for ``_NEGATIVE_CACHE_TTL`` seconds, so the
    /api/auth/cli/status poll (every 30s) doesn't thrash the CLI but
    recovery after a fresh upload still happens within seconds.
    ``store_credentials_blob`` invalidates the cache on write. The cache is
    keyed on ``(token, source)`` so per-user results don't collide with
    global, and because ``get_stored_token()`` always reads fresh from the
    DB, other tasks pick up the new token on their next call.
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
    cached_age = now - _validation_cache["checked_at"]
    cache_ttl = _POSITIVE_CACHE_TTL if _validation_cache["valid"] else _NEGATIVE_CACHE_TTL
    if (
        _validation_cache["token"] == token
        and _validation_cache.get("source") == source
        and cached_age < cache_ttl
    ):
        logger.info(
            "validate_stored_token: returning cached result=%s (age=%.0fs, ttl=%ds)",
            _validation_cache["valid"], cached_age, int(cache_ttl),
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
    on_refresh = (
        _build_refresh_persister(user, source) if source in ("user", "global") else None
    )
    valid = _check_token_via_cli(blob_json=blob_json, on_refresh=on_refresh)
    _validation_cache.update(valid=valid, checked_at=now, token=token, source=source)
    logger.info("validate_stored_token: token %s CLI check", "PASSED" if valid else "FAILED")
    return valid


def _build_refresh_persister(user, source: str):
    """Return a callback that persists a refreshed blob back to the right storage.

    Mirrors ``CLIBackend._persist_refreshed_blob`` for the validation probe
    path: ``_check_token_via_cli`` stages the blob into a temp HOME, the
    claude CLI may refresh it in-place, and we need to write the refresh
    back to DB before the staged HOME is rmtree'd — otherwise the next
    validate (or chat) tries to refresh with an already-burned refresh
    token.
    """

    def _persist(blob: dict) -> None:
        access_token = (blob.get("claudeAiOauth") or {}).get("accessToken") or ""
        if not token_looks_real(access_token):
            return
        blob_json = json.dumps(blob)
        if source == "user" and user is not None:
            from .models import UserCredential

            UserCredential.objects.filter(user=user).update(
                blob_encrypted=blob_json,
                token_prefix=access_token[:15],
            )
            logger.info(
                "validate: persisted refreshed user blob for user=%s", user.pk
            )
        elif source == "global":
            from .models import SystemConfig

            SystemConfig.objects.update_or_create(
                key=_BLOB_DB_KEY,
                defaults={"value": blob_json},
            )
            # Keep the file-sync cache aligned with what's now on disk/DB so
            # the next get_stored_token() call doesn't rewrite the file for
            # no reason.
            _FILE_SYNC_CACHE["blob_json"] = blob_json
            logger.info("validate: persisted refreshed global blob")

    return _persist


# Public canonical name. Both /api/auth/cli/status and the chat backend
# selector call this so they never disagree on "is the CLI usable?".
cli_is_ready = validate_stored_token


def _check_token_via_cli(
    blob_json: str | None = None,
    on_refresh=None,
) -> bool:
    """Run ``claude -p "ok"`` and look for a successful terminal result.

    When ``blob_json`` is provided (per-user validation), stage it into a
    fresh temp HOME for this single subprocess so we validate THIS user's
    token, not whatever happens to be in the global ACE_CLAUDE_HOME.
    When ``blob_json`` is None, fall back to the legacy behavior of using
    the shared ACE_CLAUDE_HOME (covers the no-user / startup-check paths).

    ``on_refresh`` is an optional ``Callable[[dict], None]`` invoked before
    teardown with the (possibly-refreshed) blob read back from the staged
    credentials file. Caller uses it to persist the refresh back to the
    right storage layer — see ``_build_refresh_persister``.
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
        try:
            proc = subprocess.run(
                ["claude", "-p", "--output-format", "stream-json", "--verbose", "ok"],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("CLI token check timed out after 30s")
            return False
        except FileNotFoundError:
            logger.warning("claude binary not found for token check")
            return False

        got_success = False
        saw_auth_error = any(
            marker in proc.stdout
            for marker in (
                "authentication_error",
                "Invalid bearer token",
                "API Error: 401",
            )
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if (
                    event.get("type") == "result"
                    and event.get("subtype") == "success"
                ):
                    got_success = True
                    break
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
    finally:
        if staged_home:
            if on_refresh is not None:
                try:
                    refreshed_path = os.path.join(
                        staged_home, ".claude", ".credentials.json"
                    )
                    if os.path.exists(refreshed_path):
                        with open(refreshed_path) as f:
                            refreshed = json.load(f)
                        on_refresh(refreshed)
                except Exception:
                    logger.warning(
                        "Failed to read refreshed creds for persist",
                        exc_info=True,
                    )
            shutil.rmtree(staged_home, ignore_errors=True)
