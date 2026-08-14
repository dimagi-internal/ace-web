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
#       committed deploy/aws/ace-web.cfn.yaml — that's the source of
#       truth on which instance ace-web believes it owns).
#   6.  Launch a fresh instance from the launch template into the same
#       subnet, wait until it's `running`, then stop it (ace-web starts
#       it on demand via /api/mobile/ensure-running).
#   7.  Re-apply the standard tags so the new instance matches the old.
#   8.  Rewrite deploy/aws/ace-web.cfn.yaml with the new
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

# The CloudFormation template (relative to repo root). The script rewrites the
# ACE_MOBILE_* env values in it — this is the source of truth for which instance
# is in service.
#
# This used to point at deploy/aws/task-definition.json. That file stopped
# feeding the service when ace-web came under CloudFormation: the deploy runs
# `aws cloudformation deploy --template-file deploy/aws/ace-web.cfn.yaml`, and
# CFN is the only writer of the task definition. So a rebake would have written
# the new instance id into a file nothing reads, merged it, deployed green — and
# left the app pointed at the instance this script had just TERMINATED. Worse
# than a no-op, and invisible until mobile broke.
CFN_TEMPLATE_REL="deploy/aws/ace-web.cfn.yaml"

# Working dir is this script's dir (infra/mobile-ami). Packer is invoked
# from here; repo root is two levels up for git/gh operations.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CFN_TEMPLATE="$REPO_ROOT/$CFN_TEMPLATE_REL"

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
# Read from the CFN template — the same file step 10 rewrites, so "which instance
# do we terminate" and "which instance do we install" can never disagree.
OLD_INSTANCE_ID="$(awk '
  /^[[:space:]]*-[[:space:]]+Name:[[:space:]]*ACE_MOBILE_INSTANCE_ID[[:space:]]*$/ { want=1; next }
  want && /^[[:space:]]*Value:/ { gsub(/^[[:space:]]*Value:[[:space:]]*"?|"?[[:space:]]*$/, ""); print; exit }
' "$CFN_TEMPLATE")"
[[ "$OLD_INSTANCE_ID" =~ ^i-[0-9a-f]+$ ]] || \
  fail "couldn't read ACE_MOBILE_INSTANCE_ID from $CFN_TEMPLATE (got: $OLD_INSTANCE_ID)"
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
note "Step 10: update $CFN_TEMPLATE_REL with new instance id + AMI version"
if [[ -n "$DRY_RUN" ]]; then
  echo "  [dry-run] rewrite ACE_MOBILE_INSTANCE_ID=$NEW_INSTANCE_ID, ACE_MOBILE_AMI_VERSION=$AMI_VERSION → $CFN_TEMPLATE"
else
  # A targeted rewrite of the `Value:` line that follows each `- Name: <KEY>`,
  # rather than a YAML round-trip: re-emitting this template with a YAML dumper
  # would reflow every block and mangle the `!Ref`/`!Sub` short tags CFN needs.
  python3 - "$CFN_TEMPLATE" "$NEW_INSTANCE_ID" "$AMI_VERSION" <<'PY'
import re, sys

path, instance_id, ami_version = sys.argv[1], sys.argv[2], sys.argv[3]
wanted = {"ACE_MOBILE_INSTANCE_ID": instance_id, "ACE_MOBILE_AMI_VERSION": ami_version}

lines = open(path).readlines()
pending = None
seen = set()
for i, line in enumerate(lines):
    if pending is not None:
        m = re.match(r'^(\s*)Value:\s*.*$', line)
        if not m:
            sys.exit(f"{path}: expected a Value: line after `- Name: {pending}`, got: {line.strip()!r}")
        lines[i] = f'{m.group(1)}Value: "{wanted[pending]}"\n'
        seen.add(pending)
        pending = None
        continue
    m = re.match(r'^\s*-\s+Name:\s*([A-Z0-9_]+)\s*$', line)
    if m and m.group(1) in wanted:
        pending = m.group(1)

missing = set(wanted) - seen
if missing:
    # Loud, not silent: the whole point of this step is that the running service
    # learns the new instance id. Half-applying it is how mobile ends up pointed
    # at a terminated box.
    sys.exit(f"{path}: never found env entries for {sorted(missing)} — refusing to continue")

open(path, "w").writelines(lines)
print(f"  rewrote ACE_MOBILE_INSTANCE_ID + ACE_MOBILE_AMI_VERSION in {path}")
PY
fi

# ───────────────────────────────────────────────────────────────────────
# Step 11-13: commit + PR + merge + deploy.
# ───────────────────────────────────────────────────────────────────────
BRANCH="deploy/mobile-ami-${AMI_VERSION}"
note "Step 11: commit + push on $BRANCH"
cd "$REPO_ROOT"
run git fetch origin --quiet
run git checkout -B "$BRANCH" origin/main
run git add "$CFN_TEMPLATE_REL"
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
echo "    Deploy:    https://github.com/dimagi-internal/ace-web/actions/workflows/$DEPLOY_WORKFLOW"
echo
echo "Next:"
echo "  • Watch the deploy: gh run watch"
echo "  • Once green, smoke-test:"
echo "      curl -sH \"Authorization: Bearer \$ACE_WEB_PAT_TOKEN\" \\"
echo "           https://labs.connect.dimagi.com/ace/api/mobile/status | jq"
echo "    Expect ami_version=$AMI_VERSION."
