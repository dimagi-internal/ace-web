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

exec "$@"
