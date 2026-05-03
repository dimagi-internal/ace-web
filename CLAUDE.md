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
- **Architecture docs**: `docs/architecture/` (e.g. `cli-credentials.md` for the laptop→server credential upload flow).
- **Project skills** (`.claude/skills/ace-web/`) and **commands** (`.claude/commands/ace-web/`) — repo-local Claude Code helpers, namespaced under `ace-web:`. Notably `ace-web:create-cli-credentials` / `/ace-web:create-cli-credentials` to ship local claude CLI auth up to a deployed instance.

The broader ACE plugin (CRISPR-Connect orchestration) lives in the sibling
`ace` repo at `../ace/`. ace-web is a separate module — its design spec lives
here, not there. This repo is consumed as a git submodule from `ace`, but
day-to-day work happens in this repo directly to avoid submodule pointer churn.

## Current status

**Initial development is complete as of 2026-04-21.** Phases 1 through 4 have
all shipped; Phase 5 ("Polish") is **deferred indefinitely** — we reviewed the
scope (observability, evals, a11y, security review, demo prep, docs pass) and
decided the concrete value didn't justify the work at this stage. Revisit if
a specific pain point surfaces in real team use, but do not plan it as
proactive work.

The whole-product design is in `docs/specs/2026-04-08-ace-web-design.md`.
Phases below come from that spec — they are engineering execution checkpoints,
not user-shippable milestones.

| Phase | Name                       | Scope                                                                           | Status                                    |
|-------|----------------------------|---------------------------------------------------------------------------------|-------------------------------------------|
| 1     | Foundation                 | Django + Channels + React skeleton, data model, IAP, GCP                        | **Done** — merged in jjackson/ace-web#1   |
| 2     | Conversation engine        | ChatBackend, CLIBackend, CLI auth (PTY), SSE streaming, REST + chat UI, recents | **Done**                                  |
| 2.5   | AWS migration              | GCP → AWS ECS Fargate tenant, CommCare Connect OAuth, nginx sidecar, /ace/* prefix | **Done** — per `docs/plans/2026-04-08-aws-migration.md` |
| 3     | Multi-player collaboration | WebSocket consumer, channels-redis, ASGI auth, drafts, presence                 | **Done** — per `docs/plans/2026-04-09-3-multi-player.md` |
| 4     | Library and ingest         | Session list, search/filter, share tokens, `ace upload` CLI, design system (shadcn + dark/light), personal tokens | **Done** — shipped piecemeal across many PRs. Original plan at `docs/plans/2026-04-09-phase-4-library-ingest.md` is marked HISTORICAL at the top; what's live is summarized inside that file. |
| 5     | Polish                     | Observability, evals, accessibility, security review, demo prep, full docs     | **Deferred** — see "Phase 5 deferred" note below. Do not propose this as planned work. |

**Parallel track — ACE Opportunity Workbench** (`apps/opps/` + `/opps` UI, spec
`docs/specs/2026-04-08-ace-opp-visualization-design.md`, plan
`docs/plans/2026-04-08-ace-opp-workbench.md`): **Done** — shipped in PR #17.
Drive-backed, no ORM, three-pane workbench with Discuss-in-chat seeding.
Not yet smoke-tested against a real Drive folder — see "ACE opportunity
visualization" section below.

Phase 1's 25 post-execution corrections (security, races, Docker, deploy) are
documented inline at `docs/plans/2026-04-07-1a-foundation.md` under
**Post-execution corrections**. Read that section before touching config,
settings, Dockerfile, or the auth/sessions models.

## Vendored Claude plugins

The Docker image bundles the ACE plugin repo at `/app/vendor/ace` at build
time (via `git clone --depth 1` in the Dockerfile). It serves two purposes:

1. The **System Overview tab** (`apps/system/`) reads skill metadata, agent
   definitions, and the artifact manifest from `ACE_PLUGIN_PATH` (defaults
   to `/app/vendor/ace` in the container).
2. The plugin is installed at `~/.claude/plugins/cache/ace/ace/<version>/`
   so `claude -p` subprocess sessions have ACE skills, slash commands, and
   MCP servers available. The directory is a symlink into `/app/vendor/ace`
   — one source of truth, two access paths.

The SA key at `$CLAUDE_PLUGIN_DATA/gws-sa-key.json` is written at container
start by `docker-entrypoint.sh` from the `ACE_DRIVE_SA_KEY_JSON` env var
(same secret as the opps Drive client). Never baked into the image.

**To pick up a new ACE plugin release:** rebuild the ace-web image (any
push to main triggers `build-backend.yml`), then run `deploy-labs.yml`.
The System tab's update banner compares local `VERSION` against GitHub's
remote `VERSION` and will tell you when the snapshot has drifted.

**Adding more plugins** (e.g. `superpowers`, `canopy`): follow the same
pattern in `Dockerfile` — `git clone` into `/app/vendor/<name>`, add a
symlink under `~/.claude/plugins/cache/<name>/`, append to
`installed_plugins.json`.

## Stack

- **Backend**: Django 5 + Channels 4 + DRF, ASGI via uvicorn, `psycopg[binary]`, `httpx[http2]` for Connect OAuth, `django-environ`.
- **Frontend**: React 19, Vite 5, TypeScript 5, Tailwind 3.4, react-router-dom 6. Served via nginx sidecar container in prod, built with bun.
- **DB**: PostgreSQL (shared AWS RDS `labs-*` instance, database `ace_web`; local Postgres via `docker compose`).
- **Infra**: AWS ECS Fargate (cluster `labs-jj-cluster`, us-east-1) behind the shared connect-labs ALB (path prefix `/ace/*`). GitHub Actions with OIDC for deploys. AWS Secrets Manager for secrets. ECR for images.
- **Tests**: pytest + pytest-django + pytest-asyncio, in-memory SQLite for unit tests.
- **Pattern sources**: `../connect-labs/` (CommCare Connect OAuth pattern), `../scout-jjackson/` (two-container ECS deploy pattern), `../canopy-web/` (CLI backend + PTY auth flow), `../connect-search/` (DriveClient ABC pattern for `apps/opps/`).

## Project structure

```
ace-web/
├── apps/
│   ├── auth/        # Custom User model + CommCare Connect OAuth  (7 files)
│   ├── common/      # Envelope, CLI backend, SSE, health          (11 files)
│   ├── opps/        # ACE opp Workbench (Drive-backed)            (17 files)
│   └── sessions/    # 7-table data model + streaming endpoints    (9 files)
├── config/          # Split settings, ASGI, urls, routing
├── frontend/
│   └── src/         # api, components, hooks, pages, router       (41 TS/TSX files)
├── tests/           # Project-level tests (asgi smoke)
├── docs/
│   ├── deploy.md
│   ├── learnings/   # 7 load-bearing gotchas (see below)
│   ├── specs/       # Design specs (ace-web + opp visualization)
│   └── plans/       # 1a-foundation, 2-conversation-engine, aws-migration, ace-opp-workbench
├── Dockerfile, Dockerfile.frontend, docker-compose.yml
├── frontend/nginx.prod.conf   # nginx sidecar config for the prod container
├── deploy/aws/                # task-definition.json + one-time-setup.sh
├── .github/workflows/         # build-backend, build-frontend, deploy-labs, ci
└── pyproject.toml
```

44 source Python files under `apps/`, 37 `test_*.py` files, 41 frontend TS/TSX files.

The sessions data model has 7 tables: `users`, `sessions`, `session_participants`,
`messages`, `drafts`, `share_tokens`, `ingest_uploads`. All migrated in Plan 1A.
The `opps` module adds **no ORM tables** — it reads through to Google Drive.

## Key architectural decisions

- **Auth**: CommCare Connect OAuth with PKCE, hand-rolled session-based flow ported from connect-labs (NOT django-allauth). Implementation in `apps/auth/oauth_views.py` + `apps/auth/oauth.py`. Tenant-unique session cookies (`sessionid_ace`, `csrftoken_ace`) and path-scoped (`/ace/`) to avoid collisions with scout on the shared `labs.connect.dimagi.com` host. `AUTH_USER_MODEL = "ace_auth.User"`; the `google_sub` field is a legacy no-op kept to avoid a schema migration. **No domain filter** — the legacy `@dimagi.com` filter was dropped at the start of the multi-tenancy work; `ACE_ALLOWED_EMAIL_DOMAINS` is preserved as a deployment safety knob (set to a non-empty list to revert to allowlisted signups). Workspace membership is the actual access-control gate.
- **Multi-tenancy via Workspaces**: ace-web is multi-tenant. The unit of tenancy is the **Workspace** — a name + a Drive root folder + a member list with roles (Owner / Editor / Viewer). All opp/session/upload reads scope by `request.user`'s workspace memberships; non-members get 404 (not 403) so workspace existence isn't leaked. Drive folder IDs are unique across workspaces — the CLI plugin's implicit-by-folder linkage depends on this. The plugin's `upload-transcript` skill sends `ace_root_folder_id` in the multipart payload so the web side can resolve the originating workspace. The founding migration seeds a single `dimagi-team` workspace from `ACE_DRIVE_ROOT_FOLDER_ID`; after that migration runs, the env var is no longer read at runtime. URL structure: `/w/<slug>/opps/`, `/w/<slug>/sessions/`, etc. — legacy bare paths redirect to the user's first workspace. Self-onboarding wizard at `/welcome` (workspace creation + Drive verify), invite-by-email flow at `/invite/<token>` (auth-optional preview, auth-required accept), member management + activity log + leave-workspace at `/w/<slug>/workspace-settings`. Spec: `docs/specs/2026-04-27-multi-tenant-workspaces-design.md`. Phase A plan: `docs/plans/2026-04-27-multi-tenant-workspaces-phase-a.md`. Phases B (onboarding + invites) and C (leave-workspace, audit log, drive-access banner) shipped in the same branch.
- **Automation auth on labs — `/auth/e2e-login/`**: token-gated endpoint for scripted tools (walkthroughs, smoke tests, CI harnesses). POST `{"email": "ace@dimagi-ai.com", "token": "<ACE_E2E_AUTH_TOKEN>"}` → session cookie. Bypasses OAuth; the `ace@dimagi-ai.com` bot identity is the canonical automation user. Implementation in `apps/auth/e2e_login_views.py`. The URL only registers when `ACE_E2E_AUTH_TOKEN` is non-empty; value lives in `deploy/aws/task-definition.json` (and AWS Secrets Manager for rotation). Distinct from the dev-only `ACE_ALLOW_TEST_LOGIN` / `/auth/test-login/` flow, which requires `DEBUG=True` and never registers on prod. **Use this — not personal tokens — for any scripted ace-web API access.**
- **Response envelope**: Every JSON response uses `{data, error}` via
  `apps.common.envelope.success_response` / `error_response`. See
  `docs/learnings/api-envelope-convention.md`.
- **Health check**: `/api/health` is public. See `docs/deploy.md`.
- **Chat transport is WebSocket-only (Phase 3)**: All realtime chat traffic
  (send, stream deltas, drafts, presence, stop) flows through the
  `SessionConsumer` WebSocket. The Phase 2 `POST /api/sessions/<slug>/messages`
  + SSE replay endpoints were deleted. See
  `docs/learnings/channels-ws-proxy-path.md` for the `/ace/ws/` proxy
  detail and `docs/learnings/channels-websocket-auth.md` for the handshake
  auth pattern.

## Learnings (read before touching the relevant area)

Infra & scaling:
- [channels-single-instance](docs/learnings/channels-single-instance.md) — resolved in Phase 3; `CHANNEL_LAYERS` now uses channels-redis against shared ElastiCache. Raising ECS desired count past 1 is a separate operational step.
- [channels-websocket-auth](docs/learnings/channels-websocket-auth.md) — ASGI session-cookie middleware for WebSocket handshakes; tenant-specific cookie name.
- [redis-presence-hash](docs/learnings/redis-presence-hash.md) — HASH-per-session presence with debounced Postgres writes.
- [channels-ws-proxy-path](docs/learnings/channels-ws-proxy-path.md) — `/ace/ws/` nginx proxy strips the prefix because `FORCE_SCRIPT_NAME` doesn't cover Channels routing.

Auth & identity:
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`) and first-login races must be handled at the DB layer.
- [drive-service-account](docs/learnings/drive-service-account.md) — the opps Workbench talks to Drive via a shared Google service account (not per-user OAuth); the SA key JSON lives in AWS Secrets Manager as `ACE_DRIVE_SA_KEY_JSON`.
- [nova-mcp-oauth](docs/learnings/nova-mcp-oauth.md) — Nova MCP auth: RFC 8707 `resource` indicator is mandatory; `${VAR:-}` expansion in `.mcp.json` headers beats `headersHelper`; Better-Auth rotates refresh_tokens (need `nova:refresh-lock` SETNX); bot identity uses `_can_write_global` not `is_staff`.

API conventions:
- [api-envelope-convention](docs/learnings/api-envelope-convention.md) — every JSON response wraps in `{data, error}`; no bare payloads, no DRF default errors.

Conversation engine (Phase 2):
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.
- [sse-django-async](docs/learnings/sse-django-async.md) — `Cache-Control`/`X-Accel-Buffering` headers, `sync_to_async` ORM access, async cleanup with `asyncio.shield`, and concurrent-write serialization with `select_for_update` are mandatory for SSE views. **Superseded by the Phase 3 WebSocket transport** — kept as historical context for the patterns.

Frontend:
- [draft-soft-lock-idle-timer](docs/learnings/draft-soft-lock-idle-timer.md) — React UIs that show wall-clock-driven transitions need explicit setTimeout-driven re-renders.

Deploy & infrastructure:
- [alb-nginx-django-https](docs/learnings/alb-nginx-django-https.md) — `SECURE_PROXY_SSL_HEADER` + nginx `$real_scheme` map preserve the ALB's `https`, and every `proxy_pass` must rewrite `Host` so ALB health checks don't trip `ALLOWED_HOSTS`. Silent until triggered in real infra.
- [aws-migration](docs/plans/2026-04-08-aws-migration.md) — completed migration from standalone GCP Cloud Run to AWS ECS Fargate as a connect-labs shared-infrastructure tenant. IAP auth swapped for CommCare Connect OAuth. Filestore dropped in favor of the CLIBackend hybrid-resume Django-replay path. Two-container ECS task (Django + nginx sidecar). Shared RDS, ALB, and (Phase 3) ElastiCache reduce incremental cost to ~$5-15/month.

For the full Phase 1 post-execution fix list (25 items including settings hardening,
Dockerfile slimming, SPA catch-all, slug retries, setuptools layout), see the
`## Post-execution corrections` section of `docs/plans/2026-04-07-1a-foundation.md`.

## ACE opportunity visualization (apps/opps)

The `apps/opps/` module is the ACE opportunity Workbench — a read-through UI
on top of Google Drive that shows every skill of an ACE run, per-step
artifact previews, judge verdicts, gate history, a run-level opp-eval
scorecard + trend, pending-gates banner, and a "Discuss in chat" CTA that
seeds a new ace-web `Session` from a step's context.

Google Drive is the source of truth. There are no Django ORM models for
opps / runs / steps / artifacts — the data lives as files under
`ACE/<opp-slug>/` in Drive. The ACE plugin writes `state.yaml`, `pdd.md`,
and skill-specific subfolders (`app-summaries/`, `test-results/`,
`connect-setup/`, `verdicts/`, `gate-briefs/`, `scorecards/`, …); which
skill owns which file is declared in the plugin's
`lib/artifact-manifest.ts` — ace-web parses that manifest and uses it for
file-to-skill attribution (see `apps/system/parsers.py`).

**Single-run per opp (as of 2026-04-20):** The opps Workbench reads one
run per opp. Multi-run support (`runs/run-001/`, `runs/run-002/`, …) was
removed in commits 289ee20–a8ef3d8 to match the ACE plugin's current
convention, where `/ace:run` writes `state.yaml` at the opp root. The
improvement loop is "run → inspect → upgrade plugin → rerun (overwriting)
→ compare". If we bring back multi-run, the plan lives in
`docs/plans/2026-04-20-drop-multi-run-simplify.md § deferred work` — don't
re-derive from scratch.

**Skill registry is dynamic, loaded from the plugin:** `apps/opps/skills.py`
imports agent frontmatter + the artifact manifest from `ACE_PLUGIN_PATH`
(default: auto-discovered sibling `ace/` repo, vendored into
`/app/vendor/ace` in prod) at first access. Adding or renaming a skill in
the plugin is a one-file edit there; ace-web picks it up on next process
start. See also `apps/system/reader.py` which the System Overview tab uses.

**Identity + Drive access:** identity via a hand-rolled CommCare Connect
OAuth flow with PKCE (`apps/auth/oauth_views.py`, pattern from
connect-labs). Drive access is via a single shared Google service
account (the same one the `ace` CLI uses), delivered through
`ACE_DRIVE_SA_KEY_JSON` in AWS Secrets Manager. No per-user Drive
consent. See `docs/learnings/drive-service-account.md`.

**Root folder config:** `ACE_DRIVE_ROOT_FOLDER_ID` (in `config/settings/base.py`,
env-overridable) pins the shared ACE Google Drive folder the Workbench reads
from. Default is the team's shared folder; override in dev/sandbox as needed.
Without it, `_resolve_ace_root_folder_id` returns `None` and the opp list is
empty. Set via AWS Secrets Manager in prod.

**Key files:**
- `apps/opps/sync.py` — Drive-to-payload reader + `load_scorecard` helper;
  manifest-driven file→skill attribution; reads `verdicts/*.yaml` +
  `state.yaml`'s `gates:` map and attaches them to step snapshots
- `apps/opps/previews.py` — per-skill preview extractors (header-row text
  like "12 forms · 34 questions" or "⚖️ 82/100 pass"); falls back to
  artifact count for unknown skills
- `apps/opps/seed.py` — chat-seed builder for "Discuss in chat"
- `apps/opps/drive_client.py` — DriveClient ABC + GoogleDriveClient
- `apps/opps/skills.py` — **dynamic** skill registry loaded from plugin
  agent frontmatter + artifact manifest (not a hardcoded list)
- `frontend/src/components/opps/ScorecardPanel.tsx` — run-level opp-eval
  scorecard chip + dialog in the Workbench header
- `frontend/src/components/opps/PendingGatesBanner.tsx` — review-mode
  "N gates awaiting review" banner at the top of the Workbench
- `frontend/src/pages/OppWorkbenchPage.tsx` — the three-pane UI shell

**Plugin-side contract** (what the plugin at `../ace` emits and ace-web
consumes):
- `state.yaml` at opp root — current phase/step/mode, plus `gates:` map
  with `{decision, decided_by, decided_at, note}` per skill
- `pdd.md` / `idea.md` at opp root
- Per-skill subfolders (paths declared in the plugin's
  `lib/artifact-manifest.ts`)
- `verdicts/<skill>-eval-{quick,deep,monitor}.yaml` — LLM-as-Judge output
- `gate-briefs/<skill>.md` — 5 review-mode gates (+ opp-eval advisory)
- `scorecards/YYYY-MM-DD-opp-eval-*.md` + `scorecards/trend.md` —
  umbrella `opp-eval` run-level aggregation

**Transcript ingest linkage:** `POST /api/ingest/upload` accepts optional
`opp_slug` / `opp_run_id` / `opp_step_skill` multipart fields so uploaded
transcripts from `/ace:run --ace-web-url` (via the plugin's
`upload-transcript` skill) surface under the originating opp in the
Workbench's linked-chats panel. Orphan uploads (no opp fields) still work.

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

- No observability, no eval harness, no security review — see **Phase 5 deferred** note below.

**Phase 5 deferred (2026-04-21):** The Phase 5 "Polish" bundle (structured
logs + correlation fields, p50/p95/p99 metrics, eval harness against
`CLIBackend`, keyboard a11y + aria-live streaming, end-to-end security
review, demo-prep walkthrough, full docs pass) was reviewed against what
already exists — the ACE plugin's transcript-ingest path
(`/ace:run --ace-web-url` → `apps/ingest/` → `/sessions` Imported tab) and
the `createLoggingProxy` pattern in `../ace/mcp/ocs/logging.ts` — and
consciously dropped. We don't see concrete value in doing it as proactive
work right now. Treat the `### 4.7 Polish` section of
`docs/specs/2026-04-08-ace-web-design.md` as aspirational; don't draft a
`docs/plans/2026-04-*-phase-5-*.md` unless a specific operational problem
makes the case for a specific piece of it. **Initial development is done.**

**Phase 4 note:** Library/ingest shipped piecemeal across many PRs
rather than as the single Task-1-through-N execution the original
plan described. The plan file at
`docs/plans/2026-04-09-phase-4-library-ingest.md` is marked HISTORICAL
at the top; the inventory of what's live (and where to read it) lives
in that file's status header. Source of truth for the live surface is
`apps/sessions/`, `apps/ingest/`, `apps/auth/`, and `frontend/src/`.

See `docs/specs/2026-04-08-ace-web-design.md` for the full vision and what
each phase covers.
