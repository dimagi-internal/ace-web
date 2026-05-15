# CLAUDE.md — ace-web

Agent context for the ACE web harness. Read this at the start of every session.

`ace-web` is Module 1 of the ACE initiative: a browser-based chat harness that talks
to Claude via the local CLI (subscription auth) with multi-player drafts, persistent
transcripts, and upload support for existing local `.jsonl` sessions.

## Where things live

- **Design spec** (the whole vision and phase breakdown): `docs/specs/2026-04-08-ace-web-design.md`.
- **Implementation plans** (per phase): `docs/plans/`. Notable in-flight: `2026-05-03-cli-backend-phase-1b-long-lived.md` (design-only) and `2026-05-05-stream-reconnect-resilience.md` (Hazard 1 in flight, Hazard 2 deferred).
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

**Phases 1 through 4 shipped between 2026-04-07 and 2026-04-21.** Phase 5
("Polish") is **deferred indefinitely** — we reviewed the scope (observability,
evals, a11y, security review, demo prep, docs pass) and decided the concrete
value didn't justify the work at that stage. Revisit if a specific pain
point surfaces in real team use, but do not plan it as proactive work.

The whole-product design is in `docs/specs/2026-04-08-ace-web-design.md`.
Phases below come from that spec — they are engineering execution checkpoints,
not user-shippable milestones.

| Phase | Name                       | Scope                                                                           | Status                                    |
|-------|----------------------------|---------------------------------------------------------------------------------|-------------------------------------------|
| 1     | Foundation                 | Django + Channels + React skeleton, data model, IAP, GCP                        | **Done** — merged in jjackson/ace-web#1   |
| 2     | Conversation engine        | ChatBackend, CLIBackend, CLI auth (PTY), SSE streaming, REST + chat UI, recents | **Done**                                  |
| 2.5   | AWS migration              | GCP → AWS ECS Fargate tenant, CommCare Connect OAuth, nginx sidecar, /ace/* prefix | **Done** — per `docs/plans/2026-04-08-aws-migration.md` |
| 3     | Multi-player collaboration | WebSocket consumer, channels-redis, ASGI auth, drafts, presence                 | **Done** — per `docs/plans/2026-04-09-3-multi-player.md` |
| 4     | Library and ingest         | Session list, search/filter, share tokens, `ace upload` CLI, design system (shadcn + dark/light), personal tokens | **Done** — shipped piecemeal across many PRs. Plan file is HISTORICAL. |
| 5     | Polish                     | Observability, evals, accessibility, security review, demo prep, full docs     | **Deferred** — see "Phase 5 deferred" note below. Do not propose this as planned work. |

**Post-Phase-4 work (continuing).** ~115 PRs have shipped between 2026-04-22
and 2026-05-07 covering work that wasn't in the original phase plan. The
substantive themes:

- **Multi-tenant workspaces** (PRs #137-#142, founding `apps/workspaces/`) —
  the unit of tenancy is now a `Workspace`, not a domain allowlist. URLs
  are workspace-scoped (`/w/<slug>/…`), reads are membership-gated. Spec:
  `docs/specs/2026-04-27-multi-tenant-workspaces-design.md`.
- **Nova MCP integration** (PRs #167, #173-#184) — server-side OAuth + per-spawn
  `.mcp.json` staging so `claude -p` subprocesses can call
  `mcp__plugin_nova_nova__*` without an interactive consent. Auth blob lives
  in `apps/auth/nova_oauth_views.py` + `apps/common/nova_auth_flow.py`.
  See learning `nova-mcp-oauth.md`.
- **System Overview tab** (`apps/system/`, plan
  `docs/plans/2026-04-14-system-overview.md`) — read-through view of the
  bundled ACE plugin's skills, agents, MCPs, and artifact manifest. Driven
  by `apps/system/reader.py` parsing `ACE_PLUGIN_PATH`.
- **Public per-run opp summary page** (PRs #220-#226, #229, #233-#234) —
  `/opps/<slug>/summary` is a stakeholder-facing single-page rollup with
  the OCS chatbot widget embedded. Spec:
  `docs/specs/2026-05-04-opp-summary-page-design.md`.
- **Workbench view modes** (PRs #185-#196) — Hierarchy / Timeline / Flow
  shells over the same opp data. `apps/activity/` powers the workspace
  Timeline.
- **Per-session and per-opp cost & timing breakdown** (PRs #200-#206, #210,
  #219) — JSONL transcripts roll up at ingest time into `Session.cost_breakdown`,
  surfaced as Cost & Timing tabs and rollup chips.

Phase 1's 25 post-execution corrections (security, races, Docker, deploy) are
documented inline at `docs/plans/2026-04-07-1a-foundation.md` under
**Post-execution corrections**. Read that section before touching config,
settings, Dockerfile, or the auth/sessions models.

## Vendored Claude plugins

The Docker image bundles two Claude plugins at build time so `claude -p`
subprocesses spawned by `CLIBackend` have ACE skills, slash commands, and
MCP servers available.

- **ACE plugin** at `/app/vendor/ace` (the CRISPR-Connect orchestration
  plugin from sibling repo `ace`). Cloned via `git clone --depth 1` in the
  Dockerfile. Two access paths:
  1. The **System Overview tab** (`apps/system/`) reads skill metadata,
     agent definitions, and the artifact manifest from `ACE_PLUGIN_PATH`
     (defaults to `/app/vendor/ace`).
  2. Installed at `~/.claude/plugins/cache/ace/ace/<version>/` so subprocess
     sessions see the plugin. As of PR #177, the cache directory must be a
     real directory, not a symlink — Claude Code 2.x removes symlinks.
- **Nova plugin** at `/app/vendor/nova` (since PR #167) — same bundling
  pattern as ACE. Critical difference: Nova requires OAuth 2.1 + PKCE per
  the late-2025 MCP spec, and Claude Code's interactive consent flow doesn't
  work in a headless container. ace-web runs the dance server-side
  (`apps/auth/nova_oauth_views.py`) and stages a fresh `.mcp.json` per
  subprocess spawn with the access_token expanded. See `nova-mcp-oauth.md`.

The SA key at `$CLAUDE_PLUGIN_DATA/gws-sa-key.json` is written at container
start by `docker-entrypoint.sh` from the `ACE_DRIVE_SA_KEY_JSON` env var
(same secret as the opps Drive client). Never baked into the image. The
`.env` for plugin MCPs is rendered via `op inject` at container start (see
`mcp-bootstrap-container-traps.md` for the comment-syntax + `npx tsx` traps
that have bitten us).

**To pick up a new ACE plugin release:** rebuild the ace-web image (any
push to main triggers `build-backend.yml`), then run `deploy-ace-web-labs.yml`.
The System tab's update banner compares local `VERSION` against GitHub's
remote `VERSION` and will tell you when the snapshot has drifted.

## Stack

- **Backend**: Django 5 + Channels 4 + Django Ninja (v1.x) + Pydantic v2, ASGI via uvicorn, `psycopg[binary]`, `httpx[http2]` for Connect OAuth, `django-environ`. DRF removed in the API modernization (Phases 0-8, 2026-05-14). OpenAPI 3.1 schema auto-generated at `/api/v2/openapi.json`; Scalar UI at `/api/docs/`; Redoc at `/api/redoc/`. All errors return RFC 7807 `application/problem+json`. Frontend TypeScript types are generated from the schema (`frontend/src/api/types.ts`). FastMCP bridge at `/api/mcp/` exposes read-only opp + session tools for external MCP clients. Observability: structured JSON logs to stdout (captured by ECS `awslogs` → CloudWatch Logs Insights); `RequestIDMiddleware` stamps every log record with a `request_id`. No distributed tracing — at our scale (small team) the structured logs are sufficient.
- **Frontend**: React 19, Vite 5, TypeScript 5, Tailwind 3.4, react-router-dom 6. Served via nginx sidecar container in prod, built with bun.
- **DB**: PostgreSQL (shared AWS RDS `labs-*` instance, database `ace_web`; local Postgres via `docker compose`).
- **Infra**: AWS ECS Fargate (cluster `labs-jj-cluster`, us-east-1) behind the shared connect-labs ALB (path prefix `/ace/*`). GitHub Actions with OIDC for deploys. AWS Secrets Manager for secrets. ECR for images.
- **Tests**: pytest + pytest-django + pytest-asyncio, in-memory SQLite for unit tests. Frontend tests run on vitest + @testing-library/react + jsdom (`bun run test` / `bun run test:watch`); shipped 2026-05-10 alongside the `sessionReducer` extraction.
- **Pattern sources**: `../connect-labs/` (CommCare Connect OAuth pattern), `../canopy-web/` (CLI backend + PTY auth flow), `../connect-search/` (DriveClient ABC pattern for `apps/opps/`). The two-container ECS deploy pattern lives in this repo's own `Dockerfile` + `Dockerfile.frontend` + `frontend/nginx.prod.conf`.

## Project structure

```
ace-web/
├── apps/
│   ├── activity/        # Workspace Timeline aggregator
│   ├── auth/            # Custom User model + CommCare Connect OAuth + Nova OAuth
│   ├── common/          # Envelope, CLI backend, channels auth, Nova auth flow
│   ├── ingest/          # JSONL upload + cost/timing aggregator + pricing
│   ├── opps/            # ACE opp Workbench (Drive-backed) + summary page
│   ├── service_accounts/ # Personal tokens + share tokens
│   ├── sessions/        # 7-table data model + WebSocket consumer + presence
│   ├── system/          # System Overview tab — reads bundled plugin metadata
│   └── workspaces/      # Multi-tenant workspace + invites + audit log
├── config/              # Split settings (base, connectlabs, development, production, e2e, test)
├── frontend/
│   └── src/             # api, components, hooks, pages, router
├── tests/               # Project-level tests (asgi smoke)
├── docs/
│   ├── deploy.md
│   ├── architecture/    # cli-credentials.md
│   ├── learnings/       # 18 load-bearing gotchas (see below)
│   ├── plans/           # Phase plans + scoped initiatives (18 files)
│   └── specs/           # Design specs (15 files)
├── Dockerfile, Dockerfile.frontend, docker-compose.yml, docker-entrypoint.sh
├── frontend/nginx.prod.conf   # nginx sidecar config for the prod container
├── frontend/vitest.config.ts  # vitest harness (jsdom + RTL)
├── deploy/aws/                # task-definition.json + one-time-setup.sh
├── .github/workflows/         # build-backend, build-frontend, deploy-ace-web-labs, ci
└── pyproject.toml, VERSION
```

241 source Python files under `apps/` (excluding migrations and `__pycache__`),
103 `test_*.py` files, 144 frontend TS/TSX files (3 `*.test.ts`), as of 2026-05-10.

**Notable internal modules to know about** (introduced in PR #286, 2026-05-10):
- `apps/opps/access.py` — public workspace + Drive helpers (`resolve_workspace`,
  `require_drive`, `resolve_ace_root_folder_id`, `overlay_workspace_display_name`,
  `snapshot_etag`). All views call `access.X(...)` via attribute lookup so a
  single `mock.patch("apps.opps.access.X")` intercepts every caller. See
  `docs/learnings/opps-access-module.md`.
- `apps/opps/views_{read,write,session,summary}.py` — views.py was 1,583 lines;
  split into focused modules. `views.py` keeps the read views and the GET/POST
  + GET/PATCH/DELETE dispatchers (`opp_collection`, `workbench`); other files
  are imported into views.py for back-compat with code that imports from
  `apps.opps.views`.
- `apps/opps/snapshot_cache.cold_load_client` + `etag_or_304` — collapsed the
  two near-identical cache-flow blocks in `_opp_list_impl` and `workbench`.
- `apps/common/access.gate_membership(user, workspace, hidden_existence=)` —
  shared 404-vs-403 decision used by `apps/opps/access`,
  `apps/workspaces/views`, and `apps/ingest/views`. Lookup logic stays per-app
  (each surface uses a different key — slug, drive_root_folder_id, header).
- `apps/common/cli_backend.py` defers `Session`/`Message` ORM imports via
  `TYPE_CHECKING` + function-local imports; breaks the static
  `common ↔ sessions` cycle (turn_driver imports back from common).

**Frontend modules introduced 2026-05-10**:
- `frontend/src/hooks/sessionReducer.ts` — pure 14-branch WS reducer extracted
  from `useSessionSocket` (which dropped 447 → 210 lines). Side-effect events
  (`session.title_updated`, `session.error`) stay impure in the hook. Covered
  by 17 vitest cases.
- `frontend/src/hooks/useApi.ts` — generic fetch+state hook with cancellation;
  replaces the open-coded `useState + useEffect + cancelled` triple in
  `useOppCostRollup`, `useMultiRunSummary`, `useOppRuns`, and elsewhere.
- `frontend/src/lib/wsUrl.ts` — single WS URL builder shared by
  `useSessionSocket` and `useOppSocket`.
- `frontend/src/lib/sortOpps.ts` + `frontend/src/components/opps/OppCard.tsx` —
  `OppListPage` 558 → 240 lines after extracting the inline card.
- `frontend/src/components/opps/ConfirmDialog.tsx` — destructive-confirm
  primitive (Dialog shell + submitting state + toast translation). Used by
  `DeleteOppDialog` and `DeleteRunDialog`.
- `frontend/src/components/views/phase-skill/sections.tsx` — Producer / QA /
  Eval drawer sections moved out of `PhaseSkillRow.tsx` (which dropped
  487 → 218 lines).

The sessions data model has 7 core tables: `users`, `sessions`,
`session_participants`, `messages`, `drafts`, `share_tokens`, `ingest_uploads`.
`apps/workspaces/` adds `Workspace`, `WorkspaceMember`, `WorkspaceInvite`,
and audit-log tables. The `opps` module adds **no ORM tables** — it reads
through to Google Drive.

## Key architectural decisions

- **Auth**: CommCare Connect OAuth with PKCE, hand-rolled session-based flow ported from connect-labs (NOT django-allauth). Implementation in `apps/auth/oauth_views.py` + `apps/auth/oauth.py`. Tenant-unique session cookies (`sessionid_ace`, `csrftoken_ace`) and path-scoped (`/ace/`) to avoid collisions with scout on the shared `labs.connect.dimagi.com` host. `AUTH_USER_MODEL = "ace_auth.User"`; the `google_sub` field is a legacy no-op kept to avoid a schema migration. **No domain filter** — the legacy `@dimagi.com` filter was dropped at the start of the multi-tenancy work; `ACE_ALLOWED_EMAIL_DOMAINS` is preserved as a deployment safety knob (set to a non-empty list to revert to allowlisted signups). Workspace membership is the actual access-control gate.
- **Multi-tenancy via Workspaces**: ace-web is multi-tenant. The unit of tenancy is the **Workspace** — a name + a Drive root folder + a member list with roles (Owner / Editor / Viewer). All opp/session/upload reads scope by `request.user`'s workspace memberships; non-members get 404 (not 403) so workspace existence isn't leaked. Drive folder IDs are unique across workspaces — the CLI plugin's implicit-by-folder linkage depends on this. The plugin's `upload-transcript` skill sends `ace_root_folder_id` in the multipart payload so the web side can resolve the originating workspace. The founding migration seeds a single `dimagi-team` workspace from `ACE_DRIVE_ROOT_FOLDER_ID`; after that migration runs, the env var is no longer read at runtime. URL structure: `/w/<slug>/opps/`, `/w/<slug>/sessions/`, etc. — legacy bare paths redirect to the user's first workspace. Self-onboarding wizard at `/welcome` (workspace creation + Drive verify), invite-by-email flow at `/invite/<token>` (auth-optional preview, auth-required accept), member management + activity log + leave-workspace at `/w/<slug>/workspace-settings`. Spec: `docs/specs/2026-04-27-multi-tenant-workspaces-design.md`. Phase A plan: `docs/plans/2026-04-27-multi-tenant-workspaces-phase-a.md`. Phases B (onboarding + invites) and C (leave-workspace, audit log, drive-access banner) shipped in the same branch.
- **Automation auth on labs — `/auth/e2e-login/`**: token-gated endpoint for scripted tools (walkthroughs, smoke tests, CI harnesses). POST `{"email": "ace@dimagi-ai.com", "token": "<ACE_E2E_AUTH_TOKEN>"}` → session cookie. Bypasses OAuth; the `ace@dimagi-ai.com` bot identity is the canonical automation user. Implementation in `apps/auth/e2e_login_views.py`. The URL only registers when `ACE_E2E_AUTH_TOKEN` is non-empty; value lives in `deploy/aws/task-definition.json` (and AWS Secrets Manager for rotation). Distinct from the dev-only `ACE_ALLOW_TEST_LOGIN` / `/auth/test-login/` flow, which requires `DEBUG=True` and never registers on prod. **Use this — not personal tokens — for any scripted ace-web API access.**
- **Nova MCP integration**: ace-web runs Nova's OAuth 2.1 + PKCE dance server-side and injects a fresh access_token into every `claude -p` subprocess so the bundled Nova plugin's HTTP MCP can authenticate without prompting. Auth flow in `apps/common/nova_auth_flow.py`; views in `apps/auth/nova_oauth_views.py`. Token refresh is serialized across ECS tasks via a Redis SETNX `nova:refresh-lock` (Better-Auth rotates refresh_tokens, so concurrent refreshes from sibling tasks would both fail). Bot-identity write permission gates on `_can_write_global`, not Django's `is_staff`. See `docs/learnings/nova-mcp-oauth.md` before touching this.
- **System Overview tab** (`apps/system/`): read-through UI over the bundled ACE plugin at `ACE_PLUGIN_PATH`. `reader.py` parses agent frontmatter, the artifact manifest, and MCP declarations; `parsers.py` is shared with `apps/opps/skills.py` for canonical phase/skill labels. The "Other" bucket was eliminated in PR #206 — every artifact now attributes to a real skill or fails loudly.
- **API surface (Django Ninja + OpenAPI 3.1)**: The entire REST API is implemented with Django Ninja v1.x routers. Each app exposes an `api_v2.py` module (`apps/<app>/api_v2.py`) whose router is registered in `config/urls.py`. All request/response bodies are Pydantic v2 models (defined in `apps/<app>/schemas.py`). Errors return RFC 7807 `application/problem+json` via `apps.common.problem.ProblemError`. The auto-generated OpenAPI schema at `/api/v2/openapi.json` drives Scalar (`/api/docs/`) and Redoc (`/api/redoc/`) UIs and the `frontend/src/api/types.ts` TypeScript type file (regenerated via `.github/workflows/regen-openapi.yml`). Contract tests run via Schemathesis in `.github/workflows/contract-tests.yml`. A FastMCP read-only bridge is mounted at `/api/mcp/` (`apps/api_v2/mcp.py`); see `docs/architecture/mcp-bridge.md`. Observability: structured JSON logs + X-Ray tracing configured in production settings (AWS-native, no third-party SaaS). Phases 0-8 of the API modernization (`docs/plans/2026-05-14-api-modernization.md`) are **complete and merged**.
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
  auth pattern. Stream-resume hazards documented in
  `docs/learnings/stream-resume-vercel-open-agents.md`.
- **Per-session and per-opp cost & timing breakdown**: ace-web aggregates wall time and token costs from uploaded JSONL transcripts at ingest time, persists to `Session.cost_breakdown` (JSONField), and surfaces them as a rollup chip on the Opp Workbench (the per-session Cost & Timing tab was retired in favor of the Structure view; see next bullet). Phase / skill labels reuse `apps/system/reader.py`'s plugin-derived registry. Aggregator logic in `apps/ingest/cost_aggregator.py`; pricing table in `apps/ingest/pricing.py` (refresh ~twice/year). Sidechain attribution gotcha: `docs/learnings/sidechain-attribution.md`.
- **Per-session Structure view** (`apps/sessions/views.py::session_structure` at `GET /api/sessions/<slug>/structure`): on-demand hierarchical session tree (phase → skill → tool, with subagent recursion + parallel-group clusters). Computed fresh per request from `IngestUpload.raw_jsonl_gz` (gzipped raw bytes persisted at ingest time); never persisted as a JSONField. The Structure tab in `frontend/src/components/structure/` replaced the Cost & Timing tab on session detail — collapsed it shows the same phase rollups with wall-time and cost, expanded it drills to individual tool calls with status icons (✓/✗/◐) and parallel-execution brackets. Aggregator: `apps/ingest/structure_aggregator.py` (pure; shares helpers with cost aggregator via `apps/ingest/_common.py`). Pre-2026-05-10 uploads have `raw_jsonl_gz=NULL` and need re-upload via `/ace:upload-transcript` to enable the view; the endpoint returns `schema_version=0` with `unavailable_reason: "no-raw-jsonl"` (or `"parse-failed"` for corrupt blobs) so the UI renders a clear hint. Spec: `docs/plans/2026-05-10-session-structure-view.md`.
- **Opp Workbench cache (Drive Changes API)**: opp data is read-through to Drive but cached long-lived. Each request polls `drive.changes.list` once (~150 ms) with a Redis-stored pageToken; only file_ids reported as changed invalidate matching `OppSnapshot` / `OppCard` cache entries. Backend serves cached snapshots with an ETag header derived from `sha256(json.dumps(payload, sort_keys=True))`; `If-None-Match` round-trips return 304. Frontend keeps a per-tab `Map<key, {data, etag}>` cache that survives route mounts. Net effect: load any opp once, navigations back are sub-second indefinitely until something in that opp's tree actually changes in Drive (~46-55× speedup on a real opp). Spec: `docs/specs/2026-05-08-opp-cache-redesign.md`. Implementation gotchas: `docs/learnings/opp-cache-architecture.md` (load-bearing details: `workspace.pk` is a slug, cold-load needs `bypass=True`, ETag must hash serialized body not file fingerprints).
- **Videos / clip-explorer (`apps/videos/`)**: workspace-scoped Django app that ports the Node clip-explorer (`video-production/connect-videos/scripts/explore.ts`) into the ace-web shell. Ninja v2 router at `/api/w/<slug>/videos/*`, Pydantic schemas in `apps/videos/schemas.py`, service layer in `apps/videos/service.py` (ruamel.yaml round-trip preserves comments; library parser; subprocess-driven render trigger with Redis busy flag `videos:render:<slug>:busy`). Frontend page at `/w/<slug>/videos/<program>` iframes the generated `out/clip-explorer/<slug>/index.html` after rewriting root-absolute paths and injecting a CSRF wrapper around `fetch`. Read endpoints (list_programs, get_program, get_library, get_render_status, get_feedback) are MCP-exposed via `x-mcp-expose: true`. Programs live as YAML files on disk under `video-production/connect-videos/programs/` and declare ownership via a top-level `workspace: <slug>` field; non-members get 404. Setting: `ACE_VIDEOS_ROOT` (defaults to `BASE_DIR / "video-production" / "connect-videos"`). Renders shell out to `npm run hydrate && npm run render && npm run build-clip-explorer` — Node toolchain is dev-only for now; the explorer surface still works read-only without it. Slug validation in `service.is_valid_slug` is mandatory before any subprocess spawn (slugs flow into a shell command).
- **Videos beat editor (React rewrite)**: as of 2026-05-15, the per-run editor
  is a native React tree under `frontend/src/components/videos/`
  (`<BeatEditor>` + reducer + drawer). Local-buffer dirty state, batched save
  via `POST /edit-batch`. Gated on `ACE_VIDEO_BEAT_EDITOR_REACT` (default
  False in prod until dogfooded). When False, falls back to the iframe-served
  HTML from `build-clip-explorer.ts`. Spec:
  `docs/specs/2026-05-15-video-beat-editor-react-port-design.md`.
- **Cloud mobile emulator (`apps/mobile/`)**: ace-web orchestrates a single EC2 instance (`m8i.xlarge` with nested virtualization enabled) running an Android AVD via SSM. The bake lives in `infra/mobile-ami/` (Packer); the runtime API is `/api/mobile/*` (status, ensure-running, run-recipe, diagnose, etc). Settings: `ACE_MOBILE_INSTANCE_ID`, `ACE_MOBILE_S3_BUCKET`, `ACE_MOBILE_AWS_REGION`, `ACE_MOBILE_AMI_VERSION`. The orchestrator is `apps/mobile/controller.EmulatorController` — boto3-based, lazy-clients, framed-stdout SSM probes. **`run-recipe` is async (202+job_id)** to dodge ALB's 60 s idle timeout; the worker thread holds the `mobile:emulator:lock` singleton lock through completion and writes results to `mobile:job:<id>` in Redis (`apps/mobile/jobs.py`). Polled via `GET /api/mobile/jobs/<id>`. The `/api/mobile/admin/patch-launch-script` endpoint is the hot-fix path for the in-VM launcher; gated on `_can_write_global` and every patch writes a `MobileLaunchScriptPatch` audit row. **AMI rolls are one command: `AWS_PROFILE=labs ./infra/mobile-ami/rebake.sh`** — bakes, updates the launch-template, terminates+recreates the EC2 instance (EC2 AMIs are pinned at launch, stop/start doesn't pick up new images), enables nested virt, updates task-def, opens+merges PR, triggers deploy. The sibling `infra/mobile/` Terraform stack created the original resources but its state file isn't on a shared backend and is functionally lost — `rebake.sh` is the supported management path. `status()` caches the in-VM idle marker probe for 10 s (Django cache) so skill polling loops don't saturate one ECS worker. See `docs/learnings/squash-merge-stale-branch-orphans-commits.md` for the merge-method gotcha that lost the stop busy-guard PR in May 2026.

## Learnings (read before touching the relevant area)

Infra & scaling:
- [channels-single-instance](docs/learnings/channels-single-instance.md) — resolved in Phase 3; `CHANNEL_LAYERS` now uses channels-redis against shared ElastiCache. Raising ECS desired count past 1 is a separate operational step.
- [channels-websocket-auth](docs/learnings/channels-websocket-auth.md) — ASGI session-cookie middleware for WebSocket handshakes; tenant-specific cookie name.
- [redis-presence-hash](docs/learnings/redis-presence-hash.md) — HASH-per-session presence with debounced Postgres writes.
- [channels-ws-proxy-path](docs/learnings/channels-ws-proxy-path.md) — `/ace/ws/` nginx proxy strips the prefix because `FORCE_SCRIPT_NAME` doesn't cover Channels routing.

Auth & identity:
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`) and first-login races must be handled at the DB layer. Note: this learning's `IAPHeaderAuthMiddleware` reference is historical (IAP middleware was removed in the AWS migration); the SQL UNIQUE-vs-NULL rule still holds in `apps/auth/managers.py`.
- [drive-service-account](docs/learnings/drive-service-account.md) — the opps Workbench talks to Drive via a shared Google service account (not per-user OAuth); the SA key JSON lives in AWS Secrets Manager as `ACE_DRIVE_SA_KEY_JSON`.
- [connect-oauth-openid-email](docs/learnings/connect-oauth-openid-email.md) — Connect's token introspection returns an empty `email` for HQ-linked accounts; you have to request `openid` scope AND set `response_type=token` on the token exchange POST or the AS 500s trying to mint an OIDC ID token.
- [nova-mcp-oauth](docs/learnings/nova-mcp-oauth.md) — Nova MCP auth: RFC 8707 `resource` indicator is mandatory; `${VAR:-}` expansion in `.mcp.json` headers beats `headersHelper`; Better-Auth rotates refresh_tokens (need `nova:refresh-lock` SETNX); bot identity uses `_can_write_global` not `is_staff`.

API conventions:
- [api-envelope-convention](docs/learnings/api-envelope-convention.md) — every JSON response wraps in `{data, error}`; no bare payloads, no DRF default errors.

Conversation engine (Phase 2):
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.
- [sse-django-async](docs/learnings/sse-django-async.md) — `Cache-Control`/`X-Accel-Buffering` headers, `sync_to_async` ORM access, async cleanup with `asyncio.shield`, and concurrent-write serialization with `select_for_update` are mandatory for SSE views. **Superseded by the Phase 3 WebSocket transport** — kept as historical context for the patterns.
- [stream-resume-vercel-open-agents](docs/learnings/stream-resume-vercel-open-agents.md) — two stream-resume hazards: stop-during-reconnect drops the stop frame (Hazard 1, addressed in `docs/plans/2026-05-05-stream-reconnect-resilience.md`) and reconnect-during-stream loses up to 250 ms of characters (Hazard 2, deferred — needs Redis live-mirror + delta sequence numbers).

Cost & timing breakdown:
- [sidechain-attribution](docs/learnings/sidechain-attribution.md) — `apps/ingest/cost_aggregator.py` rolls subagent assistant turns into the parent skill segment via `parentUuid` → containing-message uuid match. Without this, Phase totals under-report by the cost of every Agent dispatch.

Opp Workbench cache (`apps/opps/`):
- [opp-cache-architecture](docs/learnings/opp-cache-architecture.md) — Drive Changes API per-request poll + long-lived `OppSnapshot` / `OppCard` cache + ETag round-trip. `workspace.pk` is a slug not an int; cold-load needs `bypass=True` to defeat the inner per-call TTL; ETag is `sha256` of the serialized payload (cold and warm paths must agree); 410 on `pageToken` clears the workspace cache; `_KEY_VERSION` must bump when `OppSnapshot` shape changes.
- [opps-access-module](docs/learnings/opps-access-module.md) — patch on `apps.opps.access.X`, not `apps.opps.views.X`. Views call `access.X(...)` via attribute lookup so a single patch intercepts every caller across the `views_{read,write,session,summary}.py` split. Patching `apps.opps.views._resolve_*` only works for views still in views.py; views moved out won't see the patch and silently use the real function.

Frontend:
- [draft-soft-lock-idle-timer](docs/learnings/draft-soft-lock-idle-timer.md) — React UIs that show wall-clock-driven transitions need explicit setTimeout-driven re-renders.
- [card-click-and-grid-stretch](docs/learnings/card-click-and-grid-stretch.md) — two layout traps that masquerade as React state bugs in card-grid UIs: (1) `<button>` nested inside `<a>` / `<Link>` routes clicks ambiguously across cards; (2) CSS Grid's default `align-items: stretch` makes collapsed neighbors visually appear to also expand. Both took a real-browser repro to catch.

Deploy & infrastructure:
- [alb-nginx-django-https](docs/learnings/alb-nginx-django-https.md) — `SECURE_PROXY_SSL_HEADER` + nginx `$real_scheme` map preserve the ALB's `https`, and every `proxy_pass` must rewrite `Host` so ALB health checks don't trip `ALLOWED_HOSTS`. Silent until triggered in real infra.
- [mcp-bootstrap-container-traps](docs/learnings/mcp-bootstrap-container-traps.md) — two infra failure modes that both look like "MCP tools missing" in chat: (1) `op inject` parses `{{ }}` and `op://` literals inside `.env.tpl` comments and aborts the whole render; (2) `npx tsx` from a cwd without `node_modules` triggers an on-the-fly registry install that races Claude Code's 30 s MCP connection timeout. Read before touching `Dockerfile`, `docker-entrypoint.sh`, or `.env.tpl`.
- [long-running-turns-vs-deploys](docs/learnings/long-running-turns-vs-deploys.md) — ECS task replacement kills any in-flight `claude -p` subprocess, which is fatal to multi-hour `/ace:run` orchestrator turns. Drive state is the durable source of truth; resumption works by sending a fresh `/ace:run`, eating one `error_during_execution` (the stale `--resume`), and sending again. Audit fix #13 makes the recovery one-resend instead of two.

Repo / merge process:
- [squash-merge-stale-branch-orphans-commits](docs/learnings/squash-merge-stale-branch-orphans-commits.md) — GitHub squash-merge from a topic branch that hasn't pulled an intervening merge silently overwrites the intervening commits on `main`; the orphaned PR still shows `state: MERGED` on GitHub but `git merge-base --is-ancestor <merge> origin/main` returns no. Cost us PR #309 (mobile stop busy-guard) in May 2026. Repo defense: `allow_squash_merge=false` (set 2026-05-12). Don't re-enable squash without also turning on "Always suggest updating pull request branches" + a branch-protection rule requiring up-to-date branches before merge.

Notable plans (not learnings, but load-bearing context):
- `docs/plans/2026-04-08-aws-migration.md` — completed migration from standalone GCP Cloud Run to AWS ECS Fargate. Two-container ECS task; shared RDS, ALB, ElastiCache.

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

**Multi-run per opp (canonical):** Each opp is expected to have multiple
runs under `runs/run-001/`, `runs/run-002/`, … The Workbench reads them
through the multi-run reader (revived in PR #193) and the run selector +
URL `?run_id=…` choose which one is active. The improvement loop is
"run → inspect → chat → upgrade skill → rerun (new run folder) → compare
across runs". A 2026-04-20 simplification briefly collapsed to single-run
(commits 289ee20–a8ef3d8) before being reversed; the historical context
lives in `docs/plans/2026-04-20-drop-multi-run-simplify.md`.

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
- `frontend/src/pages/OppWorkbenchPage.tsx` — the three-pane Workbench shell
- `frontend/src/pages/OppSummaryPage.tsx` + `frontend/src/components/opps/summary/*` + `frontend/src/api/oppSummary.ts` — the public per-run summary page (`/opps/<slug>/summary`) that embeds the OCS chatbot widget. Spec: `docs/specs/2026-05-04-opp-summary-page-design.md`.

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

- **Local dev**: `docker compose up`. App at `http://localhost:8000`, Postgres at `localhost:5434`. Backend hot-reload + working Vite dev server landed in PR #235.
- **Tests**: `pytest -v` from repo root. Uses in-memory SQLite; fast hashers.
- **Lint**: `ruff check .` — `line-length=100`, `target=py311`, rules `E,F,W,I,UP,B`.
- **Deploy**: GitHub Actions workflow `.github/workflows/deploy-ace-web-labs.yml`. Manual trigger (Actions → Deploy to Labs (AWS) → Run workflow). Set `run_migrations: true` on schema-changing deploys. First-time setup: `deploy/aws/one-time-setup.sh`. See `docs/deploy.md` for the full runbook.
- **Plans-driven work**: Implementation follows the per-phase plan file in `docs/plans/`.
  Each phase plan is generated from the design spec via the `writing-plans` skill.
  Use the superpowers `subagent-driven-development` or `executing-plans` sub-skill
  to execute it, as the plan specifies.

## What does NOT ship yet

- **API modernization Phases 0-8 are DONE** (merged 2026-05-14): Django Ninja, Pydantic v2, OpenAPI 3.1, RFC 7807 problem+json, Scalar/Redoc, generated frontend types, Schemathesis CI contract tests, FastMCP bridge, basedpyright CI, AWS-native observability (structured JSON logs + X-Ray). No further API modernization work is planned.
- No eval harness, no security review — see **Phase 5 deferred** note below.
- **Observability** uses AWS-native tooling: structured JSON logs to stdout (captured by ECS `awslogs` driver → CloudWatch Logs Insights). `RequestIDFilter` stamps each log record with a `request_id`; `RequestIDMiddleware` generates or propagates `X-Request-ID` headers. No distributed tracing — at small-team scale the structured logs are sufficient; if a "this is slow and I don't know why" debugging need ever surfaces, AWS X-Ray would be the right add-on at that point.
- Stream-reconnect Hazard 2 (reconnect-during-stream gap, up to 250 ms char loss) is documented but **deferred** until observed in real user reports. See `docs/learnings/stream-resume-vercel-open-agents.md`.

(Phase 1B — long-lived per-session subprocess refactor of `CLIBackend` —
SHIPPED in commit `a02093e`. The `docs/plans/2026-05-03-cli-backend-phase-1b-long-lived.md`
file is HISTORICAL; the design is reflected in the `cli_backend.py` module
docstring's "Two execution paths" section.)

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
makes the case for a specific piece of it.

**Phase 4 note:** Library/ingest shipped piecemeal across many PRs rather
than as the single Task-1-through-N execution the original plan described.
The plan file at `docs/plans/2026-04-09-phase-4-library-ingest.md` is
marked HISTORICAL at the top; source of truth for the live surface is
`apps/sessions/`, `apps/ingest/`, `apps/auth/`, and `frontend/src/`.

See `docs/specs/2026-04-08-ace-web-design.md` for the full vision and what
each phase covers.
