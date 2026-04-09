# Drive OAuth as a secondary flow

## Context

ace-web's identity auth is a hand-rolled CommCare Connect OAuth flow with
PKCE (apps/auth/oauth.py + apps/auth/oauth_views.py, ported from connect-labs,
post the AWS pivot — see the commit history around the scout-pattern tenant move).
That flow tells us *who* the user is, filtered to `@dimagi.com`, but it does
NOT give ace-web access to the user's Google Drive.

The ACE opportunity Workbench (apps/opps) needs to read Google Drive on the
user's behalf to show the team's opp folders. So it runs a **second OAuth
flow** — a separate Google consent screen — just for the Drive scope.

## Pattern

Copied from `../connect-search/backend/app/core/{drive,auth}.py` +
`app/api/auth.py`. Translated from FastAPI to Django views. The concrete
pieces:

- `apps/opps/drive_auth_views.py` — `/auth/drive/start` and
  `/auth/drive/callback` Django views
- `apps/opps/encryption.py` — Fernet wrapper that reads the key from
  `settings.ACE_DRIVE_TOKEN_ENCRYPTION_KEY` (sourced from AWS Secrets Manager
  in prod)
- `apps/auth/models.py::User.drive_token_cache` — encrypted JSON blob per user
- `apps/opps/drive_credentials.py` — `ensure_fresh(token_data)` helper that
  transparently refreshes expired access tokens and returns a new token
  dict the caller persists back to the User row
- `apps/opps/drive_for_request.py::get_drive_client_for(user)` — the one
  call views use to get a working `GoogleDriveClient` instance

## Why not one flow?

connect-search uses a single Google OAuth flow for both identity and Drive.
ace-web can't because its identity source of truth is CommCare Connect (a
Dimagi-controlled OAuth provider), not Google. The Drive flow has to layer
on top — the user logs into ace-web via CommCare Connect, then when they
visit `/opps` they are asked to additionally grant Drive read access.

A single unified flow would require moving identity back to Google, which
loses the CommCare Connect integration benefits (Dimagi-managed user pool,
shared session with other Connect tools). Two flows is the right call.

## Refresh behavior

Access tokens expire hourly. The `ensure_fresh` helper checks expiry with a
60-second buffer on every request and refreshes via the refresh token when
needed. If the refresh itself fails (revoked grant, expired refresh token,
network error), the middleware returns a 401 with
`{"data": {"reconnect_url": "/auth/drive/start"}}` and the frontend's
`DriveReconnectGuard` redirects the user through a fresh consent grant.

## Scopes

Read-only: `drive.readonly` + `spreadsheets.readonly`. The Workbench never
writes to Drive. Any future write features (e.g. "publish a comment on an
opp folder") need an additive consent grant, not a scope upgrade on the
existing flow, because Google's consent UX is clearer when new scopes are
explicitly requested.
