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
    unzip \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@latest \
    # 1Password CLI — entrypoint uses `op inject` to render the ACE plugin's
    # .env.tpl into a real .env at container start, pulling secrets from the
    # AI-Agents vault under a service-account token. Removes the need to
    # provision per-credential secrets in AWS Secrets Manager for every new
    # 1Password item the ACE plugin starts using.
    && curl -fsSLo /tmp/op.zip "https://cache.agilebits.com/dist/1P/op2/pkg/v2.32.1/op_linux_amd64_v2.32.1.zip" \
    && cd /tmp && unzip -q op.zip && mv op /usr/local/bin/op && chmod +x /usr/local/bin/op \
    && rm -f op.zip op.sig \
    && rm -rf /var/lib/apt/lists/* \
    && echo "claude --version output:" && claude --version \
    && echo "op --version output:" && op --version

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
# Clone the ACE plugin into a temporary location so we can read VERSION,
# install npm deps, then move it directly into the plugin cache path that
# Claude Code reads from. Earlier versions of this Dockerfile placed the
# real plugin at /app/vendor/ace and symlinked the cache entry there;
# Claude Code 2.x removes those symlinks at runtime (verified via repeated
# /api/system/cli-diag probes — cache/ace/ace/<v> vanishes after each
# claude -p invocation, so the ACE stdio MCPs lose their on-disk install
# path mid-session). Storing the install in cache as a real directory and
# symlinking /app/vendor/ace BACK to it is stable across runs.
RUN mkdir -p /home/app/.claude/plugins/cache/ace/ace \
    && git clone https://github.com/jjackson/ace.git /tmp/ace-clone \
    && cd /tmp/ace-clone \
    && git checkout ${ACE_REF} \
    && npm install --no-audit --no-fund \
    && rm -rf .git \
    && ACE_VERSION="$(cat VERSION 2>/dev/null || echo vendored)" \
    && mv /tmp/ace-clone "/home/app/.claude/plugins/cache/ace/ace/${ACE_VERSION}" \
    && mkdir -p /app/vendor \
    && ln -s "/home/app/.claude/plugins/cache/ace/ace/${ACE_VERSION}" /app/vendor/ace \
    && echo "ACE plugin installed at /home/app/.claude/plugins/cache/ace/ace/${ACE_VERSION} (real dir); /app/vendor/ace -> same"

# Vendor the Nova plugin (CommCare app builder). Two repos:
#   1. github.com/voidcraft-labs/nova-marketplace — minimal, just contains
#      .claude-plugin/marketplace.json that points at the plugin source.
#   2. github.com/voidcraft-labs/nova-plugin — the actual skills + agents.
# Nova's MCP is HTTP-based (https://mcp.commcare.app/mcp) so no node deps
# to install for it; the only thing we need on disk is the skill/agent
# definitions so Claude Code can resolve `/nova:upload_to_hq` etc.
#
# The Nova HTTP MCP needs auth on first call — see CONFIGURE_NOVA flow.
# Until that's wired through 1Password, Phase 2 still requires manual
# `/plugin install nova@nova-marketplace` + OAuth in a separate session.
ARG NOVA_REF=main
ARG NOVA_VERSION=1.0.0
# Same install pattern as ACE: real dir under cache, symlink in /app/vendor.
# (Nova's MCP is HTTP-based so symlink-removal isn't a regression vector for
# Nova specifically, but match the pattern for consistency.)
RUN mkdir -p /home/app/.claude/plugins/cache/nova-marketplace/nova \
    && git clone https://github.com/voidcraft-labs/nova-marketplace.git /app/vendor/nova-marketplace \
    && cd /app/vendor/nova-marketplace \
    && git checkout ${NOVA_REF} \
    && rm -rf .git \
    && git clone https://github.com/voidcraft-labs/nova-plugin.git "/home/app/.claude/plugins/cache/nova-marketplace/nova/${NOVA_VERSION}" \
    && cd "/home/app/.claude/plugins/cache/nova-marketplace/nova/${NOVA_VERSION}" \
    && git checkout ${NOVA_REF} \
    && rm -rf .git \
    && ln -s "/home/app/.claude/plugins/cache/nova-marketplace/nova/${NOVA_VERSION}" /app/vendor/nova-plugin

# Install Playwright system dependencies so the ACE plugin's ace-connect
# and ace-ocs MCP servers can launch Chromium for their authenticated-
# session bootstrap. Without this, Phase 3 (Connect setup) and Phase 4
# (OCS authoring) hard-block on missing libglib2.0. Reproduced today —
# the Tier C v3 run got past Phase 1 and stalled at exactly this dep.
#
# `playwright install-deps chromium` apt-installs libglib + ~20 other
# X11/font/audio libraries Chromium needs in a headless Linux env.
# `playwright install chromium` downloads the Chromium binary itself
# into /home/app/.cache/ms-playwright (we run it as root here; later
# chown to app so the runtime user can read it).
ARG PLAYWRIGHT_REF=2026-05-01-chromium-deps
RUN echo "playwright cache key: ${PLAYWRIGHT_REF}" \
    && cd /app/vendor/ace \
    && PLAYWRIGHT_BROWSERS_PATH=/home/app/.cache/ms-playwright \
       npx --yes playwright install-deps chromium \
    && PLAYWRIGHT_BROWSERS_PATH=/home/app/.cache/ms-playwright \
       npx --yes playwright install chromium \
    && rm -rf /var/lib/apt/lists/*

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
    && NOVA_INSTALL_VERSION=${NOVA_VERSION} \
    && INSTALLED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    # Plugin install dirs were created above when we cloned the plugins
    # directly into cache/<marketplace>/<plugin>/<version>/. Just verify
    # they exist before we generate the registry that points at them.
    && [ -d "/home/app/.claude/plugins/cache/ace/ace/${ACE_VERSION}" ] || (echo "ACE plugin install missing" && exit 1) \
    && [ -d "/home/app/.claude/plugins/cache/nova-marketplace/nova/${NOVA_INSTALL_VERSION}" ] || (echo "Nova plugin install missing" && exit 1) \
    # Plugin registry — must match the schema Claude Code 2.x writes itself,
    # otherwise the loader silently skips the entry. Verified by reading a
    # real laptop install + the /api/system/cli-diag probe in the container.
    && printf '{\n  "version": 2,\n  "plugins": {\n    "ace@ace": [\n      {\n        "scope": "user",\n        "installPath": "/home/app/.claude/plugins/cache/ace/ace/%s",\n        "version": "%s",\n        "installedAt": "%s",\n        "lastUpdated": "%s"\n      }\n    ],\n    "nova@nova-marketplace": [\n      {\n        "scope": "user",\n        "installPath": "/home/app/.claude/plugins/cache/nova-marketplace/nova/%s",\n        "version": "%s",\n        "installedAt": "%s",\n        "lastUpdated": "%s"\n      }\n    ]\n  }\n}\n' \
        "${ACE_VERSION}" "${ACE_VERSION}" "${INSTALLED_AT}" "${INSTALLED_AT}" \
        "${NOVA_INSTALL_VERSION}" "${NOVA_INSTALL_VERSION}" "${INSTALLED_AT}" "${INSTALLED_AT}" \
        > /home/app/.claude/plugins/installed_plugins.json \
    # Marketplace registration — installed_plugins.json alone isn't enough;
    # claude resolves the plugin's source marketplace on load, and without a
    # `known_marketplaces.json` entry + a marketplaces/<id>/ dir the plugin
    # is silently dropped (init payload shows plugins=[] mcp_servers=[]).
    && mkdir -p /home/app/.claude/plugins/marketplaces \
    && ln -s /app/vendor/ace /home/app/.claude/plugins/marketplaces/ace \
    && ln -s /app/vendor/nova-marketplace /home/app/.claude/plugins/marketplaces/nova-marketplace \
    && printf '{\n  "ace": {\n    "source": {\n      "source": "github",\n      "repo": "jjackson/ace"\n    },\n    "installLocation": "/home/app/.claude/plugins/marketplaces/ace",\n    "lastUpdated": "%s"\n  },\n  "nova-marketplace": {\n    "source": {\n      "source": "github",\n      "repo": "voidcraft-labs/nova-marketplace"\n    },\n    "installLocation": "/home/app/.claude/plugins/marketplaces/nova-marketplace",\n    "lastUpdated": "%s"\n  }\n}\n' \
        "${INSTALLED_AT}" "${INSTALLED_AT}" \
        > /home/app/.claude/plugins/known_marketplaces.json \
    # Plugin enablement — Claude 2.x reads ~/.claude/settings.json
    # `enabledPlugins` to decide which registered plugins to actually load.
    # Without this entry the plugin is silently disabled.
    && printf '{\n  "enabledPlugins": {\n    "ace@ace": true,\n    "nova@nova-marketplace": true\n  }\n}\n' \
        > /home/app/.claude/settings.json \
    && mkdir -p /home/app/.claude/plugin-data/ace \
    # /home/app may have been created by an earlier RUN-as-root step
    # (the Playwright install above creates /home/app/.cache before useradd
    # runs, leaving /home/app itself owned by root). Recursive chown of the
    # whole home dir so the runtime user can also write things like
    # ~/.config/op which the 1Password CLI needs.
    && chown -R app:app /app /home/app

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
    CLAUDE_PLUGIN_DATA=/home/app/.claude/plugin-data/ace \
    PLAYWRIGHT_BROWSERS_PATH=/home/app/.cache/ms-playwright

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Production command — uvicorn ASGI server.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
