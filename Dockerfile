# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.connectlabs

# System dependencies: postgres client libs for psycopg, curl for healthchecks,
# git for cloning vendored plugins, Node.js + the Claude CLI (the chat backend
# spawns `claude -p` as a subprocess).
#
# Bump CLAUDE_CLI_REF whenever you need to force a fresh `npm install` of the
# Claude CLI — its layer is otherwise cached forever (no version pin to
# fingerprint), and the build-cache hit means we keep shipping whatever
# version the layer was first built with.
ARG CLAUDE_CLI_REF=2026-05-01-skip-permissions-rollout
RUN echo "claude-cli cache key: ${CLAUDE_CLI_REF}" && \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    gnupg \
    git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@latest \
    && rm -rf /var/lib/apt/lists/* \
    && echo "claude --version output:" && claude --version

# Vendor the ACE plugin repo. Serves two purposes:
#   1. The System Overview tab reads skill/agent/artifact metadata from here
#      via ACE_PLUGIN_PATH (see apps/system/reader.py).
#   2. Installed into the container user's ~/.claude/plugins/ below so
#      `claude -p` subprocess sessions have ACE skills, commands, and MCP
#      servers available.
#
# Pinned to the ref passed in ACE_REF (build-backend.yml resolves this to the
# current HEAD SHA of jjackson/ace, so Docker's layer cache busts whenever the
# remote branch moves — otherwise the cached clone would snapshot-freeze the
# plugin at whatever main was the first time this image was built).
ARG ACE_REF=main
RUN git clone https://github.com/jjackson/ace.git /app/vendor/ace \
    && cd /app/vendor/ace \
    && git checkout ${ACE_REF} \
    && npm install --no-audit --no-fund \
    && rm -rf .git

# Install uv for fast, reproducible dep installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dep manifests first so Docker layer caching works.
COPY pyproject.toml uv.lock* ./

# Install deps from the lock file only (no source yet, no dev extras).
RUN uv export --frozen --no-dev --no-emit-project 2>/dev/null > /tmp/requirements.txt || \
    uv pip compile pyproject.toml -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt

# Copy the rest of the project.
COPY . .

# Install the project itself (fast — deps already installed).
RUN uv pip install --system --no-deps -e .

# Run collectstatic at build time so the image ships with the static
# manifest. Use placeholders for env vars that settings.base would otherwise
# require — the values don't affect collectstatic output.
RUN DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_ALLOWED_HOSTS=build-time-placeholder \
    DATABASE_URL=sqlite:///tmp/build.db \
    DJANGO_SETTINGS_MODULE=config.settings.base \
    python manage.py collectstatic --noinput --clear

# Non-root user. Create the Claude CLI home dir so the token loader can
# write the OAuth token to it without permission errors. Also install the
# vendored ACE plugin into the user's ~/.claude/plugins/ so `claude -p`
# subprocess sessions can invoke ACE skills, slash commands, and MCP
# servers. The plugin files live under /app/vendor/ace (writable layer),
# with installed_plugins.json pointing Claude CLI at that path.
RUN useradd -m -u 1000 app \
    && mkdir -p /app/.ace-claude-home \
    && ACE_VERSION=$(cat /app/vendor/ace/VERSION 2>/dev/null || echo "vendored") \
    && mkdir -p /home/app/.claude/plugins/cache/ace/ace \
    && ln -s /app/vendor/ace "/home/app/.claude/plugins/cache/ace/ace/${ACE_VERSION}" \
    && printf '%s\n' "{\"ace@ace\":{\"version\":\"${ACE_VERSION}\",\"installPath\":\"/home/app/.claude/plugins/cache/ace/ace/${ACE_VERSION}\",\"installedAt\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}" > /home/app/.claude/plugins/installed_plugins.json \
    && mkdir -p /home/app/.claude/plugin-data/ace \
    && chown -R app:app /app /home/app/.claude

# Entrypoint writes the Drive SA key from ACE_DRIVE_SA_KEY_JSON (Secrets
# Manager) to $CLAUDE_PLUGIN_DATA/gws-sa-key.json at container start, so
# the ACE plugin's MCP servers can authenticate to Drive.
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh

USER app

# Docker's USER directive does NOT auto-set HOME. Without this, processes
# started by the entrypoint (uvicorn, cli_backend's claude -p subprocess)
# may inherit HOME=/root or no HOME at all — which makes the staged-HOME
# symlink in apps/common/cli_backend.py look in the wrong place for the
# ACE plugin and the assistant runs as a tool-less chatbot.
ENV HOME=/home/app

# Claude plugin discovery + MCP config paths for this container.
ENV ACE_PLUGIN_PATH=/app/vendor/ace \
    CLAUDE_PLUGIN_DATA=/home/app/.claude/plugin-data/ace

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Production command — uvicorn ASGI server.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
