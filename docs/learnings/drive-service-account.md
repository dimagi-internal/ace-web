# Drive access via a shared service account

## Context

The ACE opportunity Workbench (`apps/opps`) reads (and is permitted to
write) Google Drive on behalf of every Dimagi user who opens it. It used
to do this via a per-user OAuth flow ported from connect-search: each
user granted Drive read scopes through a second Google consent screen,
and tokens were encrypted and cached on the `User` row.

That was replaced on 2026-04-09 with a single shared Google **service
account** that has been granted access to the team's ACE Shared Drive.
See `docs/specs/2026-04-09-drive-service-account-design.md` for the full
rationale.

## How the credentials flow

- **Prod:** AWS Secrets Manager stores the SA key JSON as a SecretString
  at `labs-jj-ace-web-drive-sa-key-json`. ECS delivers it to the task as
  env var `ACE_DRIVE_SA_KEY_JSON` via the `secrets` array in
  `deploy/aws/task-definition.json`.
- **Dev:** `.env` holds the same key as `ACE_DRIVE_SA_KEY_JSON` on a
  single line. `.env.example` shows the shape with a placeholder.
- **Code:** `apps/opps/drive_client.get_drive_client()` parses the JSON
  blob, constructs `google.oauth2.service_account.Credentials` at the
  full `drive` scope, and caches the resulting `GoogleDriveClient` via
  `functools.cache`. Every opps view calls this factory.

## Scope

The credentials are scoped to `https://www.googleapis.com/auth/drive`
— the full Drive scope, not `drive.readonly`. The `GoogleDriveClient`
surface stays read-only for now (the Workbench does not write), but
auth permits writes so a future feature can add a write method without
touching credentials.

## Shared Drive dependency

The SA can only access what the Shared Drive's ACLs grant it. If
someone removes the SA from the Shared Drive's members, the Workbench
breaks with opaque 403s from the Drive API. The SA email lives in
the SA key JSON under `client_email` — it is also the identity
`ace` CLI uses, so both tools break together if the SA loses access.

## Rotation

1. Generate a new key JSON in the GCP console for the same SA.
2. Update the Secrets Manager secret value (`aws secretsmanager
   put-secret-value --secret-id labs-jj-ace-web-drive-sa-key-json
   --secret-string file://new-key.json`).
3. Force a new ECS task (new deployment or `aws ecs update-service
   --force-new-deployment`). The new task picks up the rotated secret
   on boot; there is no in-process reload — `functools.cache` holds the
   old client for the lifetime of the old worker.
4. Revoke the old key in GCP.

## Why not Workload Identity Federation

WIF is Google's recommended pattern for non-GCP workloads and the right
long-term target. It was deferred to the Phase 5 security review:
setting up the Workload Identity Pool + provider binding is a
half-day of GCP IAM work and would split the auth story between
ace-web (WIF) and the `ace` CLI (SA key). Keeping both on the same
SA key is the simpler short-term posture.

## Failure mode

If `ACE_DRIVE_SA_KEY_JSON` is empty or unparseable, every opps API
request returns HTTP 500 with `error.code == "drive-not-configured"`.
This is deliberately loud — a missing SA key is a deploy configuration
bug, not a user-recoverable state.
