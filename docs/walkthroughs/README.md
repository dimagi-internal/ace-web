# Turmeric Smoke Walkthroughs

Repeatable end-to-end smoke tests for the ACE → Drive → ace-web flow against
prod (`labs.connect.dimagi.com/ace`). Two entry paths, one verify deck.

Spec: `docs/specs/2026-04-17-turmeric-smoke-walkthrough-design.md`.
Plan: `docs/plans/2026-04-17-turmeric-smoke-walkthrough.md`.

## What's verified

- Opp creation path works (wizard for web; `/ace:run` + `ace-upload` for CLI).
- Opp visible in `/opps` after setup.
- Workbench renders three-pane layout.
- Artifacts round-trip through Drive (PDD in, PDD out).
- "Discuss in chat" seeds a new chat session.

Cleanup is manual for now. After a run, delete the
`turmeric-smoketest-<stamp>` opp from ace-web's `/opps` UI (trash icon on
row hover). This also trashes the Drive folder. Opps accumulate otherwise
— each run generates a new timestamped slug.

## Prerequisites

- `ACE_E2E_AUTH_TOKEN` exported in the shell (value in
  `deploy/aws/task-definition.json`). This is the labs-prod automation
  token — it lets the setup scripts authenticate as `ace@dimagi-ai.com`
  via `/auth/e2e-login/` without touching OAuth or per-user personal tokens.
  See the "Automation auth on labs" bullet in the repo's CLAUDE.md.
- Turmeric PDD body at `/tmp/turmeric-smoketest/pdd.txt`. Easiest: ask
  the ACE plugin's Drive MCP for the latest file in the `Program Design
  Docs (PDDs)` folder under the ACE Drive root and redirect to that path.
- `claude` CLI on PATH and authenticated (CLI path only).
- `uv sync --extra walkthrough` to install Python Playwright (optional;
  the CLI path doesn't need it).

## Web path

```bash
python tools/walkthrough/turmeric_web_setup.py
# then in Claude Code:
/walkthrough turmeric
```

`turmeric_web_setup.py` creates a `turmeric-smoketest-<YYYYMMDD-HHMM>` opp
via the ace-web wizard, writes the slug to `/tmp/turmeric-smoketest-slug.txt`,
and exits 0 on success. Each run uses a fresh timestamped slug, so re-runs
don't collide — but leftover opps from prior runs accumulate in `/opps`
until you delete them manually.

## CLI path

```bash
export ACE_E2E_AUTH_TOKEN="<value from deploy/aws/task-definition.json>"
bash tools/walkthrough/turmeric_cli_setup.sh
# then in Claude Code:
/walkthrough turmeric
```

The CLI setup script:
1. POSTs `/auth/e2e-login/` as `ace@dimagi-ai.com` → session cookie in
   `/tmp/turmeric-smoketest/cookies.txt`
2. POSTs `/api/opps/` with the PDD body to create a fresh
   `turmeric-smoketest-<YYYYMMDD-HHMM>` opp
3. Runs `claude -p "/ace:run <slug> --dry-run --mode auto"` and writes
   the JSONL transcript
4. Uploads the transcript to `/api/ingest/upload` via the same session
   cookie (no personal token, no `ace-upload` CLI required)
5. Polls `/api/opps/<slug>` until Drive sync completes and writes the
   slug to `/tmp/turmeric-smoketest/slug.txt`

**Cost note:** `/ace:run --dry-run` still burns LLM tokens for the
orchestrator's planning + per-step dispatch. Budget a few dollars per run.

## Running the walkthrough deck

Inside a Claude Code session in the repo root:

```
/walkthrough turmeric
```

The skill reads `docs/walkthroughs/turmeric.yaml`, navigates through the
eight verification scenes, scores each one, and writes the HTML deck to
`screenshots/walkthroughs/turmeric.html`. The walkthrough does not delete
the opp — clean up manually after reviewing the deck.

## Troubleshooting

- **`ACE_E2E_AUTH_TOKEN not set`:** copy the value from
  `deploy/aws/task-definition.json` (or pull it from AWS Secrets Manager
  when rotated) and `export` it in your shell before invoking the script.
- **`e2e-login returned 403`:** the token you exported doesn't match the
  one deployed to labs — check for stale copies, spaces, or newlines.
- **`e2e-login returned 404`:** either the URL prefix is wrong
  (`$ACE_WEB_BASE_URL` should include `/ace`) or labs was redeployed
  with `ACE_E2E_AUTH_TOKEN` empty, which de-registers the route.
- **`/ace:run` hangs:** the Claude CLI session may have lost auth. Run
  `claude login` (or the Claude Code auth flow) and retry.
- **Leftover `turmeric-smoketest-*` opps:** delete from `/opps` via the
  trash icon on row hover, or delete the folder from Google Drive. Both
  paths are recoverable via Drive trash for 30 days.

## When to run this

- Before releasing a new ace-web or ACE plugin version.
- After infra migrations (DB, Drive credentials, OAuth provider).
- When a user reports "the workbench looks empty" to disambiguate
  rendering from upstream (Drive, ACE) problems.

Not suited for CI — LLM non-determinism + cost + prod-only dependencies.
