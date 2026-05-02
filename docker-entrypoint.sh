#!/bin/bash
# Container entrypoint.
#
# Writes the Google service-account key from ACE_DRIVE_SA_KEY_JSON (injected
# by ECS from Secrets Manager) into the Claude plugin data dir so the ACE
# plugin's MCP servers can authenticate to Drive, then execs the CMD.
#
# The plugin's MCP server reads GOOGLE_APPLICATION_CREDENTIALS from its
# own config. We keep the key out of the image itself — it only lands on
# disk at container start, inside the writable layer, never committed.

set -e

PLUGIN_DATA_DIR="${CLAUDE_PLUGIN_DATA:-/home/app/.claude/plugin-data/ace}"
SA_KEY_PATH="${PLUGIN_DATA_DIR}/gws-sa-key.json"

if [ -n "${ACE_DRIVE_SA_KEY_JSON:-}" ]; then
    mkdir -p "$PLUGIN_DATA_DIR"
    printf '%s' "$ACE_DRIVE_SA_KEY_JSON" > "$SA_KEY_PATH"
    chmod 600 "$SA_KEY_PATH"
    echo "[entrypoint] Wrote ACE plugin SA key to $SA_KEY_PATH"
else
    echo "[entrypoint] ACE_DRIVE_SA_KEY_JSON not set — ACE plugin MCP servers will fail to auth to Drive"
fi

# Render the ACE plugin's .env from .env.tpl using the 1Password service
# account. OP_SERVICE_ACCOUNT_TOKEN comes from AWS Secrets Manager. Source
# tpl is the canonical one inside the vendored plugin tree (/app/vendor/ace).
# Output goes to the plugin-data dir where the ACE MCP servers (ocs-server,
# connect-server, etc.) explicitly load it via dotenv. Without this, those
# MCPs come up but are missing OCS_*, ACE_HQ_*, ACE_GMAIL_*, etc., and any
# downstream skill that needs those creds fails.
ACE_ENV_TPL="${ACE_PLUGIN_PATH:-/app/vendor/ace}/.env.tpl"
ACE_ENV_PATH="${PLUGIN_DATA_DIR}/.env"
if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ] && [ -f "$ACE_ENV_TPL" ]; then
    mkdir -p "$PLUGIN_DATA_DIR"
    if op inject -i "$ACE_ENV_TPL" -o "$ACE_ENV_PATH" --account dimagi.1password.com 2>/tmp/op-inject.err; then
        chmod 600 "$ACE_ENV_PATH"
        echo "[entrypoint] op inject succeeded → $ACE_ENV_PATH ($(grep -c '^[A-Z]' "$ACE_ENV_PATH") env keys)"
        # Mirror to the plugin's vendor dir as well. When Claude Code launches
        # the ACE MCP servers, it does NOT pass `${CLAUDE_PLUGIN_DATA}`
        # through the env block (known issue, anthropics/claude-code#9427), so
        # the MCPs fall back to `process.cwd() + '/.env'`. cwd is the plugin
        # directory (/app/vendor/ace), so a copy here makes the cwd-fallback
        # work even when the env-block substitution doesn't.
        if [ -d "${ACE_PLUGIN_PATH:-/app/vendor/ace}" ]; then
            cp -f "$ACE_ENV_PATH" "${ACE_PLUGIN_PATH:-/app/vendor/ace}/.env" 2>/dev/null \
                && chmod 600 "${ACE_PLUGIN_PATH:-/app/vendor/ace}/.env" \
                && echo "[entrypoint] mirrored .env to ${ACE_PLUGIN_PATH:-/app/vendor/ace}/.env (cwd-fallback for MCPs)" \
                || echo "[entrypoint] could not mirror .env to plugin cwd — MCPs may 401 if Claude Code doesn't pass CLAUDE_PLUGIN_DATA"
        fi
    else
        echo "[entrypoint] op inject FAILED — see /tmp/op-inject.err"
        head -c 500 /tmp/op-inject.err >&2
        echo "" >&2
        echo "[entrypoint] continuing without rendered .env; downstream ACE MCPs may fail to find OCS/HQ/Gmail creds"
    fi
elif [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    echo "[entrypoint] OP_SERVICE_ACCOUNT_TOKEN not set — skipping op inject. ACE plugin MCPs that need 1Password-backed creds (OCS, Connect, Gmail, HQ) will fail."
elif [ ! -f "$ACE_ENV_TPL" ]; then
    echo "[entrypoint] No .env.tpl found at $ACE_ENV_TPL — skipping op inject. Did the ACE plugin clone succeed?"
fi

exec "$@"
