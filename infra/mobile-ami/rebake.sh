#!/bin/bash
# rebake.sh — bake a new mobile AMI and roll it into service end-to-end.
#
# What this does (in order):
#
#   1.  Packer-bake a new AMI (~35 min, ~$1.62 of c5n.metal compute).
#   2.  Parse the AMI ID + name (e.g. 2026-05-12-2142) from Packer's output.
#   3.  Create a new launch-template version pointing at the new AMI.
#   4.  Set the new version as the launch template's default.
#   5.  Terminate the currently-running EC2 instance (id pulled from the
#       committed deploy/aws/task-definition.json — that's the source of
#       truth on which instance ace-web believes it owns).
#   6.  Launch a fresh instance from the launch template into the same
#       subnet, wait until it's `running`, then stop it (ace-web starts
#       it on demand via /api/mobile/ensure-running).
#   7.  Re-apply the standard tags so the new instance matches the old.
#   8.  Rewrite deploy/aws/task-definition.json with the new
#       ACE_MOBILE_INSTANCE_ID and ACE_MOBILE_AMI_VERSION.
#   9.  Commit, push, open a PR, merge it.
#  10.  Trigger the deploy workflow (no migrations) so ace-web picks
#       up the new env vars.
#
# WHY THIS EXISTS (and why it bypasses terraform):
#
# infra/mobile/ ships terraform definitions for these resources, but the
# state file has only ever lived on individual operator laptops and was
# functionally lost between machines (no S3 backend configured, no state
# checked in, none recoverable when the cloud-emulator review surfaced
# this in May 2026). Continuing to pretend terraform is the source of
# truth here is a footgun — apply-from-nothing would try to recreate
# the EC2 instance and the launch template, which already exist and are
# tagged `managed-by:terraform`. AWS CLI direct keeps the existing
# resources, threads through cleanly, and is the actual workflow the
# team has been doing by hand. If you ever need terraform back, the
# import path is `aws_launch_template.mobile` + `aws_instance.mobile`
# against the real IDs — but until then, this script is the
# repeatable form.
#
# Usage:
#
#   AWS_PROFILE=labs ./rebake.sh                  # full cycle (~40 min)
#   AWS_PROFILE=labs ./rebake.sh --skip-bake AMI  # roll an already-baked AMI
#                                                 # (use when the previous
#                                                 # run got past bake but
#                                                 # failed somewhere later)
#   AWS_PROFILE=labs ./rebake.sh --dry-run        # print what would happen
#
# Required tools: packer (>=1.10) + amazon plugin, aws CLI v2, gh CLI,
# jq, git.
# Required env: AWS_PROFILE for an SSO session against the labs account.

set -euo pipefail

# ───────────────────────────────────────────────────────────────────────
# Config knobs — override via env if your account / region differs.
# ───────────────────────────────────────────────────────────────────────
REGION="${REGION:-us-east-1}"
LT_NAME="${LT_NAME:-ace-mobile-emulator-labs}"
SUBNET_ID="${SUBNET_ID:-subnet-0d744956f8178d950}"
DEPLOY_WORKFLOW="${DEPLOY_WORKFLOW:-deploy-ace-web-labs.yml}"

# Path to the task-definition.json (relative to repo root). The script
# parses + rewrites it as the source of truth on which instance is in
# service.
TASK_DEF_REL="deploy/aws/task-definition.json"

# Working dir is this script's dir (infra/mobile-ami). Packer is invoked
# from here; repo root is two levels up for git/gh operations.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TASK_DEF="$REPO_ROOT/$TASK_DEF_REL"

# ───────────────────────────────────────────────────────────────────────
# CLI parsing.
# ───────────────────────────────────────────────────────────────────────
SKIP_BAKE=""
SKIP_BAKE_AMI=""
DRY_RUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-bake)
      SKIP_BAKE=1
      SKIP_BAKE_AMI="${2:-}"
      if [[ -z "$SKIP_BAKE_AMI" ]]; then
        echo "ERROR: --skip-bake requires an AMI ID argument" >&2
        exit 2
      fi
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

run() {
  if [[ -n "$DRY_RUN" ]]; then
    echo "  [dry-run] $*"
  else
    eval "$@"
  fi
}

note() { echo "==> $*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

# ───────────────────────────────────────────────────────────────────────
# Preflight.
# ───────────────────────────────────────────────────────────────────────
note "Preflight: tools + AWS auth"
for cmd in aws gh jq git packer; do
  command -v "$cmd" >/dev/null || fail "missing required tool: $cmd"
done
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  fail "AWS auth failed — is AWS_PROFILE set to a valid SSO session?"
fi
gh auth status >/dev/null 2>&1 || fail "gh CLI is not authenticated"

# ───────────────────────────────────────────────────────────────────────
# Step 1-3: bake + parse AMI ID.
# ───────────────────────────────────────────────────────────────────────
if [[ -n "$SKIP_BAKE" ]]; then
  AMI_ID="$SKIP_BAKE_AMI"
  note "Skipping bake; using provided AMI: $AMI_ID"
else
  note "Step 1: packer build (~35 min on c5n.metal)"
  cd "$SCRIPT_DIR"
  BAKE_LOG="$(mktemp -t ace-mobile-bake.XXXXXX.log)"
  if [[ -n "$DRY_RUN" ]]; then
    echo "  [dry-run] packer build . | tee $BAKE_LOG"
    AMI_ID="ami-DRYRUN0000000000"
  else
    packer init . >/dev/null
    packer build . 2>&1 | tee "$BAKE_LOG"
    AMI_ID="$(grep -Eo 'ami-[0-9a-f]{8,17}' "$BAKE_LOG" | tail -1)"
    [[ -n "$AMI_ID" ]] || fail "couldn't parse AMI ID from packer output ($BAKE_LOG)"
    note "Bake produced: $AMI_ID (log: $BAKE_LOG)"
  fi
fi

# AMI version is the timestamped suffix on the AMI Name tag, e.g.
# `ace-mobile-emulator-2026-05-12-2142` → `2026-05-12-2142`. Falls back
# to today's date for --dry-run.
if [[ -n "$DRY_RUN" ]]; then
  AMI_VERSION="$(date -u +%Y-%m-%d-%H%M)"
else
  AMI_NAME="$(aws ec2 describe-images --image-ids "$AMI_ID" \
    --query 'Images[0].Name' --output text)"
  AMI_VERSION="${AMI_NAME#ace-mobile-emulator-}"
  [[ "$AMI_VERSION" != "$AMI_NAME" ]] || \
    fail "AMI Name '$AMI_NAME' doesn't match expected prefix"
fi
note "AMI version: $AMI_VERSION"

# ───────────────────────────────────────────────────────────────────────
# Step 4-5: new LT version + set default.
# ───────────────────────────────────────────────────────────────────────
note "Step 4: create new launch-template version with $AMI_ID"
if [[ -n "$DRY_RUN" ]]; then
  echo "  [dry-run] aws ec2 create-launch-template-version ..."
  NEW_LT_VER="99"
else
  NEW_LT_VER="$(aws ec2 create-launch-template-version \
    --launch-template-name "$LT_NAME" \
    --source-version '$Latest' \
    --version-description "AMI $AMI_VERSION ($AMI_ID) — rebake.sh" \
    --launch-template-data "{\"ImageId\":\"$AMI_ID\"}" \
    --query 'LaunchTemplateVersion.VersionNumber' --output text)"
fi
note "  → version $NEW_LT_VER"

note "Step 5: set version $NEW_LT_VER as default"
run aws ec2 modify-launch-template \
  --launch-template-name "$LT_NAME" \
  --default-version "$NEW_LT_VER" \
  '>/dev/null'

# ───────────────────────────────────────────────────────────────────────
# Step 6: terminate the current instance.
# ───────────────────────────────────────────────────────────────────────
OLD_INSTANCE_ID="$(jq -r '.containerDefinitions[0].environment[]
  | select(.name=="ACE_MOBILE_INSTANCE_ID") | .value' "$TASK_DEF")"
[[ "$OLD_INSTANCE_ID" =~ ^i-[0-9a-f]+$ ]] || \
  fail "couldn't read ACE_MOBILE_INSTANCE_ID from $TASK_DEF (got: $OLD_INSTANCE_ID)"
note "Step 6: terminate old instance $OLD_INSTANCE_ID"
run aws ec2 terminate-instances --instance-ids "$OLD_INSTANCE_ID" '>/dev/null'

# ───────────────────────────────────────────────────────────────────────
# Step 7-9: launch new instance, wait, stop, tag.
# ───────────────────────────────────────────────────────────────────────
note "Step 7: launch new instance from $LT_NAME (default version)"
if [[ -n "$DRY_RUN" ]]; then
  echo "  [dry-run] aws ec2 run-instances --launch-template ..."
  NEW_INSTANCE_ID="i-DRYRUN0000000000"
else
  NEW_INSTANCE_ID="$(aws ec2 run-instances \
    --launch-template "LaunchTemplateName=$LT_NAME,Version=\$Default" \
    --subnet-id "$SUBNET_ID" \
    --query 'Instances[0].InstanceId' --output text)"
fi
note "  → $NEW_INSTANCE_ID"

note "Step 8: wait for instance-running"
run aws ec2 wait instance-running --instance-ids "$NEW_INSTANCE_ID"

note "Step 9a: stop the new instance (ace-web starts it on demand)"
run aws ec2 stop-instances --instance-ids "$NEW_INSTANCE_ID" '>/dev/null'
run aws ec2 wait instance-stopped --instance-ids "$NEW_INSTANCE_ID"

# Critical: enable nested virtualization on the new instance. Without
# this, the Android emulator's KVM path fails with "x86_64 emulation
# currently requires hardware acceleration!" and the runner script
# exits before adb sees the emulator (runner-log shows this exact
# error message). The launch template carries the instance type
# (m8i.xlarge) but NOT the cpu-options — those are an instance-level
# attribute that has to be set explicitly per-instance after launch.
# The attribute can only be modified on a stopped instance. Idempotent:
# re-running on an already-enabled instance is a no-op.
# Caught in vivo on the first rebake.sh roll (2026-05-12).
note "Step 9b: enable nested virtualization on the new instance"
run aws ec2 modify-instance-cpu-options \
  --instance-id "$NEW_INSTANCE_ID" \
  --nested-virtualization enabled \
  '>/dev/null'

note "Step 9c: re-apply standard tags"
run aws ec2 create-tags --resources "$NEW_INSTANCE_ID" --tags \
  'Key=Name,Value=ace-mobile-emulator' \
  'Key=managed-by,Value=script' \
  'Key=env,Value=labs' \
  'Key=owner,Value=ace-web-mobile-poc' \
  'Key=auto-stop,Value=true'

# ───────────────────────────────────────────────────────────────────────
# Step 10: rewrite task-def.
# ───────────────────────────────────────────────────────────────────────
note "Step 10: update $TASK_DEF_REL with new instance id + AMI version"
if [[ -n "$DRY_RUN" ]]; then
  echo "  [dry-run] jq inplace edits → $TASK_DEF"
else
  tmp="$(mktemp)"
  jq --arg id "$NEW_INSTANCE_ID" --arg ver "$AMI_VERSION" '
    .containerDefinitions[0].environment |= map(
      if .name == "ACE_MOBILE_INSTANCE_ID" then .value = $id
      elif .name == "ACE_MOBILE_AMI_VERSION" then .value = $ver
      else . end
    )
  ' "$TASK_DEF" > "$tmp" && mv "$tmp" "$TASK_DEF"
fi

# ───────────────────────────────────────────────────────────────────────
# Step 11-13: commit + PR + merge + deploy.
# ───────────────────────────────────────────────────────────────────────
BRANCH="deploy/mobile-ami-${AMI_VERSION}"
note "Step 11: commit + push on $BRANCH"
cd "$REPO_ROOT"
run git fetch origin --quiet
run git checkout -B "$BRANCH" origin/main
run git add "$TASK_DEF_REL"
COMMIT_MSG="deploy(mobile): pin task-def to AMI $AMI_VERSION ($NEW_INSTANCE_ID)

Rebake + roll executed by infra/mobile-ami/rebake.sh.

- AMI: $AMI_ID ($AMI_VERSION)
- Launch template: $LT_NAME version $NEW_LT_VER (now default)
- Old instance terminated: $OLD_INSTANCE_ID
- New instance: $NEW_INSTANCE_ID (stopped — ace-web starts on demand)

Co-Authored-By: rebake.sh <noreply@example.com>"
run git commit -m "'$COMMIT_MSG'"
run git push -u origin "$BRANCH"

note "Step 12: open PR + merge"
PR_BODY="Auto-generated by \`infra/mobile-ami/rebake.sh\`.

| | |
|---|---|
| AMI | \`$AMI_ID\` |
| AMI version | \`$AMI_VERSION\` |
| LT version | $NEW_LT_VER (default) |
| Old instance | \`$OLD_INSTANCE_ID\` (terminated) |
| New instance | \`$NEW_INSTANCE_ID\` (stopped) |

After this merges, \`$DEPLOY_WORKFLOW\` is auto-triggered (no migrations)."
if [[ -n "$DRY_RUN" ]]; then
  echo "  [dry-run] gh pr create + gh pr merge --merge"
else
  gh pr create --title "deploy(mobile): pin task-def to AMI $AMI_VERSION ($NEW_INSTANCE_ID)" --body "$PR_BODY"
  sleep 2
  gh pr merge "$BRANCH" --merge
fi

note "Step 13: trigger ace-web deploy"
run gh workflow run "$DEPLOY_WORKFLOW" -f run_migrations=false

# ───────────────────────────────────────────────────────────────────────
# Done.
# ───────────────────────────────────────────────────────────────────────
echo
echo "✓ Rebake + roll complete."
echo "    AMI:       $AMI_ID ($AMI_VERSION)"
echo "    LT ver:    $NEW_LT_VER"
echo "    Instance:  $NEW_INSTANCE_ID (stopped)"
echo "    Deploy:    https://github.com/jjackson/ace-web/actions/workflows/$DEPLOY_WORKFLOW"
echo
echo "Next:"
echo "  • Watch the deploy: gh run watch"
echo "  • Once green, smoke-test:"
echo "      curl -sH 'Authorization: Bearer <ACE_E2E_AUTH_TOKEN>' \\"
echo "           https://labs.connect.dimagi.com/ace/api/mobile/status | jq"
echo "    Expect ami_version=$AMI_VERSION."
