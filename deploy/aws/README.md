# deploy/aws/

ace-web's AWS deployment. **CloudFormation is the source of truth** — the
`ace-web` stack owns the ECS task definition, service, target group, listener
rule and log group, and is their only writer.

## Files

- `ace-web.cfn.yaml` — **the** definition of what runs. Containers, every
  non-secret environment variable, secret ARNs, the service, target group,
  listener rule and log group. Changing anything about the running task means
  changing this file.
- `one-time-setup.sh` — provisions what the stack does *not* own: the two ECR
  repositories and the Secrets Manager entries. Only for standing up a brand-new
  environment; not part of any deploy. See its header for what it assumes.

## Deploy

`.github/workflows/deploy-ace-web-labs.yml`, manual trigger (Actions → Deploy to
Labs (AWS) → Run workflow). It:

1. refuses to run on anything but `main`, and refuses a SHA that is no longer
   main's tip
2. builds and pushes the backend and frontend images, tagged with the commit SHA
3. runs `manage.py migrate` as a one-off Fargate task — new image against the
   current schema, a deliberate seam, since CFN rolls task definition and service
   atomically and leaves nowhere else to migrate
4. `aws cloudformation deploy --template-file deploy/aws/ace-web.cfn.yaml
   --parameter-overrides ImageTag=<sha>` — CFN registers the task definition and
   rolls the service, with a deployment circuit breaker
5. POSTs `/api/w/<ws>/sessions/resume-interrupted` to relaunch ACE opp runs the
   rollout killed

Full runbook, including migrations and rollback: `docs/deploy.md`.

## Changing the running configuration

Environment variables, secrets, CPU/memory, container definitions — all live in
`ace-web.cfn.yaml`, and reach the service on the next deploy. There is no second
place to change them.

Anything that writes a task definition elsewhere is stale. A JSON task
definition in this directory used to be the source of truth, and after the
CloudFormation migration it lingered long enough for two separate changes to be
written into a file nothing reads: a flag flip that deployed green and did
nothing, and an AMI roll that would have left the app pointed at a terminated
EC2 instance. It is gone.

Secrets are referenced by ARN, so rotating a secret's *value* needs no deploy.
Adding one means creating it in Secrets Manager and then referencing it here.

## Verifying a deploy did what you think

A green workflow only proves CFN converged on the template. To confirm a
specific value actually reached the running service:

```bash
TD=$(aws ecs describe-services --cluster labs-jj-cluster \
       --services labs-jj-ace-web --region us-east-1 \
       --query "services[0].taskDefinition" --output text)
aws ecs describe-task-definition --task-definition "$TD" --region us-east-1 \
  --query "taskDefinition.containerDefinitions[?name=='api'].environment" \
  --output json | grep -A1 YOUR_VAR
```

To confirm the stack still matches reality (`IN_SYNC` is the pass):

```bash
ID=$(aws cloudformation detect-stack-drift --stack-name ace-web \
       --region us-east-1 --query StackDriftDetectionId --output text)
aws cloudformation describe-stack-drift-detection-status \
  --stack-drift-detection-id "$ID" --region us-east-1
```
