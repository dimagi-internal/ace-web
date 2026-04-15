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
  `/ace/static/*`, and `/ace/ws/*` to localhost:8000)
- **Load balancer:** shared labs ALB with a listener rule routing `/ace/*`
  to the ace-web target group
- **Database:** shared RDS Postgres instance, database `ace_web`
- **Cache/Redis:** shared ElastiCache — Phase 3 uses this for the
  `RedisChannelLayer` (cross-task WebSocket broadcast) and presence HASH
  storage. Sourced via the `REDIS_URL` secret (see below)
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
| `REDIS_URL` | Shared ElastiCache primary endpoint: `redis://<endpoint>:6379/0` (see "Phase 3 Redis setup" below) |
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

### Claude CLI OAuth token secret

`apps/common/auth_flow.py` writes the OAuth token produced by `claude setup-token`
to disk at `/var/lib/ace-claude/oauth-token`. Because Fargate tasks have no
persistent volume, every deploy (or task restart) wipes that file and forces a
re-login at `/ace/auth/cli`. To make the token survive deploys we stash it in
AWS Secrets Manager and inject it as the `CLAUDE_CODE_OAUTH_TOKEN` env var,
which the CLI picks up automatically.

**One-time setup:**

1. Complete the OAuth flow once via `/ace/auth/cli` so you have a valid token
   on disk in the running container (or capture one locally by running
   `claude setup-token`).
2. Create the secret (empty placeholder is fine — `auth_flow.store_token`
   will overwrite it on the next successful re-auth):
   ```bash
   aws secretsmanager create-secret \
     --region us-east-1 \
     --name labs-jj-ace-web-claude-oauth-token \
     --description "Claude CLI OAuth token for ace-web (sk-ant-oat…)" \
     --secret-string "sk-ant-oat01-REPLACE-WITH-REAL-TOKEN"
   ```
3. Update `deploy/aws/task-definition.json` — the `CLAUDE_CODE_OAUTH_TOKEN`
   entry in the `secrets` array uses a placeholder ARN ending in
   `-claude-oauth-token-REPLACE`. Swap it for the real ARN:
   ```bash
   aws secretsmanager describe-secret \
     --secret-id labs-jj-ace-web-claude-oauth-token \
     --query ARN --output text
   ```
4. Grant the **task role** (not the execution role) permission to overwrite
   the secret so re-auths via `/ace/auth/cli` persist:
   ```bash
   aws iam put-role-policy \
     --role-name labs-jj-ecs-task-role \
     --policy-name ace-web-claude-token-write \
     --policy-document '{
       "Version": "2012-10-17",
       "Statement": [{
         "Effect": "Allow",
         "Action": ["secretsmanager:PutSecretValue"],
         "Resource": "arn:aws:secretsmanager:us-east-1:858923557655:secret:labs-jj-ace-web-claude-oauth-token-*"
       }]
     }'
   ```
   The execution role's existing `labs-jj-ace-web-*` wildcard already covers
   `GetSecretValue` for task startup.
5. Deploy. At container start the real token is injected into the env; on any
   future re-auth through `/ace/auth/cli`, `store_token()` calls
   `PutSecretValue` so the new token is what the *next* deploy picks up.

**Token lifetime:** Claude OAuth tokens last ~1 year. If the token gets
revoked or expires, re-auth through `/ace/auth/cli` — the write-back keeps
the secret fresh.

### ALB target-group stickiness

The `/ace/auth/cli/*` endpoints spawn a long-lived `claude setup-token`
PTY subprocess that must outlive one HTTP call (URL fetch) and pick up
again on the next (code submit). The subprocess is module-global state
on one ECS task, so both requests have to land on the same task or the
second call returns "No active auth flow" instantly.

To keep the service at `desiredCount > 1`, enable `lb_cookie`
stickiness on the target group:

```bash
aws elbv2 modify-target-group-attributes \
  --region us-east-1 \
  --target-group-arn $(aws elbv2 describe-target-groups \
    --region us-east-1 --names labs-jj-ace-web-tg \
    --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --attributes \
    Key=stickiness.enabled,Value=true \
    Key=stickiness.type,Value=lb_cookie \
    Key=stickiness.lb_cookie.duration_seconds,Value=3600
```

Each browser gets an `AWSALB` cookie that pins it to one task for an
hour. Chat traffic is multi-task safe (Redis channel layer), so if the
pinned task dies the user's next request fails over cleanly. The only
surface affected is the auth flow, and a 1-hour window comfortably
covers a `claude setup-token` round-trip.

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

## E2E tests

Phase 3's multi-player WebSocket flow has a Playwright smoke test at
`e2e/tests/multiplayer.spec.ts`. It uses two dev-only hooks gated by
`ACE_ALLOW_TEST_LOGIN` and `ACE_USE_FAKE_CLI_BACKEND` (both True only
in `config/settings/development.py` + `config/settings/e2e.py`):

- `POST /auth/test-login/` creates or logs in a `@dimagi.com` user
  without going through OAuth.
- `FakeCLIBackend` replaces the real `CLIBackend` with a scripted
  echo response so the test asserts on deterministic content without
  a real Claude CLI subprocess.

The suite runs the whole stack (Django + Channels + React) against a
file-backed sqlite, `InMemoryChannelLayer`, and fakeredis via
`config/asgi_e2e.py` — no Docker, Postgres, or Redis required. See
`e2e/README.md` for run instructions.

These hooks are **impossible to enable in production** — the URL
registration itself requires both `ACE_ALLOW_TEST_LOGIN` and `DEBUG`
to be True, and `production.py` / `connectlabs.py` both inherit
`DEBUG=False` from base.

## Phase 3 Redis setup (`REDIS_URL`)

Phase 3 introduces `channels-redis` and WebSocket presence storage, both
of which require a Redis endpoint shared across ECS tasks. The connection
string is exposed to the `api` container as the `REDIS_URL` env var,
sourced from AWS Secrets Manager alongside `DATABASE_URL`.

**What uses it:**
- `config/settings/base.py` — `CHANNEL_LAYERS` points `RedisChannelLayer`
  at `REDIS_URL` for cross-task WebSocket broadcast
- `apps/common/redis_client.py` — `get_redis()` reads `settings.ACE_REDIS_URL`
  for presence HASH read/write (`apps/sessions/presence.py`) and draft
  state machine bookkeeping

**Value shape:** `redis://<elasticache-primary-endpoint>:6379/0` — the
shared labs ElastiCache cluster, DB index 0. If another labs tenant starts
using the same cluster, move ace-web to a distinct DB index.

**Create the secret** (first time only):

```bash
aws secretsmanager create-secret \
  --region us-east-1 \
  --name labs-jj-ace-web-redis-url \
  --secret-string "redis://<elasticache-primary-endpoint>:6379/0"
```

Then update `deploy/aws/task-definition.json` — the `REDIS_URL` entry in
the `secrets` array uses a placeholder ARN without the AWS-appended random
suffix. Replace it with the real ARN from `aws secretsmanager describe-secret
--secret-id labs-jj-ace-web-redis-url --query ARN`.

**Verify it's set in a running task:**

```bash
aws ecs execute-command \
  --region us-east-1 \
  --cluster labs-jj-cluster \
  --task <task-id> \
  --container api \
  --interactive \
  --command "/bin/sh -c 'env | grep REDIS_URL'"
```

**Scaling past 1 ECS task:** the old `InMemoryChannelLayer` pinned
ace-web to a single task (see `docs/learnings/channels-single-instance.md`).
Once `REDIS_URL` is verified working end-to-end (open two browsers in one
session, confirm draft updates and presence propagate), it is safe to
raise `desiredCount` on the ECS service. Do this as a canary: bump to 2
first, watch CloudWatch logs for handshake errors, then scale further.

## WebSocket proxy path

The frontend connects to `wss://labs.connect.dimagi.com/ace/ws/sessions/<slug>/`.
The nginx sidecar has a dedicated `/ace/ws/` location block that:

1. Sets the `Upgrade` and `Connection: upgrade` headers so nginx upgrades
   the HTTP/1.1 connection to a WebSocket
2. Rewrites the request URI by stripping the `/ace` prefix (via the
   trailing slash on `proxy_pass http://127.0.0.1:8000/ws/;`)
3. Raises `proxy_read_timeout` / `proxy_send_timeout` to 3600s so
   long-lived idle presence connections don't drop at the default 60s

This prefix strip is necessary because Django's `FORCE_SCRIPT_NAME=/ace`
only applies to HTTP URL reversing — Channels URL routing in
`apps/sessions/routing.py` registers `ws/sessions/<slug>/` without any
`/ace` prefix. Without the nginx block the WS handshake would fall
through to the `/ace/` SPA catch-all and return `index.html` instead of
upgrading. The local dev Vite proxy in `frontend/vite.config.ts`
mirrors this with a matching `/ace/ws` entry + `rewrite`.

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
