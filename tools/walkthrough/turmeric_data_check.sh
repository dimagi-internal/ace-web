#!/usr/bin/env bash
# Verify the Turmeric opp referenced by /tmp/turmeric-smoketest/slug.txt has
# enough lifecycle data for the turmeric-end-to-end walkthrough to succeed.
#
# canopy:walkthrough's pre-flight should call this before Scene 1 when the
# spec's data readiness can be checked programmatically. Exits non-zero if
# the opp's live state won't support scenes 2–5, and prints a short,
# actionable summary so the skill can surface it to the user verbatim.
#
# Exit codes:
#   0  slug's opp has >= MIN_COMPLETE skills (default 6); walkthrough is safe
#   2  prereq error (cookies missing, slug file missing, API unreachable)
#   3  slug exists but opp is underpopulated (< MIN_COMPLETE skills complete)
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
COOKIE_JAR="${TURMERIC_COOKIE_JAR:-/tmp/turmeric-smoketest/cookies.txt}"
SLUG_FILE="${TURMERIC_SLUG_FILE:-/tmp/turmeric-smoketest/slug.txt}"
MIN_COMPLETE="${TURMERIC_MIN_COMPLETE:-6}"

log() { echo "[turmeric-data-check] $*" >&2; }

[ -f "$COOKIE_JAR" ] || { log "cookies missing: $COOKIE_JAR — run turmeric_auth_login.sh"; exit 2; }
[ -f "$SLUG_FILE" ]  || { log "slug file missing: $SLUG_FILE — run turmeric_cli_setup.sh"; exit 2; }

SLUG="$(tr -d '[:space:]' < "$SLUG_FILE")"
[ -n "$SLUG" ] || { log "slug file is empty: $SLUG_FILE"; exit 2; }

API_URL="$BASE_URL/api/opps/$SLUG"
RESP="$(curl -sS -b "$COOKIE_JAR" -w '\n%{http_code}' "$API_URL")"
HTTP_CODE="$(echo "$RESP" | tail -n1)"
BODY="$(echo "$RESP" | sed '$d')"

if [ "$HTTP_CODE" != "200" ]; then
  log "GET $API_URL returned $HTTP_CODE"
  exit 2
fi

# Count completed skills in the current run.
SLUG="$SLUG" MIN_COMPLETE="$MIN_COMPLETE" BODY="$BODY" python3 <<'PY'
import json, os, sys
body = os.environ["BODY"]
data = json.loads(body)
envelope = data.get("data", data)
run = envelope["current_run"]
steps = run.get("steps", [])
done = [s["skill_name"] for s in steps if s.get("status") == "complete"]
has_judge = [s["skill_name"] for s in steps
             if s.get("status") == "complete" and s.get("judge_verdict")]
slug = os.environ["SLUG"]
min_c = int(os.environ["MIN_COMPLETE"])
total = len(steps)
print(f"slug={slug} run_id={run.get('run_id')} complete={len(done)}/{total} "
      f"with_judge={len(has_judge)} min_required={min_c}")
print("complete_skills=" + ",".join(done))
sys.exit(0 if len(done) >= min_c else 3)
PY
