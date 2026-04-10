# Deploying ace-web to AWS (connect-labs tenant)

ace-web is deployed as a tenant service behind the `labs.connect.dimagi.com`
ALB on AWS ECS Fargate, reusing the shared connect-labs infrastructure
(RDS, ElastiCache, ALB, VPC). The deployment pattern mirrors
[scout-jjackson](/Users/jjackson/emdash-projects/scout-jjackson)'s.

## Architecture

- **Cloud:** AWS account `858923557655`, region `us-east-1`
- **Compute:** ECS Fargate task in cluster `labs-jj-cluster`
- **Task layout:** two containers in one task — `api` (Django + uvicorn on
  port 8000) and `web` (nginx serving the Vite bundle on port 3000,
  reverse-proxying `/ace/api/*`, `/ace/auth/*`, `/ace/admin/*`,
  `/ace/static/*` to localhost:8000)
- **Load balancer:** shared labs ALB with a listener rule routing `/ace/*`
  to the ace-web target group
- **Database:** shared RDS Postgres instance, database `ace_web`
- **Cache/Redis:** shared ElastiCache (used in Phase 3 for channels-redis;
  idle in Phase 2)
- **Secrets:** AWS Secrets Manager under the `ace-web/` prefix
- **Logs:** CloudWatch Logs group `/ecs/labs-jj-ace-web`, 30-day retention
- **Auth:** CommCare Connect OAuth with PKCE, `@dimagi.com` email filter
- **Deploy:** GitHub Actions `.github/workflows/deploy-labs.yml` (manual
  `workflow_dispatch` trigger)

## First-time setup

Run `deploy/aws/one-time-setup.sh` from an AWS-authenticated shell in
account `858923557655`. It creates:

- ECR repos (`labs-jj-ace-web`, `labs-jj-ace-web-frontend`)
- CloudWatch log group with 30-day retention
- Secrets Manager entries (prompts for values)
- IAM execution and task roles
- Initial ECS task definition revision (from `deploy/aws/task-definition.json`)
- ALB target group (health check `/ace/api/health`)
- ALB listener rule routing `/ace/*`
- ECS service (desired count 1, rolling deploy)

You will be prompted for:

| Input | How to get it |
|---|---|
| Django secret key | `python -c 'import secrets; print(secrets.token_urlsafe(50))'` |
| `DATABASE_URL` | Shared RDS endpoint + the new `ace_web` database name |
| Connect OAuth client id + secret | Register at https://connect.dimagi.com/admin/oauth2_provider/application/ with callback `https://labs.connect.dimagi.com/ace/auth/callback/` |
| VPC ID | `aws ec2 describe-vpcs --region us-east-1` |
| ALB listener ARN | `aws elbv2 describe-listeners --load-balancer-arn <labs-alb-arn>` |
| Subnet IDs | Same subnets scout uses (in `LABS_SUBNET` GitHub secret) |
| Security group ID | Same SG scout uses (in `LABS_SECURITY_GROUP` GitHub secret) |

After setup, create the `ace_web` database on the shared RDS instance:

```bash
psql "postgresql://<admin>:<pass>@<host>:5432/postgres" -c "CREATE DATABASE ace_web;"
```

### Google Drive service account secret

The opportunity Workbench reads Google Drive via a shared service
account. The SA JSON key is stored in AWS Secrets Manager as a
SecretString and delivered to ECS as env var `ACE_DRIVE_SA_KEY_JSON`.

**One-time setup:**

1. Download the SA key JSON from the GCP console for the
   `ace-<project>@<project>.iam.gserviceaccount.com` service account
   (the same SA used by the `ace` CLI plugin).
2. Create the secret:
   ```bash
   aws secretsmanager create-secret \
     --name labs-jj-ace-web-drive-sa-key-json \
     --description "Google service account key JSON for the ACE Drive access" \
     --secret-string file:///path/to/sa-key.json \
     --region us-east-1
   ```
3. Update `deploy/aws/task-definition.json` — the `valueFrom` ARN for
   `ACE_DRIVE_SA_KEY_JSON` needs the 6-character suffix that Secrets
   Manager generates on create (e.g.
   `...-drive-sa-key-json-AbCdEf`). Grab it with:
   ```bash
   aws secretsmanager describe-secret \
     --secret-id labs-jj-ace-web-drive-sa-key-json \
     --query ARN --output text
   ```
4. Confirm the task execution role's resource policy covers the new
   secret ARN. The existing policy uses a `labs-jj-ace-web-*` wildcard
   which should match.
5. Delete the downloaded JSON file from local disk.

**Rotation:** see `docs/learnings/drive-service-account.md`.

## Deploy workflow

Triggered manually from GitHub Actions:

1. Go to **Actions → "Deploy to Labs (AWS)" → "Run workflow"**
2. Select options:
   - `deploy_target`: `auto` (let change detection decide), `all`,
     `backend-only`, or `frontend-only`
   - `run_migrations`: `true` on the first deploy and any schema-changing
     deploy; `false` otherwise
3. The workflow:
   - Authenticates via OIDC using `AWS_ROLE_ARN`
   - Builds and pushes backend + frontend images to ECR in parallel
   - Runs `manage.py migrate --noinput` as a one-off FARGATE task (if
     `run_migrations=true`)
   - Patches `deploy/aws/task-definition.json` with the new image SHA tags
     via `jq`, registers a new task definition revision
   - Calls `ecs update-service --task-definition <new-arn>` to trigger a
     rolling deploy
   - Waits for `services-stable`

## Local development

```bash
docker compose up
```

Backend at `http://localhost:8000`. No path prefix locally — `FORCE_SCRIPT_NAME`
is only set in `config/settings/connectlabs.py`, not in `development.py`.
The Vite dev server runs separately:

```bash
cd frontend && npm run dev
```

For prod-parity testing with the full two-container layout (backend + nginx
sidecar):

```bash
docker compose --profile prod-parity up
```

Then visit `http://localhost:3000/ace/`. This builds and runs the nginx
container with the real Vite bundle and exercises the same routing as
production.

## Observability

- **Logs:** CloudWatch `/ecs/labs-jj-ace-web` — separate streams for `api`
  and `web` containers
- **Metrics:** ECS service metrics in the AWS console
- **Alarms:** none yet (Phase 5 adds SLO alarms)

## Rollback

ECS keeps all prior task definition revisions. To roll back:

```bash
# List revisions
aws ecs list-task-definitions --family-prefix labs-jj-ace-web --region us-east-1

# Update the service to a previous revision
aws ecs update-service \
  --cluster labs-jj-cluster \
  --service labs-jj-ace-web \
  --task-definition labs-jj-ace-web:<previous-revision-number> \
  --region us-east-1
```

## Cost

Estimated incremental cost: **~$5-15/month** (shared ALB, RDS, ElastiCache,
VPC amortized across all labs tenants — only the ECS task CPU/memory and
ECR storage are ace-web-specific).

## Troubleshooting

**503 from the ALB** — target group has no healthy targets. Check
CloudWatch logs for the `api` container. Usually a `DJANGO_SECRET_KEY` or
`DATABASE_URL` misconfiguration, or a failed migration.

**Health check failing** — the ALB health check hits `/ace/api/health` via
the nginx container on port 3000. Verify nginx is proxying correctly
(reproduce locally with `docker compose --profile prod-parity up`) and
that the Django `/api/health` endpoint is still reachable without auth.

**OAuth callback loop** — verify the CommCare Connect OAuth application's
callback URL is exactly `https://labs.connect.dimagi.com/ace/auth/callback/`
and the `CONNECT_OAUTH_CLIENT_ID` / `CONNECT_OAUTH_CLIENT_SECRET` secrets
in AWS Secrets Manager match what's in the Connect admin.

**CSRF failures after login** — verify `SESSION_COOKIE_NAME=sessionid_ace`
and `CSRF_COOKIE_NAME=csrftoken_ace` are active (from
`config/settings/connectlabs.py`). Collisions with scout's cookies on the
shared `labs.connect.dimagi.com` domain cause surprising failures.

**Admin POST returns 403** — `CSRF_TRUSTED_ORIGINS` in `connectlabs.py`
must include `https://labs.connect.dimagi.com`. Without this, any POST
from the ALB-fronted origin is rejected regardless of the CSRF token.

**Migrations not applied** — the `run_migrations` workflow input must be
set to `true`. Migrations run as a one-off FARGATE task BEFORE the
rolling deploy, against the `:latest` image tag (which CI has just pushed).
