---
description: Upload this laptop's claude CLI credentials to a deployed ace-web so the server can use the subscription for chat. Usage: /create-cli-credentials [url]
argument-hint: [ace-web URL, default https://labs.connect.dimagi.com/ace]
---

Invoke the `create-cli-credentials` skill to ship this laptop's local
claude CLI credential blob to the deployed ace-web instance at
`$ARGUMENTS` (default `https://labs.connect.dimagi.com/ace`).

Follow the skill's steps exactly:
1. Dry-run `scripts/ace_cli_login.py` to confirm local credentials are
   present. If not, stop and instruct the user to run `claude setup-token`.
2. Confirm the target URL (ask if ambiguous).
3. Ask the user for a personal bearer token from `<URL>/settings` — give
   them the full clickable URL. Do NOT proceed without it.
4. Run the uploader with `ACE_URL` and `ACE_TOKEN`.
5. Report the exit code and server-confirmed `authenticated` status.
6. On success, fetch `<URL>/api/auth/cli/status` and show the result.

Full procedure + failure modes: see
`.claude/skills/create-cli-credentials/SKILL.md` and
`docs/architecture/cli-credentials.md`.
