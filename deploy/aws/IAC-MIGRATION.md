# Bringing ace-web under CloudFormation

Status: **template written, import DRY RUN PASSED, not executed.**

ace-web predates any IaC — `one-time-setup.sh` created the service, target group,
listener rule and log group by hand, so they exist only as live AWS state. This
migrates them into a stack **without recreating them**, using CloudFormation
resource import.

## Why import rather than "just apply a template"

canopy-web could be managed by CloudFormation because CFN *created* its resources.
Here they already exist, so a plain `cloudformation deploy` would try to CREATE
duplicates and fail on name conflicts. Import adopts them in place.

The hazard is that the template must describe each resource **exactly** as it is.
A mismatch either fails the import or makes CloudFormation decide a resource needs
REPLACING — replacing the ECS service is downtime; replacing the target group
leaves the listener rule pointing at nothing.

## The dry run (this is the safety net — always run it first)

An import change set can be created and inspected **without executing**. It
validates the template against live reality and reports exactly what it would do,
mutating nothing.

```bash
aws cloudformation create-change-set --profile labs \
  --stack-name ace-web --change-set-name dryrun-import --change-set-type IMPORT \
  --template-body file://deploy/aws/ace-web.cfn.yaml \
  --resources-to-import file://deploy/aws/import-resources.json \
  --capabilities CAPABILITY_IAM

aws cloudformation wait change-set-create-complete --profile labs \
  --stack-name ace-web --change-set-name dryrun-import

aws cloudformation describe-change-set --profile labs \
  --stack-name ace-web --change-set-name dryrun-import \
  --query "Changes[].ResourceChange.{Action:Action,Resource:LogicalResourceId,Replacement:Replacement}" \
  --output table
```

**Pass condition — every row must read `Import` / `None`:**

```
Import  None  ListenerRule
Import  None  LogGroup
Import  None  Service
Import  None  TargetGroup
```

Anything showing `Replacement: True`, or any Action that is not `Import`, means
the template disagrees with reality. **Do not execute.** Fix the template to match
the live resource and re-run the dry run.

Result on 2026-07-26: all four `Import` / `None`. ace-web stayed up throughout
(HTTP 200, 2/2 tasks) — creating a change set touches nothing.

## Gotchas already found (each cost a round trip)

* `Description` must be **under 1024 characters**. Longer prose goes in comments.
* The ListenerRule identifier key is **`RuleArn`**, not `ListenerRuleArn`.
* An import change set **cannot add `Outputs`**. They go in with phase 2.
* Creating the change set leaves the stack in `REVIEW_IN_PROGRESS` — a shell
  holding no resources. Deleting the change set and then the stack is a clean
  no-op abort.

## Phase 2 (after the import lands)

1. Add a `TaskDefinition` resource (2 containers, 13 secrets — transcribe from
   the live definition) and repoint `Service.TaskDefinition` at `!Ref` it,
   replacing the `CurrentTaskDefinitionArn` parameter.
2. Add the `Outputs` block.
3. Grant the CI role CloudFormation permissions **scoped to this stack**, exactly
   as canopy-web needed:
   `arn:aws:cloudformation:us-east-1:858923557655:stack/ace-web/*`.
   Note `github-actions-labs-deploy` is shared across five repos, so scope it.
4. Switch the deploy workflow from `register-task-definition` + `update-service`
   to `cloudformation deploy --parameter-overrides ImageTag=<sha>`, keeping a
   throwaway task def for the migration step (see canopy-web's workflow — CFN's
   Service and TaskDefinition update atomically, leaving no seam to migrate in).

## Not imported, on purpose

The 13 secrets and 2 ECR repos. They are stable and adopting them adds 15
resources' worth of exact-match risk for no deploy benefit. They are referenced
by ARN and can be imported later if wanted.
