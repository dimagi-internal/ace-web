#!/usr/bin/env bash
# Turmeric CLI smoke-test setup.
#
# Flow:
#   1. Find the latest Turmeric PDD in Drive.
#   2. POST /api/opps/ on prod to create the opp (seeded with PDD body).
#   3. Run `claude -p "/ace:run <slug> --dry-run --mode auto"`.
#   4. Capture the resulting JSONL transcript path.
#   5. ace-upload the transcript.
#   6. Poll /api/opps/<slug>/ until 200 (Drive sync complete).
#   7. Write the slug to /tmp/turmeric-smoketest-slug.txt.
#
# Exit codes match turmeric_web_setup.py (0, 2, 3, 4, 5).
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
CONFIG_TOML="${ACE_CONFIG_TOML:-$HOME/.ace/config.toml}"
SLUG_FILE="/tmp/turmeric-smoketest-slug.txt"
STAMP="$(date +%Y%m%d-%H%M)"
SLUG="turmeric-smoketest-${STAMP}"
DISPLAY_NAME="Turmeric Smoketest ${STAMP}"

log() { echo "[cli-setup] $*" >&2; }

# 0. Prereq checks
[ -f "$CONFIG_TOML" ] || { log "missing $CONFIG_TOML — run: ace-upload --configure"; exit 2; }
command -v claude >/dev/null || { log "claude CLI not on PATH"; exit 2; }
command -v ace-upload >/dev/null || { log "ace-upload CLI not on PATH"; exit 2; }

# 1. Fetch the latest Turmeric PDD body from Drive via the Python helper.
log "looking up latest Turmeric PDD..."
PDD_BODY="$(python -m tools.walkthrough.turmeric_pdd_finder --print-body)" || {
  log "PDD finder failed"
  exit 3
}
log "PDD body length: ${#PDD_BODY} chars"

# 2. Extract the personal token from ~/.ace/config.toml.
TOKEN="$(python -c "import tomllib; print(tomllib.load(open('$CONFIG_TOML', 'rb'))['token'])")"
SERVER="$(python -c "import tomllib; print(tomllib.load(open('$CONFIG_TOML', 'rb'))['server'])")"

# 3. POST /api/opps/ to create the opp.
log "creating opp $SLUG via API"
CREATE_PAYLOAD="$(python -c "
import json, sys
body = sys.stdin.read()
print(json.dumps({
  'slug': '$SLUG',
  'display_name': '$DISPLAY_NAME',
  'idea': body,
  'mode': 'auto',
}))
" <<< "$PDD_BODY")"

HTTP_CODE=$(curl -sS -o /tmp/opp-create-resp.json -w "%{http_code}" \
  -X POST "$SERVER/api/opps/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-raw "$CREATE_PAYLOAD")
if [ "$HTTP_CODE" != "201" ]; then
  log "POST /api/opps/ returned $HTTP_CODE — body:"
  cat /tmp/opp-create-resp.json >&2
  exit 4
fi

# 4. Invoke /ace:run via `claude -p`.
log "running /ace:run $SLUG --dry-run --mode auto"
JSONL_PATH="/tmp/turmeric-cli-transcript-${STAMP}.jsonl"
claude -p "/ace:run $SLUG --dry-run --mode auto" \
  --output-format stream-json --verbose \
  > "$JSONL_PATH"
log "transcript: $JSONL_PATH ($(wc -l < "$JSONL_PATH") lines)"

# 5. Upload the transcript.
log "uploading transcript via ace-upload"
ace-upload "$JSONL_PATH" || { log "ace-upload failed"; exit 4; }

# 6. Poll the opp endpoint until it's browsable.
log "polling $SERVER/api/opps/$SLUG/ for Drive sync..."
HTTP_CODE=""
for i in $(seq 1 30); do
  HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" "$SERVER/api/opps/$SLUG")
  if [ "$HTTP_CODE" = "200" ]; then
    log "opp visible"
    break
  fi
  sleep 2
done
[ "$HTTP_CODE" = "200" ] || { log "opp never became visible"; exit 5; }

# 7. Write slug.
echo "$SLUG" > "$SLUG_FILE"
log "wrote slug to $SLUG_FILE"
