# ace-web: Bootstrap/App Stack Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it structurally impossible for an ace-web deploy to fail because CI cannot write a resource in its own stack, by splitting the stack into a bootstrap stack an admin applies and an app stack CI deploys.

**Architecture:** `AWS::CloudFormation::StackRefactor` moves the resources CI cannot write out of the CI-deployed stack and into a new admin-applied one. The app stack is left owning only the task definition and the service — the two things the CI role can actually write. Nothing is deleted or recreated; a refactor moves ownership, not resources.

**Tech Stack:** AWS CloudFormation (stack refactor, resource import), ECS, ELBv2, ECR, Secrets Manager, IAM.

**Spec:** `canopy-web` repo, `docs/superpowers/specs/2026-09-09-labs-infrastructure-as-code-design.md`

## Global Constraints

- **Every AWS-mutating step is gated.** Jonathan asked to be consulted before anything is applied, and to do it off-hours. Steps marked **GATE** stop and ask.
- **This is the pilot for `create-stack-refactor`.** canopy-web's split (which moves 7 live secrets) follows it deliberately, so the mechanism gets exercised here first, where no secret is involved.
- **A refactor must move, never modify.** Any refactor whose actions include a create, delete or replace of a live resource is wrong — stop and re-read rather than executing.
- Region `us-east-1`, account `858923557655`, AWS profile `labs`.

## What is actually true today (measured 2026-09-09)

The `ace-web` stack contains 5 resources. The CI role can write 3 of them:

| Resource | CI can write? | Notes |
| --- | --- | --- |
| `AWS::ECS::TaskDefinition` | yes | `ecs:RegisterTaskDefinition` |
| `AWS::ECS::Service` | yes | `ecs:UpdateService` |
| `AWS::ElasticLoadBalancingV2::TargetGroup` | yes | **only because of a hand-edit on 2026-09-09** — see below |
| `AWS::Logs::LogGroup` | **no** | `logs:PutRetentionPolicy` implicitDeny |
| `AWS::ElasticLoadBalancingV2::ListenerRule` | **no** | `elasticloadbalancing:ModifyRule` implicitDeny |

Also unmanaged by any stack: ECR repositories `labs-jj-ace-web` and `labs-jj-ace-web-frontend`, and 15 secrets matching `ace-web`/`ace-mobile`.

**About the target group.** On 2026-09-09, `elasticloadbalancing:ModifyTargetGroup` was added
by hand to `GitHubActionsLabsDeployPolicy` to unblock a canopy-web deploy. That statement's
Resource list already contained ace-web's target group ARN, so ace-web gained the permission
as a side effect, without anyone asking for it. It is benign — it fixes the same latent bug
here — but it is an accident, not a decision. This plan makes it a decision: the target group
moves to the bootstrap stack, and the bootstrap stack claims the grant explicitly.

## File Structure

| File | Responsibility |
| --- | --- |
| `deploy/aws/ace-web-bootstrap.cfn.yaml` (new) | Admin-applied. Owns what CI cannot write: log group, target group, listener rule, ECR repositories, and the deploy-role IAM grants ace-web needs. |
| `deploy/aws/ace-web.cfn.yaml` (modified) | CI-deployed. Reduced to the task definition and the service; takes the target group ARN and log group name as parameters. |
| `.github/workflows/deploy-ace-web-labs.yml` (modified) | Passes the two new parameters, read from the bootstrap stack's outputs. |
| `deploy/aws/README-bootstrap.md` (new) | How to apply the bootstrap stack, why it needs admin credentials, and what belongs in which stack. |

---

### Task 1: Write the bootstrap template, describing what already exists

**Files:**
- Create: `deploy/aws/ace-web-bootstrap.cfn.yaml`

**Interfaces:**
- Produces: logical IDs `LogGroup`, `TargetGroup`, `ListenerRule`, `EcrRepo`, `EcrRepoFrontend`, `DeployRoleElbPolicy`, `DeployRoleLogsPolicy`; and stack outputs `TargetGroupArn`, `LogGroupName`

- [ ] **Step 1: Read what is being moved**

Read `deploy/aws/ace-web.cfn.yaml`. The `LogGroup`, `TargetGroup` and `ListenerRule`
definitions move to the new template **byte-for-byte** — including every property, comment
and tag. A refactor compares before and after; a property you "tidy" on the way across
becomes a modification the refactor will refuse or, worse, apply.

- [ ] **Step 2: Write the bootstrap template**

Contains:
- the three moved resources, copied exactly
- `EcrRepo` and `EcrRepoFrontend` for `labs-jj-ace-web` and `labs-jj-ace-web-frontend`,
  written to match the live repositories (read them first:
  `aws ecr describe-repositories --repository-names labs-jj-ace-web labs-jj-ace-web-frontend`)
- `DeployRoleElbPolicy` and `DeployRoleLogsPolicy` as `AWS::IAM::Policy` with
  `Roles: [!Ref DeployRoleName]`, granting exactly what ace-web's own CI deploy needs and
  nothing more. Follow the pattern in connect-labs' `infra/labs-monitoring.yml`
  (`DeployRoleLogReadPolicy`) — a stack owning a slice of a role it does not own.
- `Outputs` for `TargetGroupArn` and `LogGroupName`, which the app stack consumes as
  parameters. **Outputs, not exports:** an exported value cannot be deleted while imported,
  which would couple the two stacks' update cycles. The workflow reads the outputs and passes
  them as parameters instead.

Secrets are deliberately NOT in this template. ace-web has 15 of them and moving live
secrets is the riskiest part of this work; it gets its own task after the mechanism is
proven here.

- [ ] **Step 3: Validate (read-only)**

```bash
export AWS_PROFILE=labs AWS_DEFAULT_REGION=us-east-1
aws cloudformation validate-template --template-body file://deploy/aws/ace-web-bootstrap.cfn.yaml
```

- [ ] **Step 4: Commit**

```bash
git add deploy/aws/ace-web-bootstrap.cfn.yaml
git commit -m "ace-web: a bootstrap stack for the resources CI cannot write"
```

---

### Task 2: Reduce the app template to what CI can actually write

**Files:**
- Modify: `deploy/aws/ace-web.cfn.yaml`

- [ ] **Step 1: Remove the three moved resources and add parameters**

Delete `LogGroup`, `TargetGroup` and `ListenerRule`. Add parameters `TargetGroupArn` and
`LogGroupName`. Repoint `Service`'s load balancer config at `!Ref TargetGroupArn` and the
task definition's `awslogs-group` at `!Ref LogGroupName`.

The stack must end up containing exactly `TaskDefinition` and `Service`, and a comment at the
top should say why: those are the only two resources the CI role can write, and keeping the
stack to them is what makes a permissions failure structurally impossible rather than
caught by a check.

- [ ] **Step 2: Validate (read-only)**

```bash
aws cloudformation validate-template --template-body file://deploy/aws/ace-web.cfn.yaml
```

- [ ] **Step 3: Commit**

```bash
git add deploy/aws/ace-web.cfn.yaml
git commit -m "ace-web: the CI stack holds only what CI can write"
```

---

### Task 3: Refactor — read the actions before executing them

- [ ] **Step 1: Create the refactor. This executes nothing.**

```bash
export AWS_PROFILE=labs AWS_DEFAULT_REGION=us-east-1
aws cloudformation create-stack-refactor \
  --stack-definitions \
    StackName=ace-web,TemplateBody="$(cat deploy/aws/ace-web.cfn.yaml)" \
    StackName=ace-web-bootstrap,TemplateBody="$(cat deploy/aws/ace-web-bootstrap.cfn.yaml)" \
  --resource-mappings \
    'Source={StackName=ace-web,LogicalResourceId=LogGroup},Destination={StackName=ace-web-bootstrap,LogicalResourceId=LogGroup}' \
    'Source={StackName=ace-web,LogicalResourceId=TargetGroup},Destination={StackName=ace-web-bootstrap,LogicalResourceId=TargetGroup}' \
    'Source={StackName=ace-web,LogicalResourceId=ListenerRule},Destination={StackName=ace-web-bootstrap,LogicalResourceId=ListenerRule}'
```

If the CLI rejects this shape, read `aws cloudformation create-stack-refactor help` and follow
what it actually wants rather than guessing. Record the working invocation in the README.

- [ ] **Step 2: READ the actions. This is the gate that makes the refactor safe.**

```bash
aws cloudformation list-stack-refactor-actions --stack-refactor-id <id> --output table
aws cloudformation describe-stack-refactor --stack-refactor-id <id>
```

Expected: every action is a MOVE. **Any CREATE, DELETE or REPLACE of a live resource means
stop** — the templates disagree with what exists, and the fix is to make the templates match,
not to execute anyway.

- [ ] **Step 3: GATE — show Jonathan the action list and ask**

Do not execute without explicit approval. Off-hours.

- [ ] **Step 4: On approval, execute and verify nothing moved but ownership**

```bash
aws cloudformation execute-stack-refactor --stack-refactor-id <id>

# The live resources must be untouched.
aws elbv2 describe-target-groups --names labs-jj-ace-web-tg \
  --query 'TargetGroups[0].{Arn:TargetGroupArn,HC:HealthCheckIntervalSeconds}' --output json
aws ecs describe-services --cluster labs-jj-cluster --services labs-jj-ace-web \
  --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}' --output json
curl -s -o /dev/null -w "ace-web live: %{http_code}\n" https://labs.connect.dimagi.com/ace/

# Both stacks must be IN_SYNC with their templates.
for S in ace-web ace-web-bootstrap; do
  ID=$(aws cloudformation detect-stack-drift --stack-name $S --query StackDriftDetectionId --output text)
  sleep 20
  aws cloudformation describe-stack-drift-detection-status --stack-drift-detection-id "$ID" \
    --query "{Stack:'$S',Drift:StackDriftStatus}" --output json
done
```

The target group ARN must be unchanged — a changed ARN means it was recreated, which would
have dropped the service's registration and taken ace-web down.

---

### Task 4: Point the deploy workflow at the new parameters

**Files:**
- Modify: `.github/workflows/deploy-ace-web-labs.yml`

- [ ] **Step 1: Read the bootstrap outputs and pass them through**

Before the `cloudformation deploy` call, read the two outputs and pass them as
`--parameter-overrides` alongside the existing image tag:

```bash
TG_ARN=$(aws cloudformation describe-stacks --stack-name ace-web-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='TargetGroupArn'].OutputValue|[0]" --output text)
LOG_GROUP=$(aws cloudformation describe-stacks --stack-name ace-web-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='LogGroupName'].OutputValue|[0]" --output text)
```

Guard both reads the way canopy-web's deploy step guards its own (`if VAR=$(...); then ... else ::error::; exit 1; fi`) — under GitHub Actions' default `bash -e`, a bare `VAR=$(cmd)` on a failing command aborts the step before any diagnostic can be printed.

- [ ] **Step 2: GATE — this changes how ace-web deploys**

It takes effect on the next ace-web deploy. Ask before merging.

- [ ] **Step 3: Verify the workflow parses**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-ace-web-labs.yml')); print('YAML valid')"
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy-ace-web-labs.yml
git commit -m "ace-web: the deploy reads its target group and log group from the bootstrap stack"
```

---

### Task 5: The secrets, and the README

Deliberately last, and deliberately after the refactor mechanism has been proven on three
resources that carry no credentials.

- [ ] **Step 1: Decide whether the secrets move at all**

15 secrets, live, holding real credentials. They almost never change, so leaving them
unmanaged leaves a landmine that is never stepped on. Moving them puts them under version
control at the cost of one risky operation.

Present both options to Jonathan with this plan's evidence and let him choose. Do not decide
it in the executor.

- [ ] **Step 2: If they move — read every value before, and diff after**

```bash
for S in $(aws secretsmanager list-secrets \
    --query 'SecretList[?contains(Name,`ace-web`)].Name' --output text); do
  aws secretsmanager get-secret-value --secret-id "$S" \
    --query SecretString --output text | shasum -a 256 | cut -c1-16 | xargs echo "$S"
done
```

Record the hashes, refactor, re-read, and diff. A changed hash is an incident, not a finding.
Hashes rather than values so nothing sensitive lands in a log.

- [ ] **Step 3: Write `deploy/aws/README-bootstrap.md` and commit**

Covers: what lives in which stack and why; that the bootstrap stack needs admin credentials
and is applied deliberately, off-hours; and the rule that makes the split work —
**a stack's deployer must be able to write every resource in it.**

---

## Self-Review

**Spec coverage.** The spec's bootstrap/app split is Tasks 1-4; `create-stack-refactor` as the
moving mechanism is Task 3; secrets-last sequencing is Task 5. The spec's "verification"
half shipped separately in canopy-web #732.

**Placeholders.** The refactor CLI invocation in Task 3 Step 1 is the one place I am not
certain of the exact argument shape — `create-stack-refactor` is recent and I have not run
it. The step says so and tells the executor to read `help` rather than guess, and Step 2's
action list is inspectable before anything executes, so being wrong costs a rejected command
rather than a damaged resource.

**The risk I am most likely to have got wrong.** That the three moved resources can be copied
byte-for-byte without CloudFormation seeing a modification. `!Ref`/`!Sub` expressions
referencing resources that stay behind in the app stack will not resolve in the new template,
so some may need to become parameters — which is a change, and a refactor may refuse it.
Task 3 Step 2 is where that surfaces, before anything is applied.

**What this plan does NOT do.** It does not touch the shared core (ALB, cluster, RDS, VPC,
the three IAM roles) — that is phase 2 and needs its own spec. It does not remove the
hand-made ELB grant from the shared role; the bootstrap stack claims that grant, and
retiring the hand-made copy is a follow-up once both tenants' bootstrap stacks exist.
