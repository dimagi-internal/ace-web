"""
Drive `claude setup-token` via PTY for headless Docker auth.

Flow:
  1. start() — spawns process, captures auth URL, returns it
  2. complete(code) — sends code to PTY, captures OAuth token, persists it
  3. poll() — check if auth completed via browser polling (no code needed)

The resulting token is stored in the database (SystemConfig) and exported
as CLAUDE_CODE_OAUTH_TOKEN so the CLI backend picks it up automatically.
DB storage survives container restarts and deploys without Secrets Manager.
"""
import logging
import os
import pty
import re
import select
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# Deadlines for PTY interactions. The claude CLI makes network calls to
# Anthropic before printing the URL and after the code is submitted; on
# slow paths (ECS → internet) 15 s was too tight. Override via env for ops.
START_TIMEOUT_SECONDS = int(os.environ.get("ACE_CLAUDE_AUTH_START_TIMEOUT", "60"))
COMPLETE_TIMEOUT_SECONDS = int(os.environ.get("ACE_CLAUDE_AUTH_COMPLETE_TIMEOUT", "90"))

_TOKEN_DB_KEY = "claude_oauth_token"

_lock = threading.Lock()
_session = None  # type: _AuthSession | None


# ── ANSI / parsing helpers ──────────────────────────────────────────

_ANSI_RE = re.compile(
    r"\x1b[\[\(][0-9;?]*[a-zA-Z]"
    r"|\x1b[><=][0-9;]*[a-zA-Z]?"
    r"|\x1b\[[?0-9;]*[a-zA-Z]"
)


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)


def _extract_url(raw):
    clean = _strip_ansi(raw).replace("\n", "").replace("\r", "")
    # After ANSI strip + newline removal, prompt text like
    # "Pastecodehereifprompted>" is concatenated right after the URL.
    # Use non-greedy match with lookahead to stop before "Paste".
    m = re.search(
        r"(https://claude\.com/cai/oauth/authorize\S+?)(?=Paste|\s|$)",
        clean,
    )
    return m.group(1) if m else None


def _extract_token(raw):
    clean = _strip_ansi(raw)
    m = re.search(r"(sk-ant-oat\S+)", clean)
    return m.group(1) if m else None


# ── Session object ──────────────────────────────────────────────────

class _AuthSession:
    """Manages a single setup-token PTY subprocess."""

    def __init__(self):
        self.master_fd = None
        self.process = None
        self.buffer = ""
        self.token = None
        self.url = None
        self.started_at = time.time()

    def spawn(self):
        master, slave = pty.openpty()
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        self.process = subprocess.Popen(
            ["claude", "setup-token"],
            stdin=slave, stdout=slave, stderr=slave,
            close_fds=True, start_new_session=True, env=env,
        )
        os.close(slave)
        self.master_fd = master
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        """Background reader — keeps PTY buffer drained."""
        while self.master_fd is not None:
            try:
                r, _, _ = select.select([self.master_fd], [], [], 1.0)
                if r:
                    chunk = os.read(self.master_fd, 4096)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    with _lock:
                        self.buffer += text
                        if not self.url:
                            self.url = _extract_url(self.buffer)
                        if not self.token:
                            self.token = _extract_token(self.buffer)
            except OSError:
                break

    def send(self, text):
        if self.master_fd is not None:
            os.write(self.master_fd, text.encode())

    def send_code(self, code):
        """Send an OAuth code to the PTY and press Enter.

        The claude CLI runs a full-screen TUI in raw mode. Pasting all
        chars + Enter in a single os.write works locally but on Linux
        Docker the TUI sometimes swallows the trailing CR. Sending the
        code first, pausing to let the TUI process the paste, then
        sending Enter separately is more reliable.
        """
        if self.master_fd is None:
            return
        os.write(self.master_fd, code.encode())
        time.sleep(0.3)
        os.write(self.master_fd, b"\r")
        time.sleep(0.3)
        os.write(self.master_fd, b"\n")

    def cleanup(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None


# ── Public API ──────────────────────────────────────────────────────

def start():
    """Spawn setup-token, return auth URL (or token if auth is instant)."""
    global _session
    logger.info("auth_flow.start() called (pid=%s)", os.getpid())
    cancel()

    session = _AuthSession()
    session.spawn()

    with _lock:
        _session = session

    deadline = time.time() + START_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(0.5)
        with _lock:
            if session.token:
                logger.info("auth_flow.start: instant token captured, session cleared")
                store_token(session.token)
                _cleanup_locked()
                return {"auth_url": None, "token": session.token, "status": "complete"}
            if session.url:
                logger.info(
                    "auth_flow.start: URL captured, session still alive "
                    "(buffer_len=%d)", len(session.buffer)
                )
                return {"auth_url": session.url, "token": None, "status": "awaiting_code"}

    logger.warning(
        "auth_flow.start: timed out after %s s (buffer=%r)",
        START_TIMEOUT_SECONDS,
        session.buffer[:500],
    )
    cancel()
    raise RuntimeError("Timed out waiting for auth URL from setup-token")


def complete(code=None):
    """Send the pasted code (or just check if polling completed). Returns token."""
    global _session

    logger.info(
        "auth_flow.complete() called (pid=%s, code_len=%s, session_present=%s)",
        os.getpid(), len(code) if code else 0, _session is not None,
    )
    with _lock:
        if _session is None:
            raise RuntimeError("No active auth flow. Call start() first.")
        session = _session
        if session.token:
            logger.info("auth_flow.complete: token already captured before code sent")
            token = session.token
            store_token(token)
            _cleanup_locked()
            return token

    if code:
        logger.info("auth_flow.complete: sending code (%d chars) to PTY", len(code))
        session.send_code(code)

    deadline = time.time() + COMPLETE_TIMEOUT_SECONDS
    logged_30s = False
    while time.time() < deadline:
        time.sleep(0.5)
        elapsed = time.time() - (deadline - COMPLETE_TIMEOUT_SECONDS)
        if not logged_30s and elapsed > 30:
            logged_30s = True
            clean = _strip_ansi(session.buffer)
            logger.info(
                "auth_flow.complete: 30s mark, proc_alive=%s, buffer_clean=%r",
                session.process and session.process.poll() is None,
                clean[-2000:],
            )
        with _lock:
            if session.token:
                logger.info("auth_flow.complete: token captured after %.1fs", elapsed)
                token = session.token
                store_token(token)
                _cleanup_locked()
                return token

    clean = _strip_ansi(session.buffer)
    logger.warning(
        "auth_flow.complete: timed out after %s s, proc_alive=%s, "
        "buffer_clean=%r",
        COMPLETE_TIMEOUT_SECONDS,
        session.process and session.process.poll() is None,
        clean[-3000:],
    )
    raise RuntimeError("Timed out waiting for token. Code may be invalid.")


def poll():
    """Non-blocking check — has auth completed?"""
    with _lock:
        if _session is None:
            return {
                "active": False,
                "authenticated": bool(get_stored_token()),
            }
        if _session.token:
            token = _session.token
            store_token(token)
            _cleanup_locked()
            return {"active": False, "authenticated": True}
        elapsed = int(time.time() - _session.started_at)
        return {"active": True, "authenticated": False, "elapsed_seconds": elapsed}


def cancel():
    """Kill any running auth session."""
    with _lock:
        if _session is not None:
            logger.info("auth_flow.cancel(): wiping session (pid=%s)", os.getpid())
        _cleanup_locked()


def _cleanup_locked():
    global _session
    if _session is not None:
        _session.cleanup()
        _session = None


# ── Token persistence (DB-backed) ──────────────────────────────────

def store_token(token):
    """Persist token to DB and env. Survives deploys via Postgres."""
    _invalidate_validation_cache()
    try:
        from .models import SystemConfig
        SystemConfig.objects.update_or_create(
            key=_TOKEN_DB_KEY,
            defaults={"value": token},
        )
    except Exception:
        logger.exception("Failed to persist token to DB")
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    logger.info("store_token: saved to DB + env (prefix=%s)", token[:15])


def load_stored_token():
    """Load persisted token from DB into env. Called at container boot.

    The DB is the canonical store. If CLAUDE_CODE_OAUTH_TOKEN is set in the
    environment (e.g. injected by a dev shell or one-off task) but the DB is
    empty, backfill it so subsequent callers see a single source of truth.
    """
    try:
        from .models import SystemConfig
        row = SystemConfig.objects.filter(key=_TOKEN_DB_KEY).first()
        if row and row.value:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = row.value
            return row.value

        env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if env_token and token_looks_real(env_token):
            logger.info("load_stored_token: backfilling injected env token into DB")
            SystemConfig.objects.update_or_create(
                key=_TOKEN_DB_KEY,
                defaults={"value": env_token},
            )
            return env_token
    except Exception:
        logger.debug("Could not load token from DB (migrations may not have run)")
    return None


def get_stored_token():
    """Return current token from env or DB."""
    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or load_stored_token()


def token_looks_real(token):
    """Cheap format check that rejects placeholders and obvious paste errors.

    Real Claude OAuth tokens look like "sk-ant-oatNN-<long opaque string>".
    We don't validate against Anthropic — just enough to reject the
    placeholder written when provisioning Secrets Manager and any mangled
    input. Kept next to the storage code so every caller picks up updates.
    """
    if not token:
        return False
    if not token.startswith("sk-ant-oat"):
        return False
    if len(token) < 40:
        return False
    if "placeholder" in token.lower():
        return False
    return True


# ── Live token validation (cached) ────────────────────────────────

# Cache TTL: how long a successful validation is trusted before re-checking.
_VALIDATION_CACHE_TTL = float(os.environ.get("ACE_TOKEN_VALIDATION_TTL", "300"))

_validation_cache: dict = {"valid": False, "checked_at": 0.0, "token": ""}


def _invalidate_validation_cache():
    """Clear the cache so the next status check re-validates."""
    _validation_cache["checked_at"] = 0.0
    _validation_cache["token"] = ""


def validate_stored_token() -> bool:
    """Return True only if the stored token passes a live CLI check.

    Runs ``claude -p "ok"`` as a subprocess — same auth path as real chat.
    Results are cached for ``_VALIDATION_CACHE_TTL`` seconds (default 5 min).
    ``store_token()`` invalidates the cache so a fresh auth is re-validated
    immediately.
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
    cache_age = now - _validation_cache["checked_at"]
    if (
        _validation_cache["token"] == token
        and cache_age < _VALIDATION_CACHE_TTL
    ):
        logger.info(
            "validate_stored_token: returning cached result=%s (age=%.0fs)",
            _validation_cache["valid"], cache_age,
        )
        return _validation_cache["valid"]

    logger.info("validate_stored_token: cache miss, running CLI check")
    valid = _check_token_via_cli()
    _validation_cache.update(valid=valid, checked_at=now, token=token)
    if not valid:
        logger.warning("validate_stored_token: token FAILED CLI check")
    else:
        logger.info("validate_stored_token: token PASSED CLI check")
    return valid


def _check_token_via_cli() -> bool:
    """Run a minimal ``claude -p`` invocation to verify the token works.

    Uses the same env and binary as CLIBackend so the result is
    authoritative for real chat. Costs one trivial API call (~10 tokens).

    Success criterion: the CLI emits a ``{"type":"system","subtype":"init"``
    event, which proves the token authenticated and a session was created.
    The exit code is NOT reliable — the CLI may exit 1 even after a
    successful auth + response if, e.g., a tool call fails internally.
    """
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    from django.conf import settings
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
        # The init event proves the token authenticated successfully.
        got_init = '"subtype":"init"' in proc.stdout
        logger.info(
            "CLI token check: rc=%s, got_init=%s, stdout_len=%d",
            proc.returncode, got_init, len(proc.stdout),
        )
        if got_init:
            return True
        # No init event — likely auth failure. Log the tail for debugging.
        logger.warning(
            "CLI token check: no init event (rc=%s): stderr=%s stdout_tail=%s",
            proc.returncode, proc.stderr[:500], proc.stdout[-500:],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("CLI token check timed out after 30s")
        return False
    except FileNotFoundError:
        logger.warning("claude binary not found for token check")
        return False


# Public canonical name. Both /api/auth/cli/status and the chat backend
# selector call this so they never disagree on "is the CLI usable?".
cli_is_ready = validate_stored_token
