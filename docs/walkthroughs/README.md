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
- Delete-opp teardown leaves Drive + DB clean.

## Prerequisites

- Logged-in Dimagi Google identity in a browser (for Drive + ace-web OAuth).
- `~/.ace/config.toml` with the `ace-upload` personal token and server URL.
  Generate the token from ace-web's Settings page.
- `claude` CLI on PATH and authenticated (CLI path only).
- `uv sync --extra walkthrough` to install Python Playwright (web path only).
- Persistent Playwright profile at `~/.ace/playwright-profile/`. First run of
  `turmeric_web_setup.py` opens a visible browser — complete OAuth there;
  subsequent runs reuse the cookies.

## Web path

```bash
python tools/walkthrough/turmeric_web_setup.py
# then in Claude Code:
/walkthrough turmeric
```

`turmeric_web_setup.py` creates a `turmeric-smoketest-<YYYYMMDD-HHMM>` opp
via the ace-web wizard, writes the slug to `/tmp/turmeric-smoketest-slug.txt`,
and exits 0 on success.

Flags:
- `--force-cleanup` — delete any leftover `turmeric-smoketest-*` opps before
  creating a new one. Use this when prior runs aborted mid-deck.

## CLI path

```bash
bash tools/walkthrough/turmeric_cli_setup.sh
# then in Claude Code:
/walkthrough turmeric
```

The CLI setup script creates the opp via the API, runs
`claude -p "/ace:run <slug> --dry-run --mode auto"`, captures the JSONL
transcript, and uploads it with `ace-upload`.

**Cost note:** `/ace:run --dry-run` still burns LLM tokens for the
orchestrator's planning + per-step dispatch. Budget a few dollars per run.

## Running the walkthrough deck

Inside a Claude Code session in the repo root:

```
/walkthrough turmeric
```

The skill reads `docs/walkthroughs/turmeric.yaml`, navigates through the
nine scenes, scores each one, and writes the HTML deck to
`screenshots/walkthroughs/turmeric.html`. The final scene tears down the
opp via the new DELETE endpoint.

## Troubleshooting

- **First Playwright run asks for OAuth:** complete login in the visible
  browser window and let it close. The persistent profile now has cookies
  for subsequent runs.
- **`/ace:run` hangs:** the Claude CLI session may have lost auth. Run
  `claude login` (or the Claude Code auth flow) and retry.
- **`ace-upload: Config not found`:** run `ace-upload --configure` and paste
  a personal token from ace-web's Settings page.
- **Leftover `turmeric-smoketest-*` opps:** either rerun setup with
  `--force-cleanup` (web) or delete manually from the UI.
- **Walkthrough scene 9 fails (delete button not found):** confirm the
  delete-opp UI shipped in this plan's Tasks 7–8.

## When to run this

- Before releasing a new ace-web or ACE plugin version.
- After infra migrations (DB, Drive credentials, OAuth provider).
- When a user reports "the workbench looks empty" to disambiguate
  rendering from upstream (Drive, ACE) problems.

Not suited for CI — LLM non-determinism + cost + prod-only dependencies.
