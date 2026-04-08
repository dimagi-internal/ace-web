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
  gcloud secrets create django-secret --data-file=-

echo -n 'postgres://ace:REPLACE_ME@/ace_web?host=/cloudsql/PROJECT_ID:us-central1:ace-web-db' | \
  gcloud secrets create database-url --data-file=-
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
# Health check is publicly accessible (not behind IAP)
curl -s ${URL}/api/health
```

Expected: `{"data": {"status": "ok"}, "error": null}`

Then open `${URL}/` in a browser; you should see Google SSO and then the React shell.

## Notes

- `--min-instances=1, --max-instances=1` — Module 1 runs on a single instance
  because Channels uses `InMemoryChannelLayer`. Before scaling up, switch to
  `channels-redis` and provision a Memorystore Redis instance.
- The `CLAUDE_CODE_OAUTH_TOKEN` from Claude Code CLI subscription auth will
  land in Plan 1B; this plan has no dependency on it.
