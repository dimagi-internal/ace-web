#!/usr/bin/env bash
# Turmeric CLI smoke-test setup.
#
# Authenticates as ace@dimagi-ai.com via /auth/e2e-login/ (no personal
# tokens, no OAuth flow) and drives the CLI path of the walkthrough:
# create opp via API → run /ace:run to produce a transcript → upload
# transcript via session cookie → poll until the opp is visible.
#
# Required env:
#   ACE_E2E_AUTH_TOKEN    shared-secret from deploy/aws/task-definition.json
#                         or AWS Secrets Manager.
#
# Optional env:
#   ACE_WEB_BASE_URL      default: https://labs.connect.dimagi.com/ace
#   ACE_E2E_EMAIL         default: ace@dimagi-ai.com
#   TURMERIC_PDD_PATH     default: /tmp/turmeric-smoketest/pdd.txt
#                         plain-text body of the Turmeric PDD. Fetch via
#                         the ACE plugin's Drive MCP or the Python helper.
#
# Exit codes:
#   0  opp created, transcript uploaded, opp visible in /opps
#   2  config/prereq error (missing token, missing PDD file, claude not on PATH)
#   3  e2e-login refused or did not return a session cookie
#   4  API call failed (opp create, ace run, ingest upload)
#   5  opp never became visible within the poll window
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
E2E_EMAIL="${ACE_E2E_EMAIL:-ace@dimagi-ai.com}"
PDD_PATH="${TURMERIC_PDD_PATH:-/tmp/turmeric-smoketest/pdd.txt}"
WORK_DIR="/tmp/turmeric-smoketest"
COOKIE_JAR="$WORK_DIR/cookies.txt"
SLUG_FILE="$WORK_DIR/slug.txt"
STAMP="$(date +%Y%m%d-%H%M)"
SLUG="turmeric-smoketest-${STAMP}"
DISPLAY_NAME="Turmeric Smoketest ${STAMP}"
JSONL_PATH="$WORK_DIR/transcript-${STAMP}.jsonl"

log() { echo "[cli-setup] $*" >&2; }

mkdir -p "$WORK_DIR"

# --- Prereqs ---------------------------------------------------------------

[ -n "${ACE_E2E_AUTH_TOKEN:-}" ] || {
  log "ACE_E2E_AUTH_TOKEN not set."
  log "Copy the value from deploy/aws/task-definition.json and export it."
  exit 2
}

[ -f "$PDD_PATH" ] || {
  log "PDD body not found at $PDD_PATH"
  log "Write the Turmeric PDD body there first. Easiest: use the ACE plugin's"
  log "drive_read_file MCP tool to pull the latest PDD from the Program Design"
  log "Docs folder under the ACE Drive root and redirect to that path."
  exit 2
}

command -v claude >/dev/null 2>&1 || {
  log "claude CLI not on PATH — install Claude Code first"
  exit 2
}

# --- 1. e2e-login → session cookie -----------------------------------------

log "e2e-login as $E2E_EMAIL"
LOGIN_PAYLOAD="$(E2E_EMAIL="$E2E_EMAIL" ACE_E2E_AUTH_TOKEN="$ACE_E2E_AUTH_TOKEN" \
  python3 -c "
import json, os
print(json.dumps({
    'email': os.environ['E2E_EMAIL'],
    'token': os.environ['ACE_E2E_AUTH_TOKEN'],
}))
")"

HTTP_CODE=$(curl -sS -c "$COOKIE_JAR" -o "$WORK_DIR/login-resp.json" -w '%{http_code}' \
  -X POST "$BASE_URL/auth/e2e-login/" \
  -H "Content-Type: application/json" \
  --data-raw "$LOGIN_PAYLOAD")

if [ "$HTTP_CODE" != "200" ]; then
  log "e2e-login returned $HTTP_CODE"
  cat "$WORK_DIR/login-resp.json" >&2
  exit 3
fi

# Verify we got a session cookie. Cookie name is path-scoped for labs.
SESSION_COOKIE=$(awk '$6 == "sessionid_ace" { print $7 }' "$COOKIE_JAR" | tail -n 1)
if [ -z "$SESSION_COOKIE" ]; then
  log "e2e-login succeeded but no sessionid_ace cookie in response"
  exit 3
fi
log "session established (sessionid_ace=${SESSION_COOKIE:0:8}...)"

# Warm the csrftoken_ace cookie — Django doesn't set it until a view hit by
# CsrfViewMiddleware renders. A single GET on /ace/ is enough.
curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null "$BASE_URL/"
CSRF_TOKEN=$(awk '$6 == "csrftoken_ace" { print $7 }' "$COOKIE_JAR" | tail -n 1)
log "csrftoken_ace=${CSRF_TOKEN:0:8}..."

# --- 2. POST /api/opps/ → create the opp -----------------------------------

log "creating opp $SLUG (seeding pdd.md so workbench has content)"
CREATE_PAYLOAD="$(PDD_PATH="$PDD_PATH" SLUG="$SLUG" DISPLAY_NAME="$DISPLAY_NAME" \
  python3 -c "
import json, os
with open(os.environ['PDD_PATH']) as f:
    body = f.read()
# Pass the same body as both 'idea' (short description) and 'pdd' (full
# document). This pre-populates the idea-to-pdd artifact so the workbench
# preview isn't empty on first load. /ace:run would normally generate
# pdd.md from idea.md, but --dry-run doesn't execute the skill.
print(json.dumps({
    'slug': os.environ['SLUG'],
    'display_name': os.environ['DISPLAY_NAME'],
    'idea': body,
    'pdd': body,
    'mode': 'auto',
}))
")"

HTTP_CODE=$(curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -o "$WORK_DIR/opp-create-resp.json" -w '%{http_code}' \
  -X POST "$BASE_URL/api/opps/" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF_TOKEN" \
  -H "Referer: $BASE_URL/" \
  --data-raw "$CREATE_PAYLOAD")

if [ "$HTTP_CODE" != "201" ]; then
  log "POST /api/opps/ returned $HTTP_CODE"
  cat "$WORK_DIR/opp-create-resp.json" >&2
  exit 4
fi
log "opp created"

# --- 3. /ace:run → JSONL transcript ----------------------------------------

log "running /ace:run $SLUG --dry-run --mode auto (burns LLM tokens)"
claude -p "/ace:run $SLUG --dry-run --mode auto" \
  --output-format stream-json --verbose \
  > "$JSONL_PATH"
log "transcript written to $JSONL_PATH ($(wc -l < "$JSONL_PATH") lines)"

# --- 4. Upload transcript via session cookie -------------------------------

log "uploading transcript to $BASE_URL/api/ingest/upload"
HTTP_CODE=$(curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -o "$WORK_DIR/ingest-resp.json" -w '%{http_code}' \
  -X POST "$BASE_URL/api/ingest/upload" \
  -H "X-CSRFToken: $CSRF_TOKEN" \
  -H "Referer: $BASE_URL/" \
  -F "file=@$JSONL_PATH;type=application/x-ndjson")

if [ "$HTTP_CODE" != "201" ]; then
  log "POST /api/ingest/upload returned $HTTP_CODE"
  cat "$WORK_DIR/ingest-resp.json" >&2
  exit 4
fi
log "transcript ingested: $(cat "$WORK_DIR/ingest-resp.json")"

# --- 5. Poll /api/opps/<slug> until ready ----------------------------------

log "polling $BASE_URL/api/opps/$SLUG for Drive-sync completion..."
HTTP_CODE=""
for i in $(seq 1 30); do
  HTTP_CODE=$(curl -sS -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' \
    "$BASE_URL/api/opps/$SLUG")
  if [ "$HTTP_CODE" = "200" ]; then
    log "opp visible after ${i} polls"
    break
  fi
  sleep 2
done

if [ "$HTTP_CODE" != "200" ]; then
  log "opp never became visible (last HTTP $HTTP_CODE)"
  exit 5
fi

# --- 6. Persist the slug for /walkthrough turmeric -------------------------

echo "$SLUG" > "$SLUG_FILE"
log "wrote slug to $SLUG_FILE"
log "next: run /walkthrough turmeric in Claude Code to verify the opp in the UI"
