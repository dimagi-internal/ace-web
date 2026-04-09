#!/bin/bash
#
# ace-web one-time AWS setup runbook.
#
# Run this ONCE when first deploying ace-web to the connect-labs AWS
# environment. It creates all the AWS resources that the GitHub Actions
# deploy workflow then reuses on every deploy.
#
# Prerequisites:
#   - AWS CLI authenticated as an admin-level role in account 858923557655
#   - us-east-1 region
#   - The shared connect-labs infrastructure already exists:
#     * ECS cluster labs-jj-cluster
#     * ALB with a listener fronting labs.connect.dimagi.com
#     * RDS Postgres instance
#     * VPC subnets + security group
#
# This script is NOT idempotent — re-running it after resources exist will
# error on creation. Read the output and handle any partial runs by hand.
#
# Estimated runtime: ~5 minutes. Incremental cost after setup: ~$5-15/month.

set -euo pipefail

AWS_REGION="us-east-1"
ACCOUNT_ID="858923557655"
ECR_BACKEND="labs-jj-ace-web"
ECR_FRONTEND="labs-jj-ace-web-frontend"
TASK_FAMILY="labs-jj-ace-web"
SERVICE_NAME="labs-jj-ace-web"
TARGET_GROUP_NAME="labs-jj-ace-web-tg"
CLUSTER_NAME="labs-jj-cluster"
LOG_GROUP="/ecs/labs-jj-ace-web"

echo "=== ace-web AWS one-time setup ==="
echo "Region:  $AWS_REGION"
echo "Account: $ACCOUNT_ID"
echo

# ── 1. ECR repositories ────────────────────────────────────────────────

echo "→ Creating ECR repositories..."
aws ecr create-repository --repository-name "$ECR_BACKEND" --region "$AWS_REGION" || true
aws ecr create-repository --repository-name "$ECR_FRONTEND" --region "$AWS_REGION" || true

# ── 2. CloudWatch log group ────────────────────────────────────────────

echo "→ Creating CloudWatch log group..."
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$AWS_REGION" || true
aws logs put-retention-policy \
  --log-group-name "$LOG_GROUP" \
  --retention-in-days 30 \
  --region "$AWS_REGION"

# ── 3. Secrets Manager entries ─────────────────────────────────────────

echo "→ Creating Secrets Manager entries..."
echo "  NOTE: you will be prompted to paste secret values."

read -r -s -p "  DJANGO_SECRET_KEY (50+ random chars — gen with python -c 'import secrets; print(secrets.token_urlsafe(50))'): " DJANGO_SECRET_KEY; echo
read -r -s -p "  DATABASE_URL (postgres://user:pass@host:5432/ace_web): " DATABASE_URL; echo
read -r -s -p "  CONNECT_OAUTH_CLIENT_ID: " CONNECT_OAUTH_CLIENT_ID; echo
read -r -s -p "  CONNECT_OAUTH_CLIENT_SECRET: " CONNECT_OAUTH_CLIENT_SECRET; echo

aws secretsmanager create-secret \
  --name "ace-web/django-secret-key" \
  --secret-string "$DJANGO_SECRET_KEY" \
  --region "$AWS_REGION"
aws secretsmanager create-secret \
  --name "ace-web/database-url" \
  --secret-string "$DATABASE_URL" \
  --region "$AWS_REGION"
aws secretsmanager create-secret \
  --name "ace-web/connect-oauth-client-id" \
  --secret-string "$CONNECT_OAUTH_CLIENT_ID" \
  --region "$AWS_REGION"
aws secretsmanager create-secret \
  --name "ace-web/connect-oauth-client-secret" \
  --secret-string "$CONNECT_OAUTH_CLIENT_SECRET" \
  --region "$AWS_REGION"

# ── 4. IAM roles (execution + task) ────────────────────────────────────

echo "→ Creating IAM roles..."

aws iam create-role \
  --role-name labs-jj-ace-web-exec \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' || true

aws iam attach-role-policy \
  --role-name labs-jj-ace-web-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy \
  --role-name labs-jj-ace-web-exec \
  --policy-name ace-web-secrets-read \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": [\"secretsmanager:GetSecretValue\"],
      \"Resource\": \"arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:ace-web/*\"
    }]
  }"

aws iam create-role \
  --role-name labs-jj-ace-web-task \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' || true

# ── 5. Register the initial task definition ────────────────────────────

echo "→ Registering initial task definition..."
echo "  Uses deploy/aws/task-definition.json with the :latest tag."
echo "  After the first successful deploy, CI will register new revisions."

cd "$(dirname "$0")/../.."
aws ecs register-task-definition \
  --cli-input-json "file://deploy/aws/task-definition.json" \
  --region "$AWS_REGION"

# ── 6. Target group ────────────────────────────────────────────────────

echo "→ Creating target group..."
echo "  Find the VPC ID with: aws ec2 describe-vpcs --region $AWS_REGION"
read -r -p "  VPC ID (vpc-xxxxx): " VPC_ID

TG_ARN=$(aws elbv2 create-target-group \
  --name "$TARGET_GROUP_NAME" \
  --protocol HTTP \
  --port 3000 \
  --vpc-id "$VPC_ID" \
  --target-type ip \
  --health-check-path "/ace/api/health" \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --region "$AWS_REGION" \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

echo "  Target group ARN: $TG_ARN"

# ── 7. ALB listener rule ───────────────────────────────────────────────

echo "→ Adding ALB listener rule for /ace/* ..."
echo "  Find the ALB listener ARN with:"
echo "    aws elbv2 describe-load-balancers --region $AWS_REGION"
echo "    aws elbv2 describe-listeners --load-balancer-arn <alb-arn> --region $AWS_REGION"
read -r -p "  ALB listener ARN: " LISTENER_ARN
read -r -p "  Rule priority (unused integer, e.g. 200): " RULE_PRIORITY

aws elbv2 create-rule \
  --listener-arn "$LISTENER_ARN" \
  --priority "$RULE_PRIORITY" \
  --conditions "Field=path-pattern,Values=/ace/*" \
  --actions "Type=forward,TargetGroupArn=$TG_ARN" \
  --region "$AWS_REGION"

# ── 8. ECS service ─────────────────────────────────────────────────────

echo "→ Creating ECS service..."
read -r -p "  Subnet IDs (comma-separated, no spaces): " SUBNET_IDS
read -r -p "  Security group ID (sg-xxxxx): " SG_ID

aws ecs create-service \
  --cluster "$CLUSTER_NAME" \
  --service-name "$SERVICE_NAME" \
  --task-definition "$TASK_FAMILY" \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=web,containerPort=3000" \
  --region "$AWS_REGION"

# ── 9. Database creation reminder ──────────────────────────────────────

echo
echo "→ Create the 'ace_web' database on the shared RDS instance:"
echo ""
echo "    psql \"\$DATABASE_URL_WITHOUT_DB\" -c 'CREATE DATABASE ace_web;'"
echo ""
echo "  Where DATABASE_URL_WITHOUT_DB points at the RDS host without the"
echo "  trailing '/ace_web' — because the ace_web database doesn't exist"
echo "  yet. You must connect to a different database (e.g. 'postgres')"
echo "  first to run the CREATE DATABASE statement."

# ── Done ───────────────────────────────────────────────────────────────

echo
echo "✓ One-time setup complete."
echo
echo "Next steps:"
echo "  1. Register the OAuth client ID in CommCare Connect admin:"
echo "     https://connect.dimagi.com/admin/oauth2_provider/application/"
echo "     Callback URL: https://labs.connect.dimagi.com/ace/auth/callback/"
echo "     Grant type: Authorization code"
echo "     Client type: Confidential (PKCE required)"
echo "  2. Update ace-web/connect-oauth-client-id and -secret secrets with"
echo "     the real values from the Connect admin (if you entered placeholders)."
echo "  3. Trigger the deploy workflow: Actions > Deploy to Labs (AWS) > Run"
echo "     with run_migrations=true for the first deploy."
echo "  4. Visit https://labs.connect.dimagi.com/ace/ and sign in with a"
echo "     @dimagi.com CommCare Connect account."
