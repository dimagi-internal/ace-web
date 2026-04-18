#!/usr/bin/env bash
# Does the shared cookie jar already have a valid ace-web session?
# Called by canopy:walkthrough via turmeric.yaml's auth.check hook.
#
# Returns 0 if authenticated, non-zero otherwise. The walkthrough skill
# interprets non-zero as "expired or missing" and invokes the login
# script next.
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
COOKIE_JAR="${TURMERIC_COOKIE_JAR:-/tmp/turmeric-smoketest/cookies.txt}"

[ -f "$COOKIE_JAR" ] || exit 1

# Hit an auth-required endpoint. 200 → authed; 401/302-to-login → not.
HTTP_CODE=$(curl -sS -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' \
  "$BASE_URL/api/opps/")

[ "$HTTP_CODE" = "200" ]
