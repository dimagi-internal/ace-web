# Sign-in: what is configured, and what a human still has to do

Design: `docs/specs/2026-10-08-normal-login-design.md`. Admission rule:
`apps/auth/login_gate.py`. Shared sign-in path: `apps/auth/identity.py`.

| Method | Works out of the box? | Needs |
|---|---|---|
| Email + password | Yes | Users get a password from an invite or from Django admin |
| Sign in with CommCare | Yes (unchanged) | existing `CONNECT_OAUTH_*` secrets |
| Sign in with Google | **No — button hidden** | Steps 1–3 below |
| Password reset by email | **No — routes 404** | Steps 4–5 below |

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

## Password reset email

Production has no mail backend. Until one exists, `ACE_PASSWORD_RESET_ENABLED`
stays false and reset is unavailable (an admin can set a password in Django
admin; users who are signed in can change theirs at `/auth/password/`).

4. Pick a sender. SES is the obvious choice on this AWS account: verify the
   sending identity (`dimagi-ai.com` or `ace@dimagi-ai.com`), get out of the SES
   sandbox if recipients are external, create SMTP credentials.
5. Add to the container: secret `EMAIL_URL`
   (`smtp+tls://<user>:<pass>@email-smtp.us-east-1.amazonaws.com:587`, URL-encode
   the password), env `DEFAULT_FROM_EMAIL` (e.g. `ace-web <ace@dimagi-ai.com>`),
   env `ACE_PASSWORD_RESET_ENABLED=True`. Deploy. Test with one reset to a
   mailbox you own before telling anyone.

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
