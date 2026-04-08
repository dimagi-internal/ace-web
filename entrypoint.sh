#!/bin/bash
set -e

# Ensure the persistent CLI state directory exists
ACE_CLAUDE_DIR="${ACE_CLAUDE_HOME:-/var/lib/ace-claude}"
mkdir -p "$ACE_CLAUDE_DIR/.claude"

# Symlink ~/.claude into the persistent directory so the CLI's session store
# survives container restarts.
if [ ! -L "$HOME/.claude" ]; then
  rm -rf "$HOME/.claude" 2>/dev/null || true
  ln -s "$ACE_CLAUDE_DIR/.claude" "$HOME/.claude"
fi

# Bootstrap Claude CLI auth from Secret Manager if available.
# In Plan 1A this is a no-op; the actual token loading lands in Plan 1B
# when the CLIBackend is implemented.
if [ -n "${ACE_CLAUDE_TOKEN_SECRET}" ]; then
    echo "[entrypoint] Loading CLAUDE_CODE_OAUTH_TOKEN from secret ${ACE_CLAUDE_TOKEN_SECRET}"
    # Plan 1B: read from Secret Manager and write to ~/.claude/auth.json
fi

# Apply migrations
python manage.py migrate --noinput

# Start ASGI server. Add --reload in dev for hot-reload on source changes.
RELOAD_FLAG=""
if [ "${DJANGO_DEBUG}" = "True" ]; then
    RELOAD_FLAG="--reload"
fi
exec uvicorn config.asgi:application \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --workers 1 \
    --lifespan off \
    $RELOAD_FLAG
