#!/bin/bash
# Refresh the vendored ACE plugin to the latest dimagi-internal/ace `main` at
# container start.
#
# Why this exists: the plugin is baked into the image at build time
# (Dockerfile clones dimagi-internal/ace at the SHA resolved by build-backend.yml).
# But dimagi-internal/ace bumps several times a day, while ace-web only rebuilds
# its image on its OWN merges to main. So the deployed plugin lags the
# plugin repo — the "v0.13.494 deployed / v0.13.502 available" drift the
# System Overview tab surfaces. A plain `deploy-ace-web-labs.yml` run only
# re-rolls the existing image, so it never moved the plugin forward.
#
# This script makes every task self-update on boot: it shallow-clones the
# current `main`, and if its VERSION differs from the baked one, swaps the
# fresh tree into Claude Code's plugin cache. Net effect — a plain deploy
# (which replaces tasks) now picks up the latest plugin on EVERY task, no
# image rebuild required, and it scales correctly to >1 task (each task
# refreshes its own ephemeral layer; there is no shared plugin volume).
#
# Fail-safe by construction: any failure (GitHub unreachable, npm error,
# malformed clone) logs and leaves the baked plugin untouched — container
# start never blocks on this. The baked clone is always the fallback.
#
# Kill-switch: set ACE_PLUGIN_AUTO_UPDATE=false to skip entirely (offline
# boots, or to pin a task to exactly the baked version). This is an
# operational knob, not a product feature flag.

set -u

log() { echo "[refresh-ace-plugin] $*"; }

PLUGIN_PATH="${ACE_PLUGIN_PATH:-/app/vendor/ace}"
CACHE_ROOT="/home/app/.claude/plugins/cache/ace/ace"
INSTALLED_JSON="/home/app/.claude/plugins/installed_plugins.json"
REPO_URL="https://github.com/dimagi-internal/ace.git"
REFRESH_TIMEOUT="${ACE_PLUGIN_REFRESH_TIMEOUT:-150}"
# Temp dir adjacent to the cache so the final swap (and node_modules reuse)
# is a cheap same-filesystem rename rather than a cross-device copy.
TMP_DIR="${CACHE_ROOT}/.refresh.$$"

current_version="$(cat "${PLUGIN_PATH}/VERSION" 2>/dev/null || echo unknown)"

if [ "${ACE_PLUGIN_AUTO_UPDATE:-true}" = "false" ]; then
    log "ACE_PLUGIN_AUTO_UPDATE=false — keeping baked plugin ${current_version}"
    exit 0
fi

cleanup() { rm -rf "$TMP_DIR" 2>/dev/null || true; }
trap cleanup EXIT

# --- Fetch latest main -------------------------------------------------------
rm -rf "$TMP_DIR"
if ! mkdir -p "$CACHE_ROOT"; then
    log "cannot create cache root ${CACHE_ROOT} — keeping baked plugin ${current_version}"
    exit 0
fi
if ! timeout "$REFRESH_TIMEOUT" git clone --depth 1 "$REPO_URL" "$TMP_DIR" \
        >/tmp/ace-refresh.log 2>&1; then
    log "git clone failed (see /tmp/ace-refresh.log) — keeping baked plugin ${current_version}"
    exit 0
fi

new_version="$(cat "${TMP_DIR}/VERSION" 2>/dev/null || echo unknown)"
if [ "$new_version" = "unknown" ]; then
    log "cloned tree has no VERSION — keeping baked plugin ${current_version}"
    exit 0
fi
if [ "$new_version" = "$current_version" ]; then
    log "already at latest (${current_version}) — no refresh needed"
    exit 0
fi

log "refreshing ACE plugin ${current_version} → ${new_version}"

# --- node_modules ------------------------------------------------------------
# The plugin's MCP servers need node_modules present. Most plugin bumps are
# skill/agent markdown edits with an unchanged lockfile — in that case reuse
# the baked install (an instant same-fs rename) instead of a fresh npm
# install. Only reinstall when the lockfile actually moved.
OLD_TARGET="$(readlink -f "$PLUGIN_PATH" 2>/dev/null || true)"
reuse_modules=false
if [ -n "$OLD_TARGET" ] && [ -d "${OLD_TARGET}/node_modules" ] \
        && [ -f "${OLD_TARGET}/package-lock.json" ] && [ -f "${TMP_DIR}/package-lock.json" ]; then
    old_hash="$(sha256sum < "${OLD_TARGET}/package-lock.json" | cut -d' ' -f1)"
    new_hash="$(sha256sum < "${TMP_DIR}/package-lock.json" | cut -d' ' -f1)"
    [ "$old_hash" = "$new_hash" ] && reuse_modules=true
fi

if [ "$reuse_modules" = true ]; then
    log "package-lock unchanged — reusing baked node_modules"
    mv "${OLD_TARGET}/node_modules" "${TMP_DIR}/node_modules" 2>/dev/null || reuse_modules=false
fi
if [ "$reuse_modules" != true ]; then
    log "installing npm deps for ${new_version}"
    if ! (cd "$TMP_DIR" && timeout "$REFRESH_TIMEOUT" npm install --no-audit --no-fund \
            >>/tmp/ace-refresh.log 2>&1); then
        log "npm install failed (see /tmp/ace-refresh.log) — keeping baked plugin ${current_version}"
        exit 0
    fi
fi

# Match the baked layout (Dockerfile does `rm -rf .git` after cloning).
rm -rf "${TMP_DIR}/.git"

# --- Swap into place ---------------------------------------------------------
# Order matters: stage the new tree, repoint the symlink, and only then drop
# the old dir — so nothing ever points at a missing path mid-swap.
NEW_CACHE_DIR="${CACHE_ROOT}/${new_version}"
rm -rf "$NEW_CACHE_DIR"
if ! mv "$TMP_DIR" "$NEW_CACHE_DIR"; then
    log "failed to stage new tree at ${NEW_CACHE_DIR} — keeping baked plugin ${current_version}"
    exit 0
fi
trap - EXIT  # TMP_DIR has been moved; nothing left to clean up.

# Repoint /app/vendor/ace (consumed by ACE_PLUGIN_PATH: System Overview tab,
# entrypoint op-inject). ln -sfn replaces the symlink in place. The cache dir
# itself stays a REAL directory — Claude Code 2.x deletes symlinked cache
# entries at runtime, so we never make the cache path a symlink.
ln -sfn "$NEW_CACHE_DIR" "$PLUGIN_PATH"

# Update installed_plugins.json so `claude` self-reports the new path+version.
# Best-effort: a failure here doesn't undo the swap (the loader resolves the
# plugin by installPath, which we keep valid).
python3 - "$INSTALLED_JSON" "$NEW_CACHE_DIR" "$new_version" <<'PY' || log "installed_plugins.json update skipped"
import datetime, json, sys

path, install_path, version = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    data = json.load(f)
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
for entry in data.get("plugins", {}).get("ace@ace", []):
    entry["installPath"] = install_path
    entry["version"] = version
    entry["lastUpdated"] = now
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

# Drop the previous cache dir last.
if [ -n "$OLD_TARGET" ] && [ "$OLD_TARGET" != "$NEW_CACHE_DIR" ] && [ -d "$OLD_TARGET" ]; then
    rm -rf "$OLD_TARGET" 2>/dev/null || true
fi

log "ACE plugin refreshed to ${new_version} at ${NEW_CACHE_DIR}"
