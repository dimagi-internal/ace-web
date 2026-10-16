# Sign-in: what is configured, and what a human still has to do

Design: `docs/specs/2026-10-08-normal-login-design.md`. Admission rule:
`apps/auth/login_gate.py`. Shared sign-in path: `apps/auth/identity.py`.

| Method | Works out of the box? | Needs |
|---|---|---|
| Email + password | Yes | Users get a password from an invite or from Django admin |
| Sign in with Connect | Yes (unchanged) | existing `CONNECT_OAUTH_*` secrets |
| Sign in with Google | **No — button hidden** | Steps 1–3 below |
| Password reset by email | **No — routes 404** | See "Password reset email" below |

## Google sign-in (one console step, then secrets)

1. **Google Cloud Console → APIs & Services → Credentials → Create OAuth client
   ID → Web application**, in a Dimagi-owned project. Authorized redirect URI:
   `https://labs.connect.dimagi.com/ace/auth/google/callback/` (plus
   `http://localhost:8000/ace/auth/google/callback/` for local dev). Configure
   the OAuth consent screen as **External** if partners use non-Google-Workspace
   addresses (Internal would admit only Dimagi's Workspace). Scopes are the
   non-sensitive `openid email profile`; no Google verification review needed.
2. Store the client id and secret in AWS Secrets Manager
   (account `858923557655`, `us-east-1`), e.g. `ace-web/google-oauth-client-id`
   and `ace-web/google-oauth-client-secret`.
3. In `deploy/aws/ace-web.cfn.yaml` add to the `Secrets:` list of the `api`
   container (alphabetical, next to `DJANGO_SECRET_KEY`):
   ```yaml
   - Name: GOOGLE_OAUTH_CLIENT_ID
     ValueFrom: "arn:aws:secretsmanager:us-east-1:858923557655:secret:<full ARN incl. suffix>"
   - Name: GOOGLE_OAUTH_CLIENT_SECRET
     ValueFrom: "arn:aws:secretsmanager:us-east-1:858923557655:secret:<full ARN incl. suffix>"
   ```
   The task execution role needs `secretsmanager:GetSecretValue` on them (the
   existing `ace-web/*` policy may already cover it). **Create the secrets
   first**: a task definition that names a missing secret fails to start.
   Then deploy through the standard pipeline. The Google button appears
   automatically once both values are set.

## Outbound email

Labs sends mail through SES's API as the ECS task role — no SMTP credentials.
`ACE_EMAIL_ENABLED=true` (set in `deploy/aws/ace-web.cfn.yaml`) selects
django-anymail's SES backend. The task role `labs-jj-ecs-task-role` already
holds `ses:SendEmail` on the `labs.connect.dimagi.com` identity and the
`labs-jj-email` configuration set (connect-labs `infra/labs-email.yml`, policy
`labs-ses-send`), so the sender must be on that domain:
`DEFAULT_FROM_EMAIL=ACE <noreply@labs.connect.dimagi.com>`. Any other From is
refused by SES. Bounces and complaints reach the `labs-jj-email-events` SNS
topic through the configuration set.

What sends today: **workspace invites**. Creating an invite emails its accept
link (Reply-To: the inviter), and **Resend** on a pending invite emails the
same link again with a fresh 14-day expiry. A failed send never fails the
invite — the settings page then shows the link to copy instead.

## Password reset email

Reset is still behind `ACE_PASSWORD_RESET_ENABLED` (default false; an admin can
set a password in Django admin, and signed-in users can change theirs at
`/auth/password/`). Outbound email now exists, so turning it on is: set
`ACE_PASSWORD_RESET_ENABLED=True` in the task definition, deploy, and test one
reset to a mailbox you own before telling anyone. (The older `EMAIL_URL` SMTP
path still works for local setups but is not used on labs.)

## Giving an agent (hal@, ada@) a token without HQ

Create the user in Django admin (`/ace/admin/ace_auth/user/add/`) with a password
— its domain is admitted by `ACE_ALLOWED_EMAIL_DOMAINS` — then run the usual
`/ace:ace-web-pat-mint`; the browser step now offers email + password.

## Operating notes

* Un-invited outsiders are refused by every method with the same message. To
  cut someone off, remove their last workspace membership (and any pending
  invite); a password does not keep them in.
* Brute-force limits live in the cache (Redis in prod) and reset on deploy by
  design.
