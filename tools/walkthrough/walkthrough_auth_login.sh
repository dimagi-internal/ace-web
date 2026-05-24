#!/usr/bin/env bash
# Trade an ACE_WEB_PAT_TOKEN PAT for a Django session cookie via
# POST /api/auth/pat-to-session, then persist the cookie to the shared
# cookie jar. Called by canopy:walkthrough via any ace-web walkthrough's
# auth.login hook. Also imports cookies into the gstack browse profile
# so the walkthrough's Chromium session is authenticated for
# browser-driven scenes.
#
# Why the PAT-to-cookie hop: browsers can't set custom headers on
# WebSocket upgrades and curl's cookie jar is the lingua franca for
# subsequent CLI + browse calls. POST /api/auth/pat-to-session is
# designed exactly for this hop (apps/auth/api.py:pat_to_session).
#
# Generic (not turmeric-specific) — works for any ace-web walkthrough
# against any deployed instance.
#
# Required env:
#   ACE_WEB_PAT_TOKEN     Bearer PAT. Mint one via /ace:ace-web-pat-mint.
#
# Optional env:
#   ACE_WEB_BASE_URL      default: https://labs.connect.dimagi.com/ace
#   ACE_WEB_COOKIE_JAR    default: /tmp/ace-web-walkthrough/cookies.txt
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
COOKIE_JAR="${ACE_WEB_COOKIE_JAR:-${TURMERIC_COOKIE_JAR:-/tmp/ace-web-walkthrough/cookies.txt}}"

log() { echo "[walkthrough-auth-login] $*" >&2; }

if [ -z "${ACE_WEB_PAT_TOKEN:-}" ]; then
  log "ACE_WEB_PAT_TOKEN not set."
  log "Mint one via /ace:ace-web-pat-mint and export before running."
  exit 2
fi

mkdir -p "$(dirname "$COOKIE_JAR")"

log "pat-to-session -> $BASE_URL"
HTTP_CODE=$(curl -sS -c "$COOKIE_JAR" -o /dev/null -w '%{http_code}' \
  -X POST "$BASE_URL/api/auth/pat-to-session" \
  -H "Authorization: Bearer $ACE_WEB_PAT_TOKEN")

if [ "$HTTP_CODE" != "204" ] && [ "$HTTP_CODE" != "200" ]; then
  log "pat-to-session returned $HTTP_CODE"
  exit 3
fi

# Warm csrftoken_ace so subsequent POSTs work with the same jar.
curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null "$BASE_URL/"

log "session cookie written to $COOKIE_JAR"

# Also import cookies into gstack browse (Chromium) so canopy:walkthrough's
# browser session is authenticated. The curl jar is separate from the
# browse persistent profile.
BROWSE_BIN="${BROWSE_BIN:-$HOME/.claude/skills/gstack/browse/dist/browse}"
if [ -x "$BROWSE_BIN" ]; then
  # browse requires an origin-matching page before accepting cookies (v1.1.x).
  "$BROWSE_BIN" goto "$BASE_URL" >/dev/null 2>&1 || true
  COOKIE_JSON="$(dirname "$COOKIE_JAR")/cookies.json"
  COOKIE_JAR_PATH="$COOKIE_JAR" BASE_URL_ENV="$BASE_URL" python3 -c "
import json, os, sys
from urllib.parse import urlparse

host = urlparse(os.environ['BASE_URL_ENV']).hostname
cookies = []
with open(os.environ['COOKIE_JAR_PATH']) as f:
    for line in f:
        line = line.rstrip('\n')
        if not line.strip():
            continue
        # Netscape format prefixes HTTP-only cookies with '#HttpOnly_' in
        # the domain column. Strip that before skipping comments, otherwise
        # sessionid_ace (and any other HttpOnly cookie) gets dropped.
        http_only = False
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
            http_only = True
        elif line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 7:
            continue
        domain, _, path, secure, expires, name, value = parts[:7]
        cookies.append({
            'name': name,
            'value': value,
            'domain': host,
            'path': path,
            'secure': secure == 'TRUE',
            'httpOnly': http_only,
            'sameSite': 'Lax',
        })
json.dump(cookies, sys.stdout)
" > "$COOKIE_JSON"
  "$BROWSE_BIN" cookie-import "$COOKIE_JSON" >&2 || log "browse cookie-import failed (non-fatal)"
  log "imported $(python3 -c "import json; print(len(json.load(open('$COOKIE_JSON'))))") cookies into browse"
fi

# canopy:walkthrough reads the login command's stdout as "{token}" for
# inject_url substitution. We print a no-op token — our auth is already
# set in the cookie jar + browse profile, so the inject_url is just a
# sanity-check nav on "/" to confirm the session works.
echo "cookies-in-jar"
