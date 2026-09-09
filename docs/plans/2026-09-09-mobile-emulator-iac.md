# Mobile Emulator: Back Under IaC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the ACE mobile emulator's AWS resources back under version-controlled infrastructure-as-code, and prove the emulator still boots and runs a Maestro flow after three months stopped.

**Architecture:** The emulator's Terraform has no backend and no state file anywhere, so its config is orphaned from the resources it describes. Rather than reconstruct that state, the resources are adopted into a CloudFormation stack via resource import — matching the estate's stated tooling — and the Terraform is deleted. The instance is treated as disposable because its AMI is self-contained.

**Tech Stack:** AWS CloudFormation (resource import), EC2, S3, IAM, CloudWatch, SSM Session Manager, Maestro.

**Spec:** `canopy-web` repo, `docs/superpowers/specs/2026-09-09-labs-infrastructure-as-code-design.md` — the "Mobile emulator: Terraform → CloudFormation" section.

## Global Constraints

- **Every AWS-mutating step is gated.** Jonathan asked to be consulted before anything is deployed, and to do it off-hours. Steps marked **GATE** stop and ask; they do not proceed on the executor's judgment.
- **The instance is disposable; the bucket is not.** `ace-mobile-artifacts-labs` holds captured test artifacts. It must never be deleted or replaced — `DeletionPolicy: Retain` on it from the first template.
- **Import changes nothing.** A CloudFormation import adopts existing resources without modifying them. Any import whose change set proposes a modification is wrong and must be stopped and re-read, not executed.
- Region `us-east-1`, account `858923557655`, AWS profile `labs`.

## What is actually true today (measured 2026-09-09)

| Resource | Identifier | State |
| --- | --- | --- |
| EC2 instance | `i-0c447ed51374a4871` | **stopped** since 2026-06-12, `m8i.xlarge` |
| AMI | `ami-057bc47bcbe68e69e` | `ace-mobile-emulator-2026-05-25-1857`, owned by this account |
| Security group | `sg-05bc2fc8316a5e16e` | egress-only, no ingress (SSM access only) |
| Instance profile | `ace-mobile-instance-profile-labs` | |
| IAM role | `ace-mobile-instance-role-labs` | 2 inline policies (`…-s3-labs`, `…-secrets-labs`) |
| S3 bucket | `ace-mobile-artifacts-labs` | tagged `managed-by: terraform` |
| CloudWatch alarm | idle-stop | |
| Launch template | `ace-mobile-emulator-labs` | |

**None of these is owned by any CloudFormation stack, and no Terraform state file exists on
this machine or in any backend** — `infra/mobile/main.tf` declares no `backend` block, and
`.gitignore` says outright: *"state stays local until promoted."* `terraform apply` today
would try to create duplicates and collide on the bucket and role names.

**The instance holds no unique state.** The AMI's own description is
*"Android 34 / Pixel 7 AVD, Maestro 1.39.x, CommCare 2.63.0 default + 2.62.0 fallback,
registered demo user snapshot"*, its root volume was created the same minute as the AMI, and
`ec2.tf`'s `null_resource.stop_on_create` stops the instance immediately after launch. So
everything the emulator needs is baked into the image, and the running instance is a
disposable instantiation of it. That is what makes this low-risk.

## File Structure

| File | Responsibility |
| --- | --- |
| `deploy/aws/ace-mobile.cfn.yaml` (new) | The whole emulator stack, matching `deploy/aws/ace-web.cfn.yaml`'s conventions. |
| `deploy/aws/ace-mobile-bootstrap.sh` (new) | The two one-shot post-create steps Terraform modelled as `null_resource` — stop-on-create and nested virtualisation. They are bootstrap actions, not desired state. |
| `deploy/aws/README-mobile.md` (new) | How to import, apply, boot, test, and stop. Replaces `infra/mobile/README.md`. |
| `infra/mobile/**` (deleted, last task) | Removed only after the stack owns the resources. |

---

### Task 1: Write the stack template, and prove it describes what already exists

**Files:**
- Create: `deploy/aws/ace-mobile.cfn.yaml`

**Interfaces:**
- Consumes: nothing
- Produces: a template whose logical IDs are referenced by every later task —
  `Instance`, `SecurityGroup`, `LaunchTemplate`, `InstanceRole`, `InstanceProfile`,
  `ArtifactsBucket`, `IdleStopAlarm`

- [ ] **Step 1: Read the Terraform being replaced**

Read all of `infra/mobile/*.tf`. Every resource, property and tag in the CloudFormation
template must correspond to something there or to a measured fact from the table above.
Carry the comments across — they explain why the security group has no ingress and why the
launch template exists alongside a single instance.

- [ ] **Step 2: Write the template**

Follow `deploy/aws/ace-web.cfn.yaml` for house style: a `Parameters` block for the things
that vary (`AmiId`, `InstanceType`, `VpcId`, `SubnetId`, `EnvSuffix`), `Description` comments
that say why rather than what.

Requirements that are not negotiable:

- `ArtifactsBucket` carries `DeletionPolicy: Retain` **and** `UpdateReplacePolicy: Retain`.
  It holds captured test artifacts; losing it is the one unrecoverable outcome here.
- `SecurityGroup` has **no ingress rules at all**. Access is via SSM Session Manager. This is
  a deliberate property of the design, not an omission.
- `InstanceRole` keeps both inline policies (`ace-mobile-instance-s3-labs`,
  `ace-mobile-instance-secrets-labs`) and the SSM managed policy attachment, with the same
  permissions the Terraform grants — read `iam.tf` for the exact statements rather than
  inventing them.
- Resource names match the existing physical resources exactly. Import matches on physical
  ID, but a later update would rename anything that disagrees.

- [ ] **Step 3: Validate the template against CloudFormation**

```bash
export AWS_PROFILE=labs AWS_DEFAULT_REGION=us-east-1
aws cloudformation validate-template \
  --template-body file://deploy/aws/ace-mobile.cfn.yaml
```

Expected: no error, and the `Parameters` list matches what the template declares.
This call is read-only.

- [ ] **Step 4: Commit**

```bash
git add deploy/aws/ace-mobile.cfn.yaml
git commit -m "mobile: describe the emulator's resources as a CloudFormation stack"
```

---

### Task 2: Import the existing resources — read the change set before executing it

**Files:**
- Create: `deploy/aws/README-mobile.md`

**Interfaces:**
- Consumes: `deploy/aws/ace-mobile.cfn.yaml` from Task 1
- Produces: a CloudFormation stack named `ace-mobile` owning the resources

- [ ] **Step 1: Build the import change set — this executes nothing**

An import change set is a proposal. Creating one modifies no resource.

```bash
export AWS_PROFILE=labs AWS_DEFAULT_REGION=us-east-1
cat > /tmp/import-resources.json <<'JSON'
[
  {"ResourceType":"AWS::S3::Bucket","LogicalResourceId":"ArtifactsBucket",
   "ResourceIdentifier":{"BucketName":"ace-mobile-artifacts-labs"}},
  {"ResourceType":"AWS::IAM::Role","LogicalResourceId":"InstanceRole",
   "ResourceIdentifier":{"RoleName":"ace-mobile-instance-role-labs"}},
  {"ResourceType":"AWS::IAM::InstanceProfile","LogicalResourceId":"InstanceProfile",
   "ResourceIdentifier":{"InstanceProfileName":"ace-mobile-instance-profile-labs"}},
  {"ResourceType":"AWS::EC2::SecurityGroup","LogicalResourceId":"SecurityGroup",
   "ResourceIdentifier":{"GroupId":"sg-05bc2fc8316a5e16e"}},
  {"ResourceType":"AWS::EC2::Instance","LogicalResourceId":"Instance",
   "ResourceIdentifier":{"InstanceId":"i-0c447ed51374a4871"}}
]
JSON

aws cloudformation create-change-set \
  --stack-name ace-mobile \
  --change-set-name import-mobile \
  --change-set-type IMPORT \
  --template-body file://deploy/aws/ace-mobile.cfn.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --resources-to-import file:///tmp/import-resources.json
```

If CloudFormation rejects a resource type as not importable, drop that resource from BOTH
the import list and the template, note it in the README as still unmanaged, and continue
with the rest. Do not invent a workaround.

- [ ] **Step 2: READ the change set. This is the gate that makes import safe.**

```bash
aws cloudformation describe-change-set \
  --stack-name ace-mobile --change-set-name import-mobile \
  --query 'Changes[].ResourceChange.{Action:Action,Id:LogicalResourceId,Type:ResourceType,Replacement:Replacement}' \
  --output table
```

Expected: **every row's `Action` is `Import`.** Nothing else is acceptable.

A `Modify` means the template disagrees with the live resource and CloudFormation would
change it — fix the template to match reality and rebuild the change set. A `Replacement` of
`True` means it would destroy and recreate the resource, which for the bucket would be
unrecoverable.

- [ ] **Step 3: GATE — stop and ask before executing**

Show Jonathan the table from Step 2 and ask for explicit approval to run
`execute-change-set`. Do not proceed without it. He asked to be consulted before anything is
applied, and to do it off-hours.

- [ ] **Step 4: On approval, execute and verify nothing changed**

```bash
aws cloudformation execute-change-set --stack-name ace-mobile --change-set-name import-mobile
aws cloudformation wait stack-import-complete --stack-name ace-mobile

# The resources must be untouched by the import.
aws ec2 describe-instances --instance-ids i-0c447ed51374a4871 \
  --query 'Reservations[0].Instances[0].State.Name' --output text     # still "stopped"
aws s3api head-bucket --bucket ace-mobile-artifacts-labs && echo "bucket intact"

# And the stack must now be IN_SYNC with its template.
ID=$(aws cloudformation detect-stack-drift --stack-name ace-mobile \
       --query StackDriftDetectionId --output text)
sleep 20
aws cloudformation describe-stack-drift-detection-status --stack-drift-detection-id "$ID" \
  --query '{Detection:DetectionStatus,Drift:StackDriftStatus}' --output json
```

Expected: instance still `stopped`, bucket intact, drift `IN_SYNC`. A `DRIFTED` result here
means the template does not describe what was imported — record exactly which properties
differ before doing anything else.

- [ ] **Step 5: Write the README and commit**

`deploy/aws/README-mobile.md` covers: what the stack owns, how to boot and stop the
emulator, how to reach it over SSM, and the standing note that the instance is disposable
because the AMI is self-contained. Carry over anything still true from
`infra/mobile/README.md`.

```bash
git add deploy/aws/README-mobile.md
git commit -m "mobile: document the emulator stack, and why the instance is disposable"
```

---

### Task 3: Prove the emulator still works

Three months stopped, never tested since. "It imported" is not "it works".

**Files:**
- Create: `deploy/aws/ace-mobile-bootstrap.sh`

- [ ] **Step 1: GATE — ask before starting the instance**

Starting an `m8i.xlarge` costs real money per hour. Ask Jonathan before starting it, and
confirm who stops it. The idle-stop CloudWatch alarm exists but must not be relied on as the
only brake for a manual test.

- [ ] **Step 2: Start it and wait for SSM**

```bash
aws ec2 start-instances --instance-ids i-0c447ed51374a4871
aws ec2 wait instance-running --instance-ids i-0c447ed51374a4871

# SSM registration lags the instance being "running"; poll rather than assume.
for _ in $(seq 1 30); do
  ONLINE=$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=i-0c447ed51374a4871" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo None)
  [ "$ONLINE" = "Online" ] && break
  sleep 10
done
echo "SSM: $ONLINE"
```

If SSM never comes Online, stop the instance and report. Without SSM there is no way in —
the security group has no ingress by design.

- [ ] **Step 3: Check the emulator tooling actually survived**

Over SSM, confirm the pieces the AMI description promises are present and runnable:

```bash
aws ssm send-command --instance-ids i-0c447ed51374a4871 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["adb version","maestro --version","emulator -list-avds","ls -la /opt/commcare* 2>/dev/null || true"]' \
  --query 'Command.CommandId' --output text
```

Retrieve with `aws ssm get-command-invocation`. Record the actual versions found against what
the AMI description claims (Android 34 / Pixel 7 AVD, Maestro 1.39.x, CommCare 2.63.0 +
2.62.0). Differences are findings, not something to smooth over.

- [ ] **Step 4: Boot the AVD and run one real Maestro flow**

Use an existing recipe from the repo rather than writing a new one — search
`ace-web` for Maestro flows (`*.yaml` under a `maestro`/`recipes` path) and pick the
simplest that exercises app launch. Capture the exit status and any screenshots it produces.

**This is the deliverable of the whole task.** A passing `adb version` proves nothing about
whether the emulator still runs a test.

- [ ] **Step 5: Stop the instance**

```bash
aws ec2 stop-instances --instance-ids i-0c447ed51374a4871
```

Do this even if the test failed. Confirm it reaches `stopped`.

- [ ] **Step 6: Write the bootstrap script and commit**

`deploy/aws/ace-mobile-bootstrap.sh` holds the two one-shot steps Terraform modelled as
`null_resource`: stop-on-create, and enabling nested virtualisation. Read `ec2.tf` for what
they actually do. Head the script with a comment explaining that these are one-time bootstrap
actions rather than desired state, which is why they are a script beside the stack rather
than resources inside it.

```bash
git add deploy/aws/ace-mobile-bootstrap.sh
git commit -m "mobile: the two one-shot bootstrap steps, as a script rather than a null_resource"
```

---

### Task 4: Delete the Terraform

Only after the stack owns the resources and the emulator has been proven to work.

- [ ] **Step 1: Confirm the stack owns everything the Terraform declared**

```bash
aws cloudformation list-stack-resources --stack-name ace-mobile \
  --query 'StackResourceSummaries[].{Id:LogicalResourceId,Type:ResourceType}' --output table
```

Compare against the resource list in `infra/mobile/*.tf`. Anything the stack does not own
must be recorded in `deploy/aws/README-mobile.md` as still unmanaged — do not delete the
Terraform that describes it without saying so.

- [ ] **Step 2: Delete `infra/mobile/` and commit**

```bash
git rm -r infra/mobile
git commit -m "mobile: remove the Terraform, now that CloudFormation owns the resources

Its state had been lost — no backend was ever configured (.gitignore said 'state stays local
until promoted') so the config described resources it could no longer touch, and a
terraform apply would have tried to create duplicates and collided on the bucket and role
names. The resources are now in the ace-mobile CloudFormation stack, which keeps its state
in AWS where there is nothing to lose."
```

---

## Self-Review

**Spec coverage.** The spec's mobile-emulator section asks for three things: convert the
Terraform to CloudFormation (Tasks 1, 2, 4), move the two `null_resource` provisioners to a
documented bootstrap script (Task 3 Step 6), and end with the instance booted and a Maestro
flow actually run (Task 3 Step 4). All present.

**Placeholders.** None — every step carries its command. Task 1 Step 2 deliberately says
"read `iam.tf` for the exact statements" rather than inventing IAM policy, because guessing
at a policy is worse than reading the one that exists.

**The risk I am most likely to have got wrong.** Whether CloudFormation supports importing
every one of these resource types. Partially checked since writing this: `describe-type
--type RESOURCE` returns a CloudFormation Registry entry for all seven
(`AWS::EC2::Instance`, `::SecurityGroup`, `::LaunchTemplate`, `AWS::IAM::Role`,
`::InstanceProfile`, `AWS::S3::Bucket`, `AWS::CloudWatch::Alarm`), each `FULLY_MUTABLE`.
Registry-backed resources implement the read handler that import requires, so that is a
strong signal — but it is a signal, not proof, and there is no API that answers
"is this importable" directly.

Task 2 Step 1 therefore still handles it the honest way: attempt the import, and if a type is
rejected, drop it and record it as unmanaged rather than working around it. The import change
set is inspectable before execution, so the cost of being wrong is a rejected change set, not
a damaged resource.

**What this plan does NOT do.** It does not rebuild the AMI, upgrade Android/Maestro/CommCare
versions, or change the instance type. If Task 3 finds the tooling has rotted, that is a
finding to report, and its own piece of work.
