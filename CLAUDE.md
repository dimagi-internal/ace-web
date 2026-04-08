# CLAUDE.md — ace-web

Agent context for the ACE web harness. Read this at the start of every session.

`ace-web` is Module 1 of the ACE initiative: a browser-based chat harness that talks
to Claude via the local CLI (subscription auth) with multi-player drafts, persistent
transcripts, and upload support for existing local `.jsonl` sessions.

## Where things live

- **Design spec** (the whole vision and phase breakdown): `docs/specs/2026-04-08-ace-web-design.md`.
- **Implementation plans** (per phase): `docs/plans/`.
- **Pattern source** for new backend code: `../canopy-web/` (sibling repo).
- **Deploy / GCP setup**: `docs/deploy.md`.
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
| 3     | Multi-player collaboration | WebSocket consumer, channels-redis, ASGI auth, drafts, presence                 | Pending                                   |
| 4     | Library and ingest         | Session list, search/filter, share tokens, `ace upload` CLI                     | Pending                                   |
| 5     | Polish                     | Observability, evals, accessibility, security review, demo prep, full docs     | Pending                                   |

Phase 1's 25 post-execution corrections (security, races, Docker, deploy) are
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
- [iap-websocket-coverage](docs/learnings/iap-websocket-coverage.md) — IAP middleware is HTTP-only; Phase 3 must add ASGI-scope auth for WebSocket handshakes.
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`) and first-login races must be handled at the DB layer.

API conventions:
- [api-envelope-convention](docs/learnings/api-envelope-convention.md) — every JSON response wraps in `{data, error}`; no bare payloads, no DRF default errors.

Conversation engine (Phase 2):
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.
- [sse-django-async](docs/learnings/sse-django-async.md) — `Cache-Control`/`X-Accel-Buffering` headers, `sync_to_async` ORM access, async cleanup with `asyncio.shield`, and concurrent-write serialization with `select_for_update` are mandatory for SSE views.

For the full Phase 1 post-execution fix list (25 items including settings hardening,
Dockerfile slimming, SPA catch-all, slug retries, setuptools layout), see the
`## Post-execution corrections` section of `docs/plans/2026-04-07-1a-foundation.md`.

## Workflow

- **Local dev**: `docker compose up`. App at `http://localhost:8000`, Postgres at `localhost:5434`.
- **Tests**: `pytest -v` from repo root. Uses in-memory SQLite; fast hashers.
- **Lint**: `ruff check .` — `line-length=100`, `target=py311`, rules `E,F,W,I,UP,B`.
- **Deploy**: `gcloud builds submit --config=cloudbuild.yaml`. One-time GCP setup in `docs/deploy.md`.
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
