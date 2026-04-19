# Turmeric Walkthroughs

Repeatable end-to-end tours of the ACE → Drive → ace-web flow against prod
(`labs.connect.dimagi.com/ace`). Two specs for two different jobs:

| Spec | Scenes | Setup | Use when |
|------|--------|-------|----------|
| `turmeric-step1-web` | 4 | `turmeric_cli_setup.sh` (dry-run, ~2 min, ~$1) | Smoke-test the ace-web tier after a deploy |
| `turmeric-end-to-end` | 5 | Manual `/ace:run` without `--dry-run` (20–60 min, significant tokens) | Tour a real populated lifecycle for demos or post-run review |

Spec: `docs/specs/2026-04-17-turmeric-smoke-walkthrough-design.md`.
Plan: `docs/plans/2026-04-17-turmeric-smoke-walkthrough.md`.

## `turmeric-step1-web` — web-tier smoke test

Four scenes, web-tier only. The setup path runs `/ace:run --dry-run`, which
seeds only Phase 1 (`idea-to-pdd`) with a real PDD and leaves the other 18
skills pending. The walkthrough therefore exercises just the four pieces of
plumbing that are actually load-bearing for a smoke test:

1. **Opp appears in the list** — opp create → Drive folder → list read-through
2. **Workbench three-pane renders** — Drive sync, WebSocket auth, 19-skill sidebar (with 18 pending-state rows in one view), chat pane mount
3. **Drive artifact round-trips** — `idea-to-pdd` detail pane fetches `pdd.md` from Drive via the ace-web API and renders it verbatim
4. **Opps → chat bridge** — "Discuss in chat" seeds a new `/chat/<slug>` session with the step context

Earlier revisions had 8 scenes (per-phase clicks on `pdd-to-learn-app`,
`ocs-agent-setup`, `cycle-grade`, and a duplicate `pdd.md` re-click). Those
were dropped because they captured identical pending-state screenshots that
Scene 2 already covers via the sidebar — no new plumbing was under test.

## `turmeric-end-to-end` — populated-lifecycle tour

Five scenes across a real run. Prerequisite: the opp's lifecycle has
actually executed (no `--dry-run`), so phases 1–4 carry real artifacts
plus judge verdicts. Picks the most interesting step per lifecycle
stage rather than re-capturing all 19 skills:

1. **Opp list shows lifecycle progress** — same list view, but the Turmeric card now sits atop a populated pipeline
2. **19-skill lifecycle — real progress, not stubs** — workbench landing with ≥6 ✓ marks + judge bars rendering scores
3. **ACE calls Nova — pdd-to-learn-app** — cross-system artifact: the CommCare Learn app that ACE generated via Nova, with judge verdict
4. **Evaluation loop — app-test judge verdict** — structured test results + judge score + rationale, proves the feedback loop
5. **Cycle grade — closeout** — the closeout artifact that feeds learnings-summary into the next PDD

Skipped deliberately: the "no judge" skills and Phase 5 (LLO management,
which sends real emails). The workbench-overview scene captures their
status at a glance via the sidebar.

**Setup:** see the comment block at the top of `turmeric-end-to-end.yaml`.
Shortest safe path is `turmeric_cli_setup.sh` → drive a real `/ace:run
<slug> --mode auto` → stop at Phase 4 → `/walkthrough turmeric-end-to-end`.

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
/walkthrough turmeric-step1-web
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
/walkthrough turmeric-step1-web
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
/walkthrough turmeric-step1-web
```

The skill reads `docs/walkthroughs/turmeric-step1-web.yaml`, navigates
through the four verification scenes, scores each one, and writes the HTML
deck to `screenshots/walkthroughs/turmeric-step1-web.html`. The walkthrough
does not delete the opp — clean up manually after reviewing the deck.

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
