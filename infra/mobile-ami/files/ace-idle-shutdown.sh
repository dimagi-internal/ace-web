#!/bin/bash
# Layer-2 idle watchdog. ace-web bumps /var/run/ace-mobile/last-activity
# via SSM at the start (and end) of every chargeable operation. If the
# idle threshold passes without a bump, halt the system. The EC2
# instance is configured with `instance_initiated_shutdown_behavior=stop`,
# so `shutdown -h` stops the instance — the CloudWatch alarm
# `ace-mobile-emulator-idle-stop-labs` is the third-layer backstop in
# case this script ever fails to fire.
#
# Threshold is overridable via /etc/default/ace-idle-shutdown (KEY=VAL,
# sourced if present). Useful during heavy dev to widen the window
# without rebaking; bake-time default is 60 min so the runner doesn't
# auto-stop mid-iteration. Trim back down (or rely on the CloudWatch
# alarm) once an opp is in steady state.
set -euo pipefail

MARKER=/var/run/ace-mobile/last-activity
IDLE_THRESHOLD_SECONDS=3600  # 60 minutes — dev-friendly default
[ -r /etc/default/ace-idle-shutdown ] && . /etc/default/ace-idle-shutdown

last=$(stat -c %Y "$MARKER" 2>/dev/null || echo 0)
now=$(date +%s)
delta=$(( now - last ))

if (( delta >= IDLE_THRESHOLD_SECONDS )); then
  echo "[$(date -u +%FT%TZ)] idle for ${delta}s (>= ${IDLE_THRESHOLD_SECONDS}s); halting"
  /usr/bin/sudo /sbin/shutdown -h now
else
  echo "[$(date -u +%FT%TZ)] idle for ${delta}s (< ${IDLE_THRESHOLD_SECONDS}s); staying up"
fi
