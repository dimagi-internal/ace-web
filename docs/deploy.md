# Deploying ace-web to GCP Cloud Run

This document covers the one-time GCP project setup required before
`cloudbuild.yaml` will work. After this setup, every push to `main`
(once a Cloud Build trigger is configured) auto-deploys.

## Prerequisites

- A GCP project with billing enabled
- `gcloud` CLI installed and authenticated
- `PROJECT_ID` exported in your shell

## One-time setup

### 1. Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  iap.googleapis.com
```

### 2. Create the Artifact Registry repo

```bash
gcloud artifacts repositories create ace-web \
  --repository-format=docker \
  --location=us-central1
```

### 3. Create the Cloud SQL instance

```bash
gcloud sql instances create ace-web-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-central1

gcloud sql databases create ace_web --instance=ace-web-db

gcloud sql users create ace --instance=ace-web-db --password='REPLACE_ME'
```

### 4. Store secrets

```bash
echo -n 'long-random-django-key' | \
  gcloud secrets create ace-web-django-secret --data-file=-

echo -n 'postgres://ace:REPLACE_ME@/ace_web?host=/cloudsql/PROJECT_ID:us-central1:ace-web-db' | \
  gcloud secrets create ace-web-database-url --data-file=-
```

### 5. Initial deploy

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_ALLOWED_HOSTS=placeholder
```

After the first deploy, note the actual Cloud Run URL and update
`_ALLOWED_HOSTS` in `cloudbuild.yaml`.

### 6. Configure IAP

1. In the Cloud Console, navigate to **Security → Identity-Aware Proxy**
2. Find the `ace-web` Cloud Run service
3. Toggle IAP **on**
4. Add the team's Google accounts as **IAP-secured Web App User** principals

After IAP is configured, navigating to the service URL prompts a Google login.
Once logged in as an authorized user, requests reach the app with the
`X-Goog-Authenticated-User-Email` and `X-Goog-Authenticated-User-ID` headers
that the `IAPHeaderAuthMiddleware` reads.

## Smoke test

```bash
URL=$(gcloud run services describe ace-web --region=us-central1 --format='value(status.url)')
# All external requests pass through IAP first — need an identity token even
# for /api/health. The health endpoint is middleware-exempt inside Django,
# not IAP-exempt at the GCP layer.
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" ${URL}/api/health
```

Expected: `{"data": {"status": "ok"}, "error": null}`

Then open `${URL}/` in a browser; you should see Google SSO and then the React shell.

## Notes

- `--min-instances=1, --max-instances=1` — Module 1 runs on a single instance
  because Channels uses `InMemoryChannelLayer`. Before scaling up, switch to
  `channels-redis` and provision a Memorystore Redis instance.
- The `CLAUDE_CODE_OAUTH_TOKEN` from Claude Code CLI subscription auth will
  land in Plan 1B; this plan has no dependency on it.

## Filestore (persistent CLI state)

ace-web mounts a Filestore (NFS) volume at `/var/lib/ace-claude` on Cloud Run
to persist the OAuth token and the Claude CLI's `~/.claude` session store
across instance restarts. Without it, every cold start would require the
CLIBackend to fall back to its Django-replay path.

### One-time provisioning

```bash
# Create a VPC network if you don't have one
gcloud compute networks create ace-web --subnet-mode=auto

# Allocate a Filestore instance (~$25/mo minimum)
gcloud filestore instances create ace-web-claude \
  --region=us-central1 \
  --tier=BASIC_HDD \
  --file-share=name=ace_claude,capacity=1024 \
  --network=name=ace-web

# Note the IP address — you need it in cloudbuild.yaml
gcloud filestore instances describe ace-web-claude --region=us-central1 \
  --format='value(networks.ipAddresses[0])'

# Create the VPC connector that Cloud Run uses to reach Filestore
gcloud compute networks vpc-access connectors create ace-web-connector \
  --region=us-central1 \
  --network=ace-web \
  --range=10.8.0.0/28
```

Then update `cloudbuild.yaml` substitutions `_FILESTORE_IP`, `_FILESTORE_SHARE`,
and `_VPC_CONNECTOR` to match.

### Why Filestore (and not GCS Fuse)

Filestore gives the CLI POSIX semantics that the Claude CLI's session store
relies on. GCS Fuse is cheaper but its sync and locking semantics are not
guaranteed to match a real POSIX filesystem, and the CLI was not designed
against it.

If Filestore cost is a problem, the CLIBackend's hybrid resume strategy is
the safety net — drop the Filestore mount, accept that every cold start
rehydrates from Django history, and document the trade-off.
