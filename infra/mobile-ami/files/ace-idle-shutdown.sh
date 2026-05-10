#!/bin/bash
# Layer-2 idle watchdog. ace-web bumps /var/run/ace-mobile/last-activity
# via SSM at the start (and end) of every chargeable operation. If 5 minutes
# pass without a bump, halt the system. The EC2 instance is configured with
# `instance_initiated_shutdown_behavior=stop`, so `shutdown -h` stops the
# instance — Terraform's CloudWatch alarm at 5 min is the third-layer
# backstop in case this script ever fails to fire.
set -euo pipefail

MARKER=/var/run/ace-mobile/last-activity
IDLE_THRESHOLD_SECONDS=300  # 5 minutes

last=$(stat -c %Y "$MARKER" 2>/dev/null || echo 0)
now=$(date +%s)
delta=$(( now - last ))

if (( delta >= IDLE_THRESHOLD_SECONDS )); then
  echo "[$(date -u +%FT%TZ)] idle for ${delta}s (>= ${IDLE_THRESHOLD_SECONDS}s); halting"
  /usr/bin/sudo /sbin/shutdown -h now
else
  echo "[$(date -u +%FT%TZ)] idle for ${delta}s (< ${IDLE_THRESHOLD_SECONDS}s); staying up"
fi
