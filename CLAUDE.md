# CLAUDE.md — ace-web

Agent context for the ACE web harness. Read this at the start of every session.

`ace-web` is Module 1 of the ACE initiative: a browser-based chat harness that talks
to Claude via the local CLI (subscription auth) with multi-player drafts, persistent
transcripts, and upload support for existing local `.jsonl` sessions.

## Where things live

- **Architecture spec**: no unified web-harness spec file exists yet. Per-wave scope lives in `docs/plans/<date>-<plan>.md`. Pattern source for new code is `../canopy-web/` (sibling repo).
- **Implementation plans**: `docs/plans/`.
- **Deploy / GCP setup**: `docs/deploy.md`.
- **Learnings**: `docs/learnings/` (load-bearing gotchas — read these before touching the relevant area).

This repo is consumed as a git submodule from the `ace` repo. Day-to-day work on
ace-web happens in this repo directly, not through the `ace` worktree — working
through the submodule causes pointer churn.

## Current status

| Plan | Scope                                                     | Status                                    |
|------|-----------------------------------------------------------|-------------------------------------------|
| 1A   | Django + Channels + React skeleton, data model, IAP, GCP  | **Done** — merged in jjackson/ace-web#1   |
| 1B   | `ChatBackend` interface, CLIBackend, chat REST API, UI    | **Next**                                  |
| 1C   | WebSocket consumer, drafts, presence                      | Pending                                   |
| 1D   | Session list, share tokens, `ace upload` CLI              | Pending                                   |

Plan 1A's 25 post-execution corrections (security, races, Docker, deploy) are
documented inline at `docs/plans/2026-04-07-1a-foundation.md` under
**Post-execution corrections**. Read that section before touching config,
settings, Dockerfile, or the auth/sessions models.

## Stack

- **Backend**: Django 5 + Channels 4 + DRF, ASGI via uvicorn, `psycopg[binary]`, WhiteNoise, `django-environ`.
- **Frontend**: React 19, Vite 5, TypeScript 5, Tailwind 3.4, react-router-dom 6.
- **DB**: PostgreSQL 16 (Cloud SQL in prod, local Postgres via `docker compose`).
- **Infra**: GCP Cloud Run behind IAP + Google SSO, Cloud Build, Secret Manager, Artifact Registry.
- **Tests**: pytest + pytest-django + pytest-asyncio, in-memory SQLite for unit tests.
- **Patterns source**: `../canopy-web/` — copy structure for auth flows, envelope, settings layout, Dockerfile, entrypoint.

## Project structure

```
ace-web/
├── apps/
│   ├── auth/        # Custom User, IAP header middleware    (10 files)
│   ├── common/      # Envelope, health check                (4 files)
│   └── sessions/    # 7-table data model                    (4 files)
├── config/          # Split settings, ASGI, urls, routing
├── frontend/        # React 19 + Vite shell                 (6 src files)
├── tests/           # Project-level tests (asgi smoke)
├── docs/
│   ├── deploy.md
│   ├── learnings/
│   └── plans/2026-04-07-1a-foundation.md
├── Dockerfile, entrypoint.sh, docker-compose.yml
├── cloudbuild.yaml
└── pyproject.toml
```

10 source Python files under `apps/`, 5 `test_*.py` files, 6 frontend TS/TSX files.

The sessions data model has 7 tables: `users`, `sessions`, `session_participants`,
`messages`, `drafts`, `share_tokens`, `ingest_uploads`. All migrated in Plan 1A.

## Key architectural decisions

- **Auth via IAP**: GCP IAP is the edge. `apps.auth.middleware.IAPHeaderAuthMiddleware` reads
  `X-Goog-Authenticated-User-Email` and `X-Goog-Authenticated-User-ID` and populates
  `request.user`. `AUTH_USER_MODEL = "ace_auth.User"`. In dev, IAP is faked via
  `ACE_IAP_REQUIRED=False` and `ACE_IAP_DEV_FAKE_EMAIL`.
- **Response envelope**: Every JSON response uses `{data, error}` via
  `apps.common.envelope.success_response` / `error_response`. See
  `docs/learnings/api-envelope-convention.md`.
- **Health check is IAP-exempt at Django, not at IAP**: `/api/health` is
  middleware-exempt inside Django but still sits behind IAP at the GCP edge.
  Smoke tests must pass an identity token. See `docs/deploy.md`.
- **Single Cloud Run instance**: `min-instances=1 max-instances=1` until Channels
  switches off `InMemoryChannelLayer`. See `docs/learnings/channels-single-instance.md`.

## Learnings (read before touching the relevant area)

Infra & scaling:
- [channels-single-instance](docs/learnings/channels-single-instance.md) — `InMemoryChannelLayer` pins Cloud Run to a single instance; Plan 1C must add `channels-redis` before scaling.

Auth & identity:
- [iap-websocket-coverage](docs/learnings/iap-websocket-coverage.md) — IAP middleware is HTTP-only; Plan 1C must add ASGI-scope auth for WebSocket handshakes.
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`) and first-login races must be handled at the DB layer.

API conventions:
- [api-envelope-convention](docs/learnings/api-envelope-convention.md) — every JSON response wraps in `{data, error}`; no bare payloads, no DRF default errors.

For the full Plan 1A post-execution fix list (25 items including settings hardening,
Dockerfile slimming, SPA catch-all, slug retries, setuptools layout), see the
`## Post-execution corrections` section of `docs/plans/2026-04-07-1a-foundation.md`.

## Workflow

- **Local dev**: `docker compose up`. App at `http://localhost:8000`, Postgres at `localhost:5434`.
- **Tests**: `pytest -v` from repo root. Uses in-memory SQLite; fast hashers.
- **Lint**: `ruff check .` — `line-length=100`, `target=py311`, rules `E,F,W,I,UP,B`.
- **Deploy**: `gcloud builds submit --config=cloudbuild.yaml`. One-time GCP setup in `docs/deploy.md`.
- **Plans-driven work**: Implementation follows the plan file for the current module.
  Plan 1B will live at `docs/plans/<date>-1b-<slug>.md`. Use the superpowers
  `subagent-driven-development` or `executing-plans` sub-skill as the plan specifies.

## What does NOT ship yet

- No `ChatBackend` interface, no Claude CLI integration, no chat REST API or UI — Plan 1B.
- No WebSocket consumer, no drafts, no presence — Plan 1C.
- No session list, share tokens, or `ace upload` CLI — Plan 1D.
- No `CLAUDE_CODE_OAUTH_TOKEN` handling — lands with CLIBackend in Plan 1B.
