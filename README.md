# ace-web

Browser-based workbench for the ACE (CRISPR-Connect) initiative.

ace-web is the web companion to the [`ace` Claude Code plugin](../ace/). It
gives a Dimagi team or third-party LLO a place to:

- See every ACE opportunity in their workspace, with per-skill artifacts,
  judge verdicts, gates, and run-level scorecards (the **Workbench**).
- Talk to Claude in a multi-player chat that's wired to the same context
  (multi-player drafts, persistent transcripts, transcript ingest from
  local `.jsonl` files).
- Onboard a new workspace by pointing at a Google Drive folder — no CLI
  required for the day-to-day inspection loop.

Drive is the source of truth: opps live as files under `ACE/<opp-slug>/`
in a workspace's Drive folder; ace-web reads through to them via a shared
service account.

## Status

- **Initial development complete (2026-04-21).** Phases 1-4 shipped.
  Phase 5 ("Polish": observability, evals, a11y, security review) was
  reviewed and **deferred indefinitely** — revisit only when a concrete
  pain point shows up.
- **Multi-tenant Workspaces shipped (2026-04-27).** The hard-coded
  `ACE_DRIVE_ROOT_FOLDER_ID` is now migration-only; each workspace owns
  its own Drive folder + member list (Owner / Editor / Viewer), with
  self-onboarding at `/welcome` and invite-by-email at `/invite/<token>`.

For a phase-by-phase status table and the canonical map of where things
live, see [`CLAUDE.md`](./CLAUDE.md). For the whole-product vision and
the engineering execution plan it phases into, see
[`docs/specs/2026-04-08-ace-web-design.md`](./docs/specs/2026-04-08-ace-web-design.md).

## Where things live

- **Design spec** (the whole vision): `docs/specs/2026-04-08-ace-web-design.md`
- **Implementation plans** (per phase): `docs/plans/`
- **Learnings** (load-bearing gotchas — read before touching the relevant
  area): `docs/learnings/`
- **Architecture notes**: `docs/architecture/`
- **Deploy runbook**: `docs/deploy.md`
- **Agent context** (what every Claude session reads first): `CLAUDE.md`

The broader ACE plugin (CRISPR-Connect orchestration) lives in the
sibling `ace` repo at `../ace/`. ace-web is a separate module — its
design spec lives here, not there. This repo is consumed as a git
submodule from `ace`, but day-to-day work happens in this repo
directly to avoid submodule pointer churn.

## Quick start (local dev)

```bash
docker compose up
```

Then open http://localhost:8000.

### Trying it out — no credentials needed

The dev container ships with two escape hatches enabled
(`ACE_ALLOW_TEST_LOGIN=True`, `ACE_USE_FAKE_CLI_BACKEND=True` — both
set automatically by `config/settings/development.py`):

1. On the sign-in page, use the **"Sign in as test user"** form at the
   bottom — type any email, get logged in. No CommCare Connect OAuth
   credentials required.
2. Land on `/welcome` and create a workspace. You'll need a Google Drive
   folder shared with the configured service account if you want Drive
   features to work; otherwise opps will be empty.
3. Try chat — it'll respond with deterministic test text via the
   `FakeCLIBackend` until you wire up real claude CLI credentials (see
   `docs/architecture/cli-credentials.md`).

That's enough to click around and understand the surface area. To use
ACE for real, configure CommCare Connect OAuth (`CONNECT_OAUTH_CLIENT_ID`
+ `CONNECT_OAUTH_CLIENT_SECRET` in `.env`), point a workspace at a real
Drive folder shared with the service account, and upload claude CLI
credentials via `/ace-web:create-cli-credentials`.

## Stack

- **Backend**: Django 5 + Channels 4 + DRF, ASGI via uvicorn
- **Frontend**: React 19 + Vite + TypeScript + Tailwind + shadcn/ui
- **Data**: PostgreSQL (AWS RDS in prod, local Postgres via docker compose)
- **Realtime**: WebSocket-only (`SessionConsumer`), channels-redis backed
  by ElastiCache in prod
- **Drive access**: shared Google service account, key in AWS Secrets
  Manager (`ACE_DRIVE_SA_KEY_JSON`)
- **Claude**: local Claude CLI subprocess (`apps/common/CLIBackend`),
  subscription credential blob in `SystemConfig`

## Deploy

ace-web runs on AWS ECS Fargate as a tenant of the connect-labs shared
infrastructure (cluster `labs-jj-cluster`, ALB path prefix `/ace/*`).
Manual deploy:

```bash
gh workflow run deploy-labs.yml --ref main -f run_migrations=true
```

See [`docs/deploy.md`](./docs/deploy.md) for the full runbook (image
build, secrets, rollbacks, first-time setup).

## Tests

```bash
pytest -v        # backend
bunx tsc -b      # frontend type check
ruff check .     # lint
```
