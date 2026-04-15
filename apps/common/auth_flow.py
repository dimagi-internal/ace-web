"""
Drive `claude setup-token` via PTY for headless Docker auth.

Flow:
  1. start() — spawns process, captures auth URL, returns it
  2. complete(code) — sends code to PTY, captures OAuth token, persists it
  3. poll() — check if auth completed via browser polling (no code needed)

The resulting token is stored at TOKEN_FILE and exported as
CLAUDE_CODE_OAUTH_TOKEN so the CLI backend picks it up automatically.
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

TOKEN_FILE = os.environ.get(
    "ACE_CLAUDE_TOKEN_FILE", "/var/lib/ace-claude/oauth-token"
)
# If set, store_token() also pushes the token to AWS Secrets Manager so it
# survives ECS task replacement. Value is a secret ARN or name.
TOKEN_SECRET_ID = os.environ.get("ACE_CLAUDE_TOKEN_SECRET_ID")
TOKEN_SECRET_REGION = os.environ.get("AWS_REGION", "us-east-1")

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
    cancel()

    session = _AuthSession()
    session.spawn()

    with _lock:
        _session = session

    # Wait for URL (or instant token) up to 15 s
    deadline = time.time() + 15
    while time.time() < deadline:
        time.sleep(0.5)
        with _lock:
            if session.token:
                store_token(session.token)
                _cleanup_locked()
                return {"auth_url": None, "token": session.token, "status": "complete"}
            if session.url:
                return {"auth_url": session.url, "token": None, "status": "awaiting_code"}

    cancel()
    raise RuntimeError("Timed out waiting for auth URL from setup-token")


def complete(code=None):
    """Send the pasted code (or just check if polling completed). Returns token."""
    global _session

    with _lock:
        if _session is None:
            raise RuntimeError("No active auth flow. Call start() first.")
        session = _session
        if session.token:
            token = session.token
            store_token(token)
            _cleanup_locked()
            return token

    if code:
        session.send(code + "\r")

    deadline = time.time() + 15
    while time.time() < deadline:
        time.sleep(0.5)
        with _lock:
            if session.token:
                token = session.token
                store_token(token)
                _cleanup_locked()
                return token

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
        _cleanup_locked()


def _cleanup_locked():
    global _session
    if _session is not None:
        _session.cleanup()
        _session = None


# ── Token persistence ───────────────────────────────────────────────

def store_token(token):
    """Persist token to disk, secrets manager (if configured), and env."""
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        logger.debug("Could not persist token to %s", TOKEN_FILE)
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    _push_token_to_secrets_manager(token)


def _push_token_to_secrets_manager(token):
    """Write token back to AWS Secrets Manager so it survives ECS task replacement.

    No-op unless ACE_CLAUDE_TOKEN_SECRET_ID is set. Failures are logged but
    never raise — disk+env persistence is the primary path; this is the
    cross-deploy backup.
    """
    if not TOKEN_SECRET_ID:
        return
    try:
        import boto3  # local import: only needed on AWS

        client = boto3.client("secretsmanager", region_name=TOKEN_SECRET_REGION)
        client.put_secret_value(SecretId=TOKEN_SECRET_ID, SecretString=token)
        logger.info("Pushed Claude OAuth token to Secrets Manager (%s)", TOKEN_SECRET_ID)
    except Exception as exc:
        logger.warning("Failed to push token to Secrets Manager: %s", exc)


def load_stored_token():
    """Load persisted token into env. Called at container boot."""
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE) as f:
                token = f.read().strip()
            if token:
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
                return token
    except OSError:
        pass
    return None


def get_stored_token():
    """Return current token from env or disk."""
    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or load_stored_token()
