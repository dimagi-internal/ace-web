#!/usr/bin/env bash
# Log in as ace@dimagi-ai.com via /auth/e2e-login/ and persist the
# session cookie to the shared cookie jar. Called by canopy:walkthrough
# via turmeric.yaml's auth.login hook.
#
# Required env:
#   ACE_E2E_AUTH_TOKEN    shared-secret from deploy/aws/task-definition.json
#
# Optional env:
#   ACE_WEB_BASE_URL      default: https://labs.connect.dimagi.com/ace
#   ACE_E2E_EMAIL         default: ace@dimagi-ai.com
#   TURMERIC_COOKIE_JAR   default: /tmp/turmeric-smoketest/cookies.txt
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
E2E_EMAIL="${ACE_E2E_EMAIL:-ace@dimagi-ai.com}"
COOKIE_JAR="${TURMERIC_COOKIE_JAR:-/tmp/turmeric-smoketest/cookies.txt}"

log() { echo "[turmeric-auth-login] $*" >&2; }

if [ -z "${ACE_E2E_AUTH_TOKEN:-}" ]; then
  log "ACE_E2E_AUTH_TOKEN not set."
  log "Copy it from deploy/aws/task-definition.json and export before running."
  exit 2
fi

mkdir -p "$(dirname "$COOKIE_JAR")"

log "e2e-login as $E2E_EMAIL -> $BASE_URL"
LOGIN_PAYLOAD="$(E2E_EMAIL="$E2E_EMAIL" ACE_E2E_AUTH_TOKEN="$ACE_E2E_AUTH_TOKEN" \
  python3 -c "
import json, os
print(json.dumps({
    'email': os.environ['E2E_EMAIL'],
    'token': os.environ['ACE_E2E_AUTH_TOKEN'],
}))
")"

HTTP_CODE=$(curl -sS -c "$COOKIE_JAR" -o /dev/null -w '%{http_code}' \
  -X POST "$BASE_URL/auth/e2e-login/" \
  -H "Content-Type: application/json" \
  --data-raw "$LOGIN_PAYLOAD")

if [ "$HTTP_CODE" != "200" ]; then
  log "e2e-login returned $HTTP_CODE"
  exit 3
fi

# Warm csrftoken_ace so subsequent POSTs work with the same jar.
curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null "$BASE_URL/"

log "session cookie written to $COOKIE_JAR"
# canopy:walkthrough reads the login command's stdout as "{token}" for
# inject_url substitution. We print a no-op token — our auth is already
# set in the cookie jar, so the inject_url is just a sanity-check nav
# on "/" to confirm the session works.
echo "cookies-in-jar"
