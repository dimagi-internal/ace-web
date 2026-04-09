# CLAUDE.md — ace-web

Agent context for the ACE web harness. Read this at the start of every session.

`ace-web` is Module 1 of the ACE initiative: a browser-based chat harness that talks
to Claude via the local CLI (subscription auth) with multi-player drafts, persistent
transcripts, and upload support for existing local `.jsonl` sessions.

## Where things live

- **Design spec** (the whole vision and phase breakdown): `docs/specs/2026-04-08-ace-web-design.md`.
- **Implementation plans** (per phase): `docs/plans/`.
- **Pattern source** for new backend code: `../canopy-web/` (sibling repo).
- **Deploy / AWS setup**: `docs/deploy.md`.
- **Learnings**: `docs/learnings/` (load-bearing gotchas — read these before touching the relevant area).

The broader ACE plugin (CRISPR-Connect orchestration) lives in the sibling
`ace` repo at `../ace/`. ace-web is a separate module — its design spec lives
here, not there. This repo is consumed as a git submodule from `ace`, but
day-to-day work happens in this repo directly to avoid submodule pointer churn.

## Current status

The whole-product design is in `docs/specs/2026-04-08-ace-web-design.md`.
Phases below come from that spec — they are engineering execution checkpoints,
not user-shippable milestones (the team only uses ace-web after Phase 5).

| Phase | Name                       | Scope                                                                           | Status                                    |
|-------|----------------------------|---------------------------------------------------------------------------------|-------------------------------------------|
| 1     | Foundation                 | Django + Channels + React skeleton, data model, IAP, GCP                        | **Done** — merged in jjackson/ace-web#1   |
| 2     | Conversation engine        | ChatBackend, CLIBackend, CLI auth (PTY), SSE streaming, REST + chat UI, recents | **Done**                                  |
| 2.5   | AWS migration              | GCP → AWS ECS Fargate tenant, CommCare Connect OAuth, nginx sidecar, /ace/* prefix | **Done** — per `docs/plans/2026-04-08-aws-migration.md` |
| 3     | Multi-player collaboration | WebSocket consumer, channels-redis, ASGI auth, drafts, presence                 | Pending                                   |
| 4     | Library and ingest         | Session list, search/filter, share tokens, `ace upload` CLI                     | Pending                                   |
| 5     | Polish                     | Observability, evals, accessibility, security review, demo prep, full docs     | Pending                                   |

Phase 1's 25 post-execution corrections (security, races, Docker, deploy) are
documented inline at `docs/plans/2026-04-07-1a-foundation.md` under
**Post-execution corrections**. Read that section before touching config,
settings, Dockerfile, or the auth/sessions models.

## Stack

- **Backend**: Django 5 + Channels 4 + DRF, ASGI via uvicorn, `psycopg[binary]`, `httpx[http2]` for Connect OAuth, `django-environ`.
- **Frontend**: React 19, Vite 5, TypeScript 5, Tailwind 3.4, react-router-dom 6. Served via nginx sidecar container in prod, built with bun.
- **DB**: PostgreSQL (shared AWS RDS `labs-*` instance, database `ace_web`; local Postgres via `docker compose`).
- **Infra**: AWS ECS Fargate (cluster `labs-jj-cluster`, us-east-1) behind the shared connect-labs ALB (path prefix `/ace/*`). GitHub Actions with OIDC for deploys. AWS Secrets Manager for secrets. ECR for images.
- **Tests**: pytest + pytest-django + pytest-asyncio, in-memory SQLite for unit tests.
- **Pattern sources**: `../connect-labs/` (CommCare Connect OAuth pattern), `../scout-jjackson/` (two-container ECS deploy pattern), `../canopy-web/` (CLI backend + PTY auth flow).

## Project structure

```
ace-web/
├── apps/
│   ├── auth/        # Custom User model                     (10 files)
│   ├── common/      # Envelope, health check                (4 files)
│   ├── opps/        # ACE opp Workbench (Drive-backed)     (new)
│   └── sessions/    # 7-table data model                    (4 files)
├── config/          # Split settings, ASGI, urls, routing
├── frontend/        # React 19 + Vite shell                 (6 src files)
├── tests/           # Project-level tests (asgi smoke)
├── docs/
│   ├── deploy.md
│   ├── learnings/
│   └── plans/2026-04-07-1a-foundation.md
├── Dockerfile, Dockerfile.frontend, docker-compose.yml
├── frontend/nginx.prod.conf   # nginx sidecar config for the prod container
├── deploy/aws/                # task-definition.json + one-time-setup.sh
├── .github/workflows/deploy-labs.yml   # AWS ECS deploy pipeline
└── pyproject.toml
```

10 source Python files under `apps/`, 5 `test_*.py` files, 6 frontend TS/TSX files.

The sessions data model has 7 tables: `users`, `sessions`, `session_participants`,
`messages`, `drafts`, `share_tokens`, `ingest_uploads`. All migrated in Plan 1A.

## Key architectural decisions

- **Auth**: CommCare Connect OAuth with PKCE, `@dimagi.com` email filter enforced at the callback. Hand-rolled session-based flow ported from connect-labs (NOT django-allauth). Implementation in `apps/auth/oauth_views.py` + `apps/auth/oauth.py`. Tenant-unique session cookies (`sessionid_ace`, `csrftoken_ace`) and path-scoped (`/ace/`) to avoid collisions with scout on the shared `labs.connect.dimagi.com` host. `AUTH_USER_MODEL = "ace_auth.User"`; the `google_sub` field is a legacy no-op kept to avoid a schema migration.
- **Response envelope**: Every JSON response uses `{data, error}` via
  `apps.common.envelope.success_response` / `error_response`. See
  `docs/learnings/api-envelope-convention.md`.
- **Health check**: `/api/health` is public. See `docs/deploy.md`.
- **Single ECS task**: Run only one ECS Fargate task until Channels switches off
  `InMemoryChannelLayer`. See `docs/learnings/channels-single-instance.md`.

## Learnings (read before touching the relevant area)

Infra & scaling:
- [channels-single-instance](docs/learnings/channels-single-instance.md) — `InMemoryChannelLayer` pins to a single ECS task; Plan 1C must add `channels-redis` (shared ElastiCache) before scaling.

Auth & identity:
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`) and first-login races must be handled at the DB layer.

API conventions:
- [api-envelope-convention](docs/learnings/api-envelope-convention.md) — every JSON response wraps in `{data, error}`; no bare payloads, no DRF default errors.

Conversation engine (Phase 2):
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.
- [sse-django-async](docs/learnings/sse-django-async.md) — `Cache-Control`/`X-Accel-Buffering` headers, `sync_to_async` ORM access, async cleanup with `asyncio.shield`, and concurrent-write serialization with `select_for_update` are mandatory for SSE views.

Deploy & infrastructure:
- [aws-migration](docs/plans/2026-04-08-aws-migration.md) — completed migration from standalone GCP Cloud Run to AWS ECS Fargate as a connect-labs shared-infrastructure tenant. IAP auth swapped for CommCare Connect OAuth. Filestore dropped in favor of the CLIBackend hybrid-resume Django-replay path. Two-container ECS task (Django + nginx sidecar). Shared RDS, ALB, and (Phase 3) ElastiCache reduce incremental cost to ~$5-15/month.

For the full Phase 1 post-execution fix list (25 items including settings hardening,
Dockerfile slimming, SPA catch-all, slug retries, setuptools layout), see the
`## Post-execution corrections` section of `docs/plans/2026-04-07-1a-foundation.md`.

## ACE opportunity visualization (apps/opps)

The `apps/opps/` module is the ACE opportunity Workbench — a read-through UI
on top of Google Drive that shows all 19 skills of an ACE run, per-step
artifact previews, judge verdicts, gate history, and a "Discuss in chat"
CTA that seeds a new ace-web `Session` from a step's context.

Google Drive is the source of truth. There are no Django ORM models for
opps / runs / steps / artifacts — the data lives as `opp.yaml` / `run.yaml` /
`step.yaml` / `judge.yaml` / `gates.jsonl` / `events.jsonl` files under
`ACE/<opp-slug>/` in Drive. See
`docs/specs/2026-04-08-ace-opp-visualization-design.md` § 6 for the full
folder format.

**Coordination with the ACE plugin:** The Drive folder format in the spec
above is a proposal that the ACE plugin (`../ace`) needs to adopt for
first-class multi-run support. ace-web ships with a flat-layout fallback
that reads the current `ACE/<opp>/state.yaml` + subfolder convention as a
single implicit run, so both formats work during the transition.

**Two OAuth flows:** identity via a hand-rolled CommCare Connect OAuth
flow with PKCE (`apps/auth/oauth_views.py`, pattern from connect-labs);
Drive access via a separate Google OAuth grant per-user. See
`docs/learnings/drive-oauth-two-flow.md`.

**Key files:**
- `apps/opps/sync.py` — Drive-to-payload reader (structured + flat layouts)
- `apps/opps/previews.py` — 19 per-skill preview extractors
- `apps/opps/seed.py` — chat-seed builder for "Discuss in chat"
- `apps/opps/drive_client.py` — DriveClient ABC + GoogleDriveClient
- `apps/opps/skills.py` — canonical 19-skill metadata (phase/judge/gate/ordinal)
- `frontend/src/pages/OppWorkbenchPage.tsx` — the three-pane UI shell

## Workflow

- **Local dev**: `docker compose up`. App at `http://localhost:8000`, Postgres at `localhost:5434`.
- **Tests**: `pytest -v` from repo root. Uses in-memory SQLite; fast hashers.
- **Lint**: `ruff check .` — `line-length=100`, `target=py311`, rules `E,F,W,I,UP,B`.
- **Deploy**: GitHub Actions workflow `.github/workflows/deploy-labs.yml`. Manual trigger (Actions → Deploy to Labs (AWS) → Run workflow). Set `run_migrations: true` on schema-changing deploys. First-time setup: `deploy/aws/one-time-setup.sh`. See `docs/deploy.md` for the full runbook.
- **Plans-driven work**: Implementation follows the per-phase plan file in `docs/plans/`.
  Each phase plan is generated from the design spec via the `writing-plans` skill.
  Use the superpowers `subagent-driven-development` or `executing-plans` sub-skill
  to execute it, as the plan specifies.

## What does NOT ship yet

- No WebSocket consumer, no drafts, no presence, no channels-redis — Phase 3.
- No session list, share tokens, or `ace upload` CLI — Phase 4.
- No observability, no eval harness, no security review — Phase 5.

See `docs/specs/2026-04-08-ace-web-design.md` for the full vision and what
each phase covers.
