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

# Refresh the vendored ACE plugin to the latest dimagi-internal/ace main BEFORE
# anything reads the plugin tree (op-inject below reads $ACE_PLUGIN_PATH's
# .env.tpl; the chat backend's `claude -p` loads the cache dir). The plugin
# bumps several times a day but the image only rebuilds on ace-web's own
# merges — without this a plain deploy would keep shipping a stale plugin.
# Fully fail-safe: the script always exits 0 and leaves the baked plugin in
# place on any error, and `|| true` guards against `set -e` regardless.
if [ -f /app/scripts/refresh-ace-plugin.sh ]; then
    bash /app/scripts/refresh-ace-plugin.sh || true
fi

if [ -n "${ACE_DRIVE_SA_KEY_JSON:-}" ]; then
    mkdir -p "$PLUGIN_DATA_DIR"
    printf '%s' "$ACE_DRIVE_SA_KEY_JSON" > "$SA_KEY_PATH"
    chmod 600 "$SA_KEY_PATH"
    echo "[entrypoint] Wrote ACE plugin SA key to $SA_KEY_PATH"
    # Mirror to the derived-data-dir path that lib/plugin-data-dir.ts
    # composes when Claude Code passes ${CLAUDE_PLUGIN_DATA} through as a
    # literal (anthropics/claude-code#9427). Without this mirror, gdrive's
    # resolveKeyPath looks at /home/app/.claude/plugins/data/ace-ace/
    # gws-sa-key.json (not /home/app/.claude/plugin-data/ace/) and throws
    # "No Google service-account key found" at startup → the MCP exits
    # before responding to JSON-RPC initialize → the chat-side never sees
    # ace-gdrive tools. Verified live: with this mirror, gdrive starts
    # cleanly and registers its 22 tools in the deferred-tool registry.
    # Same pattern as the .env three-mirror in this same script.
    DERIVED_DATA_DIR="/home/app/.claude/plugins/data/ace-ace"
    mkdir -p "$DERIVED_DATA_DIR"
    cp -f "$SA_KEY_PATH" "$DERIVED_DATA_DIR/gws-sa-key.json" 2>/dev/null \
        && chmod 600 "$DERIVED_DATA_DIR/gws-sa-key.json" \
        && echo "[entrypoint] mirrored SA key to $DERIVED_DATA_DIR/gws-sa-key.json (derived-data-dir fallback)" \
        || echo "[entrypoint] could not mirror SA key to derived data dir — ace-gdrive may fail when Claude Code doesn't pass CLAUDE_PLUGIN_DATA"
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
    # Service-account auth (OP_SERVICE_ACCOUNT_TOKEN) doesn't accept --account;
    # the token's tied to a single sign-in URL already. Verified via
    # `op whoami` returning the integration without the flag.
    if op inject -i "$ACE_ENV_TPL" -o "$ACE_ENV_PATH" 2>/tmp/op-inject.err; then
        chmod 600 "$ACE_ENV_PATH"
        # Status file read by /api/system/version's env_inject block (ace-web#636).
        printf 'ok\n' > /tmp/op-inject.status
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
        # Also mirror to the path that lib/plugin-data-dir.ts derives from
        # import.meta.url when CLAUDE_PLUGIN_DATA isn't passed: it walks up
        # to find a `plugins/cache/<mp>/<plugin>/<v>/...` segment, then
        # composes a sibling `<plugins-root>/data/<mp>-<plugin>` path. With
        # the new install layout (cache=real-dir), import.meta.url resolves
        # cleanly into that pattern, so the derivation finds
        # /home/app/.claude/plugins/data/ace-ace/.env. Mirror there too so
        # both the cwd-fallback and the derivation-fallback resolve.
        # Repro from a live Tier C v6 chat: claude self-healed by running
        # `cp /home/app/.claude/plugin-data/ace/.env /home/app/.claude/plugins/data/ace-ace/.env`
        # mid-session before its first connect_list_programs call worked.
        DERIVED_DATA_DIR="/home/app/.claude/plugins/data/ace-ace"
        mkdir -p "$DERIVED_DATA_DIR"
        cp -f "$ACE_ENV_PATH" "$DERIVED_DATA_DIR/.env" 2>/dev/null \
            && chmod 600 "$DERIVED_DATA_DIR/.env" \
            && echo "[entrypoint] mirrored .env to $DERIVED_DATA_DIR/.env (derived-data-dir fallback)" \
            || echo "[entrypoint] could not mirror .env to derived data dir"
    else
        echo "[entrypoint] op inject FAILED — see /tmp/op-inject.err"
        head -c 500 /tmp/op-inject.err >&2
        echo "" >&2
        # Status file read by /api/system/version's env_inject block (ace-web#636):
        # a failed inject must flunk a health check, not just stderr.
        { printf 'failed\n'; head -c 500 /tmp/op-inject.err; } > /tmp/op-inject.status
        echo "[entrypoint] continuing without rendered .env; downstream ACE MCPs may fail to find OCS/HQ/Gmail creds"
    fi
elif [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    printf 'skipped\nOP_SERVICE_ACCOUNT_TOKEN not set\n' > /tmp/op-inject.status
    echo "[entrypoint] OP_SERVICE_ACCOUNT_TOKEN not set — skipping op inject. ACE plugin MCPs that need 1Password-backed creds (OCS, Connect, Gmail, HQ) will fail."
elif [ ! -f "$ACE_ENV_TPL" ]; then
    printf 'skipped\nno .env.tpl found\n' > /tmp/op-inject.status
    echo "[entrypoint] No .env.tpl found at $ACE_ENV_TPL — skipping op inject. Did the ACE plugin clone succeed?"
fi

# Register the user-scope Nova MCP shadow override.
#
# The Nova plugin's bundled MCP entry is OAuth-only. ace-web injects a
# refreshed OAuth bearer token into the plugin's rewritten .mcp.json via
# ``${NOVA_BEARER_TOKEN:-}`` (see Dockerfile + CLIBackend._stage_env_for),
# but that approach has two known problems on the production stack:
#
#   1. nova-plugin#2 — architect subagents dispatched via Agent
#      occasionally halt at turn 0 with zero tool calls; the headersHelper-
#      based OAuth flow doesn't reliably bind ``mcp__plugin_nova_nova__*``
#      tools to subagent contexts.
#   2. nova-plugin#13 — when both auth paths are visible, the architect
#      subagent uses a different Nova identity than the level-0 PAT,
#      producing apps invisible to ``upload_to_hq``.
#
# The same hack ``bin/ace-setup`` runs on local operator machines is the
# documented workaround until nova-plugin#16 ships first-class PAT
# support: register a user-scope MCP entry at the same URL with a bearer
# header. Claude Code's URL-signature dedup picks the user-scope entry
# over the plugin's OAuth entry; tools surface as ``mcp__nova__*`` and
# the architect subagent sees them. The plugin's OAuth entry continues
# to be the fallback when NOVA_API_KEY is unset.
#
# Writes to ``$HOME/.claude.json``. CLIBackend._stage_env_for symlinks
# this file into each per-session staged HOME so subprocess Claude Code
# instances inherit the override.
NOVA_KEY=""
if [ -f "$ACE_ENV_PATH" ]; then
    NOVA_KEY="$(grep -E '^NOVA_API_KEY=' "$ACE_ENV_PATH" | head -1 \
        | sed -E 's/^NOVA_API_KEY=//' | sed -E 's/^"(.*)"$/\1/')"
fi
if [ -z "$NOVA_KEY" ] || [ "${NOVA_KEY#op://}" != "$NOVA_KEY" ]; then
    echo "[entrypoint] nova_mcp: NOVA_API_KEY not resolved — Nova MCP will fall back to OAuth flow (architect subagents may halt at turn 0; see nova-plugin#2)"
elif ! command -v claude >/dev/null 2>&1; then
    echo "[entrypoint] nova_mcp: claude CLI not on PATH — cannot register user-scope override"
else
    # Idempotent: remove any prior user-scope entry (e.g. stale token from
    # a previous container generation), then re-add with the current key.
    claude mcp remove nova --scope user >/dev/null 2>&1 || true
    if claude mcp add nova "https://mcp.commcare.app/mcp" \
            --transport http \
            --scope user \
            --header "Authorization: Bearer $NOVA_KEY" >/dev/null 2>&1; then
        echo "[entrypoint] nova_mcp: user-scope bearer override registered at https://mcp.commcare.app/mcp"
    else
        echo "[entrypoint] nova_mcp: claude mcp add failed — Nova MCP will fall back to OAuth flow"
    fi
fi

exec "$@"
