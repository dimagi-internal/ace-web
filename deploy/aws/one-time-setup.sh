#!/bin/bash
#
# ace-web one-time AWS setup runbook.
#
# Run this ONCE when first standing up ace-web in a new AWS environment.
#
# It creates ONLY the resources CloudFormation does not own: the ECR
# repositories, the Secrets Manager entries, and the two IAM roles. The task
# definition, ECS service, target group, listener rule and log group belong to
# the `ace-web` stack (deploy/aws/ace-web.cfn.yaml) — creating them here too
# would leave duplicates the stack cannot then adopt. Create the stack after
# this script; the closing "next steps" print the command.
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

echo "=== ace-web AWS one-time setup ==="
echo "Region:  $AWS_REGION"
echo "Account: $ACCOUNT_ID"
echo

# ── 1. ECR repositories ────────────────────────────────────────────────

echo "→ Creating ECR repositories..."
aws ecr create-repository --repository-name "$ECR_BACKEND" --region "$AWS_REGION" || true
aws ecr create-repository --repository-name "$ECR_FRONTEND" --region "$AWS_REGION" || true

# ── 2. Secrets Manager entries ─────────────────────────────────────────

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

# ── 3. IAM roles (execution + task) ────────────────────────────────────

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

# ── 4. Database creation reminder ──────────────────────────────────────

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
echo "  1. Register the OAuth client ID in Connect admin:"
echo "     https://connect.dimagi.com/admin/oauth2_provider/application/"
echo "     Callback URL: https://labs.connect.dimagi.com/ace/auth/callback/"
echo "     Grant type: Authorization code"
echo "     Client type: Confidential (PKCE required)"
echo "  2. Update ace-web/connect-oauth-client-id and -secret secrets with"
echo "     the real values from the Connect admin (if you entered placeholders)."
echo "  3. Create the stack, which owns the task definition, service, target"
echo "     group, listener rule and log group:"
echo ""
echo "       aws cloudformation deploy --stack-name ace-web \\"
echo "         --template-file deploy/aws/ace-web.cfn.yaml \\"
echo "         --capabilities CAPABILITY_IAM --parameter-overrides ImageTag=<sha>"
echo ""
echo "  4. Trigger the deploy workflow: Actions > Deploy to Labs (AWS) > Run"
echo "     with run_migrations=true for the first deploy."
echo "  5. Visit https://labs.connect.dimagi.com/ace/ and sign in with a"
echo "     @dimagi.com Connect account."
