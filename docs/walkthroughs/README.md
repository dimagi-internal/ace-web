# Turmeric Walkthroughs

Repeatable end-to-end tours of the ACE → Drive → ace-web flow against prod
(`labs.connect.dimagi.com/ace`). Two specs for two different jobs:

| Spec | Scenes | Setup | Use when |
|------|--------|-------|----------|
| `turmeric-step1-web` | 4 | `/ace:run <slug> --dry-run --idea <pdd-file> --ace-web-url <url>` (~2 min, ~$1) | Smoke-test the ace-web tier after a deploy |
| `turmeric-end-to-end` | 5 | Same recipe without `--dry-run` (20–60 min, significant tokens) | Tour a real populated lifecycle for demos or post-run review |

Spec: `docs/specs/2026-04-17-turmeric-smoke-walkthrough-design.md`.
Plan: `docs/plans/2026-04-17-turmeric-smoke-walkthrough.md`.

## `turmeric-step1-web` — web-tier smoke test

Four scenes, web-tier only. The setup path runs `/ace:run --dry-run`, which
seeds only Phase 1 (`idea-to-pdd`) with a real PDD and leaves the other 21
skills pending. The walkthrough therefore exercises just the four pieces of
plumbing that are actually load-bearing for a smoke test:

1. **Opp appears in the list** — opp create → Drive folder → list read-through
2. **Workbench three-pane renders** — Drive sync, opps list + 22-skill lifecycle sidebar (with 21 pending-state rows in one view) + empty-state detail pane
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
stage rather than re-capturing all 22 skills:

1. **Opp list shows lifecycle progress** — same list view, but the Turmeric card now sits atop a populated pipeline
2. **22-skill lifecycle — real progress, not stubs** — workbench landing with ≥6 ✓ marks + judge bars rendering scores
3. **ACE calls Nova — pdd-to-learn-app** — cross-system artifact: the CommCare Learn app that ACE generated via Nova, with judge verdict
4. **Evaluation loop — app-test judge verdict** — structured test results + judge score + rationale, proves the feedback loop
5. **Cycle grade — closeout** — the closeout artifact that feeds learnings-summary into the next PDD

Skipped deliberately: the "no judge" skills and Phase 5 (LLO management,
which sends real emails). The workbench-overview scene captures their
status at a glance via the sidebar.

**Setup:** see the comment block at the top of `turmeric-end-to-end.yaml`.
Shortest safe path is `turmeric_pdd_finder.py` → `/ace:run <slug> --mode
auto --idea <pdd-file> --ace-web-url <url>` → stop at Phase 4 (interrupt
or cap scope to avoid Phase 5's real emails) → `/walkthrough
turmeric-end-to-end`.

Cleanup is manual for now. After a run, delete the
`turmeric-smoketest-<stamp>` opp from ace-web's `/opps` UI (trash icon on
row hover). This also trashes the Drive folder. Opps accumulate otherwise
— each run generates a new timestamped slug.

## Prerequisites

- `ACE_WEB_PAT_TOKEN` exported in the shell. Mint via
  `/ace:ace-web-pat-mint` (one-time gh-style loopback browser flow).
  The PAT belongs to *you* — chat sessions, opps, and uploads attribute
  back to the authorizing human, not a shared bot identity. See the
  "Automation auth on labs" bullet in the repo's CLAUDE.md.
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
# 1. Fetch the Turmeric PDD to a local file
mkdir -p /tmp/turmeric-smoketest
python tools/walkthrough/turmeric_pdd_finder.py > /tmp/turmeric-smoketest/pdd.txt

# 2. Run /ace:run with the new scripted flags (ACE plugin >= 0.5.0).
#    --idea seeds idea.md from the PDD file, skipping AskUserQuestion.
#    --ace-web-url uploads the transcript to /api/ingest/upload after
#    the run via the upload-transcript skill (Bearer PAT auth).
SLUG="turmeric-smoketest-$(date +%Y%m%d-%H%M)"
# Mint a PAT via /ace:ace-web-pat-mint if you don't have one yet.

claude -p "/ace:run $SLUG --mode auto --dry-run \
           --idea /tmp/turmeric-smoketest/pdd.txt \
           --ace-web-url https://labs.connect.dimagi.com/ace" \
  --output-format stream-json --verbose \
  > /tmp/turmeric-smoketest/transcript-$SLUG.jsonl

# 3. Persist the slug so the step1-web walkthrough can find it
echo "$SLUG" > /tmp/turmeric-smoketest/slug.txt

# 4. In Claude Code:
/walkthrough turmeric-step1-web
```

What `/ace:run` now handles natively (replacing the deleted
`turmeric_cli_setup.sh`):
1. Creates the `ACE/<slug>/` Drive folder (flat layout; ACE plugin
   owns state.yaml).
2. Seeds `idea.md` from `--idea /path/to/file` — no interactive prompt.
3. Dispatches the `ace-orchestrator` agent through Phase 1.
4. On completion, dispatches the `upload-transcript` skill (from the
   ACE plugin) which POSTs to `/api/ingest/upload` with
   `Authorization: Bearer $ACE_WEB_PAT_TOKEN`.

ace-web's `/opps` list picks up the new Drive folder automatically;
the `OppWorkspace` DB row materializes lazily on first view (e.g.
when you click into `/opps/<slug>`).

**Cost note:** `/ace:run --dry-run` still burns LLM tokens for the
orchestrator's planning + per-step dispatch. Budget a few dollars per
run. For the **real** (non-`--dry-run`) path that powers the
`turmeric-end-to-end` walkthrough, drop `--dry-run` and plan for a
20–60 minute run that burns significantly more tokens (Nova calls
for Learn/Deliver apps, app-test evaluation loop, OCS agent clone).

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

- **`ACE_WEB_PAT_TOKEN not set`:** mint a PAT via
  `/ace:ace-web-pat-mint` (one-time gh-style loopback browser flow) and
  `export` it before invoking the script. The token lands in
  `$CLAUDE_PLUGIN_DATA/.env` automatically.
- **HTTP 401 from ingest/upload:** the PAT was revoked or never minted.
  Re-mint via `/ace:ace-web-pat-mint` and retry.
- **URL prefix wrong:** `$ACE_WEB_BASE_URL` should include `/ace`
  (e.g. `https://labs.connect.dimagi.com/ace`).
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
