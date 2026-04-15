"""Claude CLI OAuth token persistence.

The user runs `claude setup-token` on their own laptop and pastes the
resulting `sk-ant-oat…` token into the ace-web UI. We stash it in three
places so every task has it at startup:

  - env (`CLAUDE_CODE_OAUTH_TOKEN`) — picked up by the `claude` CLI
    subprocess at session time
  - disk (`TOKEN_FILE`) — primary persistence inside the container
  - AWS Secrets Manager (if `ACE_CLAUDE_TOKEN_SECRET_ID` is set) — survives
    ECS task replacement

The server-side PTY `claude setup-token` flow we used to run was deleted
because it required two HTTP calls to hit the same ECS task (the PTY
subprocess lived in one task's memory). See git history for context.
"""
import logging
import os

logger = logging.getLogger(__name__)

TOKEN_FILE = os.environ.get(
    "ACE_CLAUDE_TOKEN_FILE", "/var/lib/ace-claude/oauth-token"
)
# If set, store_token() also pushes the token to AWS Secrets Manager so it
# survives ECS task replacement. Value is a secret ARN or name.
TOKEN_SECRET_ID = os.environ.get("ACE_CLAUDE_TOKEN_SECRET_ID")
TOKEN_SECRET_REGION = os.environ.get("AWS_REGION", "us-east-1")

TOKEN_PREFIX = "sk-ant-oat"


class InvalidTokenError(ValueError):
    """Raised when the submitted token doesn't look like a Claude OAuth token."""


def store_token(token):
    """Persist token to disk, secrets manager (if configured), and env.

    Raises InvalidTokenError if the token doesn't start with sk-ant-oat.
    """
    token = (token or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        raise InvalidTokenError(
            f"Token must start with {TOKEN_PREFIX!r}. Run `claude setup-token` "
            "on your laptop and paste the value it prints."
        )
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
