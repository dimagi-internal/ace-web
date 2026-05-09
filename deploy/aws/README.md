# deploy/aws/

AWS deployment artifacts for ace-web.

## Files

- `task-definition.json` — Canonical ECS task definition. Source of truth for the two-container layout (Django backend + nginx frontend). Registered in AWS via `aws ecs register-task-definition` on each deploy.
- `one-time-setup.sh` — Bash runbook that creates ECR repos, Secrets Manager entries, the target group + ALB listener rule, IAM roles, and the ECS service. Run once per environment.

## Deploy flow

1. Developer pushes to `main` (or triggers workflow_dispatch).
2. `.github/workflows/deploy-ace-web-labs.yml` runs:
   - Authenticates to AWS via OIDC (AWS_ROLE_ARN secret)
   - Builds backend and frontend images in parallel
   - Pushes both to ECR with tags `:latest` and `:$GITHUB_SHA`
   - Registers a new ECS task definition revision with the new image tags
   - Runs `manage.py migrate` as a one-off FARGATE task
   - Calls `ecs update-service --task-definition <new-arn>` to trigger a rolling deploy
   - Waits for service stability

## First-time setup

See `one-time-setup.sh` and `docs/deploy.md` for the full runbook.
