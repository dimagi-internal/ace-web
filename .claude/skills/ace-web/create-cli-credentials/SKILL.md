---
name: ace-web:create-cli-credentials
description: Connect a developer's local claude CLI credentials to a deployed ace-web instance. Reads the local credential blob (macOS Keychain or Linux ~/.claude/.credentials.json), mints a personal bearer token, and POSTs the blob to /api/auth/cli/upload. Use when the user asks to "connect my CLI", "upload credentials", "hook up claude", or when /auth/cli shows "not connected".
---

# create-cli-credentials

Ship the developer's local claude CLI credential blob to a deployed
ace-web so the server's `claude -p` subprocess can use it.

Full architecture: `docs/architecture/cli-credentials.md`.

## When to invoke

- User says "connect my CLI credentials to the server", "upload
  credentials", "hook up the deployed app to my local claude", etc.
- `/auth/cli` on the deployed instance shows "not connected".
- After a refresh-token rotation where re-upload is needed.
- First-time developer setup for a new ace-web instance.

## Preconditions to verify

1. **Local claude CLI is authenticated.** Run
   `python scripts/ace_cli_login.py --dry-run` from the repo root. If
   it prints `found credentials (accessToken prefix=sk-ant-oat01-..., len=...)`,
   we're good. If it prints `no local credentials found`, stop and
   have the user run `claude setup-token` and complete the browser
   flow, then retry.

2. **User knows the target ace-web URL.** The default is the prod labs
   URL `https://labs.connect.dimagi.com/ace`. Ask if a different
   instance is intended.

3. **User has a personal bearer token minted at `$ACE_URL/settings`.**
   If not, direct them to visit the Settings page and mint one with
   label `cli-upload` (or similar), then paste the `raw_token` value
   when prompted. Tell them the full URL — never a bare path.

## Steps

1. Confirm `ACE_URL` (default `https://labs.connect.dimagi.com/ace`).
2. Confirm `ACE_TOKEN` is available — if not, pause and instruct the
   user to mint one at `<ACE_URL>/settings`, then resume.
3. Run the uploader:
   ```
   ACE_URL=<url> ACE_TOKEN=<token> python scripts/ace_cli_login.py
   ```
4. Parse the output. Exit codes:
   - `0` → uploaded, server confirms `authenticated=True`. Done.
   - `1` → local creds missing or malformed. Have user run
     `claude setup-token` and retry.
   - `2` → uploaded but live CLI check failed (token stored, `claude -p`
     from the server got 401). Either the access token is stale and
     refresh failed, or the deployed server can't reach Anthropic.
     Check server logs via `aws logs tail /ecs/labs-jj-ace-web
     --since 3m --region us-east-1 --profile labs | grep "CLI token check"`.
   - `3` → network/HTTP error. Validate URL, token, and connectivity.
5. On success, confirm end-to-end by fetching status:
   ```
   curl -s <url>/api/auth/cli/status
   ```
   Expect `{"data":{"authenticated":true},"error":null}`.

## Failure modes and recovery

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rc=1 "no local credentials found"` | User never ran `claude setup-token` locally | Have them run it, complete browser auth, retry. |
| `rc=2 "live check failed"` | Token stored, but `claude -p` on server 401s. Either (a) the blob's accessToken expired and the server's network can't reach Anthropic for refresh, or (b) Anthropic revoked the token. | Re-run `claude setup-token` locally (fresh tokens), then re-upload. If that also fails, check network egress from ECS to api.anthropic.com. |
| `rc=3 HTTP 401` | Bearer token wrong, expired, or revoked | Mint a new one at `<ACE_URL>/settings`. |
| `rc=3 HTTP 404` | Endpoint not deployed (old image) | Check that the deploy landed: `gh run list --workflow=deploy-labs.yml --limit=1`. |

## Do NOT

- Do NOT try to run `claude setup-token` on the server — that path is
  intentionally deleted, see `docs/architecture/cli-credentials.md` §
  "What we deleted (and why)".
- Do NOT put the credential blob in a file that might be committed
  (e.g., don't dump to the repo root). The dry-run output redacts the
  tokens; only the live POST sends them.
- Do NOT put `ACE_TOKEN` or the blob contents into commit messages,
  chat logs, or issue descriptions.

## Success criterion

After the skill completes, `GET <ACE_URL>/api/auth/cli/status` returns
`authenticated: true` and the user can send a chat message at
`<ACE_URL>/chat` that streams back a real response.
