# CLAUDE.md — ace-web

Agent context for the ACE web harness. Read this at the start of every session.

`ace-web` is Module 1 of the ACE initiative: the opp Workbench that runs and observes
ACE's own agent work (via Claude, driven through the local CLI or API), with
persistent transcripts and upload support for existing local `.jsonl` sessions.
Phases 1–4 of the original design spec shipped (foundation, conversation engine,
multi-player, library/ingest); Phase 5 (Polish) is deferred indefinitely. Interactive
chat moved out to canopy-hosted chat (canopy-web) — ace-web's own multi-player
WebSocket chat UI was retired; see "Chat is canopy-hosted, full stop" below. Active
surfaces in 2026-07 are the opp Workbench, the cloud mobile emulator, and the videos
app.

## Where things live

- **Design spec** (whole vision): `docs/specs/2026-04-08-ace-web-design.md`
- **Other specs**: `docs/specs/` (per-feature design docs — workspaces, opp summary,
  videos editor, mobile cloud, opp-cache redesign, products contract, …)
- **Implementation plans**: `docs/plans/` (historical for shipped phases; check
  the file header for status)
- **Learnings**: `docs/learnings/` (load-bearing gotchas — read these before
  touching the relevant area)
- **Architecture docs**: `docs/architecture/cli-credentials.md`,
  `docs/architecture/mcp-surface.md`, `docs/architecture/slack-integration.md`,
  `docs/architecture/workspace-activity.md`
- **QA**: `docs/qa/e2e-probe.md` — re-runnable Playwright probe of every UI
  surface; lives at `scripts/qa/labs_probe.py`. Run it after every deploy.
- **Deploy runbook**: `docs/deploy.md`
- **Pattern source** for new backend code: `../canopy-web/` (sibling repo)
- **Project Claude helpers**: `.claude/skills/ace-web/` and `.claude/commands/ace-web/`
  (notably `ace-web:create-cli-credentials` to ship local Claude CLI auth up to a
  deployed instance)

The broader ACE plugin (CRISPR-Connect orchestration) lives in `../ace/`. ace-web is
a separate module — its design spec lives here, not there. This repo is consumed as
a git submodule from `ace`, but day-to-day work happens here.

## Vendored Claude plugins

The Docker image bundles two Claude plugins at build time so `claude -p` subprocesses
spawned by `CLIBackend` have ACE skills, slash commands, and MCP servers available.

- **ACE plugin** at `/app/vendor/ace`. The System Overview tab (`apps/system/`)
  reads skill/agent/manifest metadata from `ACE_PLUGIN_PATH`. The plugin is also
  installed at `~/.claude/plugins/cache/ace/ace/<version>/` so subprocess sessions
  see it. As of PR #177 the cache directory must be a real directory, not a
  symlink — Claude Code 2.x removes symlinks.
- **Nova plugin** at `/app/vendor/nova`. Requires OAuth 2.1 + PKCE per the
  late-2025 MCP spec; ace-web runs the dance server-side
  (`apps/auth/nova_oauth_views.py`) and stages a fresh `.mcp.json` per subprocess
  spawn with the access_token expanded. See `nova-mcp-oauth.md`.

The SA key at `$CLAUDE_PLUGIN_DATA/gws-sa-key.json` is written at container start
by `docker-entrypoint.sh` from the `ACE_DRIVE_SA_KEY_JSON` env var. The `.env` for
plugin MCPs is rendered via `op inject` at container start (see
`mcp-bootstrap-container-traps.md` for traps).

**Plugin auto-update on boot:** the image bakes the plugin at build time, but
`dimagi-internal/ace` bumps several times a day while ace-web only rebuilds on its own
merges. So `docker-entrypoint.sh` runs `scripts/refresh-ace-plugin.sh` at
container start: it shallow-clones the latest `main`, and if its `VERSION`
differs from the baked one, swaps the fresh tree into the plugin cache
(reusing baked `node_modules` when the lockfile is unchanged, else `npm install`)
and repoints `/app/vendor/ace`. Net effect — **a plain `deploy-ace-web-labs.yml`
run picks up the latest plugin on every task** (each task refreshes its own
ephemeral layer; no shared volume, scales to >1 task), no image rebuild needed.
Fully fail-safe: any error leaves the baked plugin in place. Kill-switch:
`ACE_PLUGIN_AUTO_UPDATE=false`. The System Overview tab's "update available"
banner (`apps/system/version.py`) compares the baked `VERSION` against
`raw .../ace/main/VERSION` — the same source the refresh clones, so the banner
clears once a refreshed task is serving. A faster image rebuild is still any
push to ace-web `main` (triggers `build-backend.yml`) followed by a deploy.

## Stack

- **Backend**: Django 5 + Channels 4 + Django Ninja v1.x + Pydantic v2, ASGI via
  uvicorn, `psycopg[binary]`, `httpx[http2]` for Connect OAuth, `django-environ`.
  OpenAPI 3.1 schema auto-generated at `/api/openapi.json`; Scalar UI at
  `/api/docs/`; Redoc at `/api/redoc/`. All errors return RFC 7807
  `application/problem+json`. Frontend TypeScript types are generated from the
  schema (`frontend/src/api/generated.ts`). FastMCP bridge at `/api/mcp/` exposes
  read-only opp + session tools for external MCP clients. **Observability:**
  structured JSON logs to stdout (captured by ECS `awslogs` → CloudWatch Logs
  Insights); `RequestIDMiddleware` stamps every log record with a `request_id`.
  No distributed tracing.
- **Frontend**: React 19, Vite 5, TypeScript 5, Tailwind 3.4, react-router-dom 6.
  Served via nginx sidecar container in prod, built with bun.
- **DB**: PostgreSQL (shared AWS RDS `labs-*` instance, database `ace_web`; local
  Postgres via `docker compose`).
- **Infra**: AWS ECS Fargate (cluster `labs-jj-cluster`, us-east-1) behind the
  shared connect-labs ALB (path prefix `/ace/*`). GitHub Actions with OIDC for
  deploys. AWS Secrets Manager for secrets. ECR for images.
- **Tests**: pytest + pytest-django + pytest-asyncio, in-memory SQLite for unit
  tests. Frontend tests on vitest + @testing-library/react + jsdom (`bun run test`).
  Playwright e2e under `e2e/` (separate bun workspace).
- **Pattern sources**: `../connect-labs/` (Connect OAuth), `../canopy-web/`
  (CLI backend + PTY), `../connect-search/` (DriveClient ABC).

## Project structure

```
ace-web/
├── apps/
│   ├── activity/        # Workspace Timeline aggregator
│   ├── api/             # API root (Ninja registry, MCP bridge, OpenAPI/Scalar/Redoc)
│   ├── auth/            # Custom User model + Connect OAuth + Nova OAuth
│   ├── common/          # CLI backend, channels auth, Nova auth flow, problem+json
│   ├── ingest/          # JSONL upload + cost/timing + structure aggregators + pricing
│   ├── mobile/          # Cloud emulator controller + jobs
│   ├── opps/            # ACE opp Workbench (Drive-backed) + summary page + cache
│   ├── service_accounts/ # Personal tokens
│   ├── sessions/        # Session/Message execution engine for programmatic
│   │                     # ACE runs (seeded-run, drive_turn) + structure view;
│   │                     # NOT chat — see "ace-web's own interactive chat UI
│   │                     # is retired" below
│   ├── slack/           # /ace activity slash command + async dispatcher + run threads
│   ├── system/          # System Overview tab — reads bundled plugin metadata
│   ├── videos/          # Video program editor (Drive-backed) + render orchestration
│   └── workspaces/      # Multi-tenant workspace + invites + audit log
├── config/              # Split settings (base, connectlabs, development, production, e2e, test)
├── frontend/src/        # api, components, hooks, pages, router (Vite + bun)
├── e2e/                 # Playwright smoke/regression suite (separate bun workspace)
├── tests/               # Project-level tests (asgi smoke)
├── tools/               # Walkthrough/demo helpers
├── video-production/    # connect-videos/ — Remotion renderer the videos app shells out to
├── docs/                # specs/, plans/, learnings/, architecture/, qa/, deploy.md
├── scripts/qa/          # Re-runnable Playwright probe of the deployed UI
├── infra/mobile-ami/    # Packer bake for the mobile EC2 AMI + rebake.sh
├── deploy/aws/          # task-definition.json + one-time-setup.sh
├── .github/workflows/   # build-backend, build-frontend, deploy-ace-web-labs, ci,
│                        # contract-tests, regen-openapi, typecheck,
│                        # sync-video-library-labs
└── pyproject.toml
```

The sessions data model has 5 core tables: `users`, `sessions`,
`session_participants`, `messages`, `ingest_uploads` — `drafts` and
`share_tokens` were dropped when ace-web's own interactive chat UI (co-edited
drafts, session share links) was retired in favor of canopy-hosted chat; see
"ace-web's own interactive chat UI is retired" below. `apps/workspaces/` adds
`Workspace`, `WorkspaceMembership`, `WorkspaceInvite`, and audit-log tables.
The `opps` and `videos` modules add **no ORM tables** — they read through to
Google Drive.

## Key architectural decisions

- **Auth**: Connect OAuth with PKCE, hand-rolled session-based flow ported
  from connect-labs (NOT django-allauth). Implementation in
  `apps/auth/oauth_views.py` + `apps/auth/oauth.py`. Tenant-unique session cookies
  (`sessionid_ace`, `csrftoken_ace`) and path-scoped (`/ace/`) to avoid collisions
  with scout on the shared `labs.connect.dimagi.com` host.
  `AUTH_USER_MODEL = "ace_auth.User"`. **No domain filter** — workspace
  membership is the access-control gate. `ACE_ALLOWED_EMAIL_DOMAINS` is preserved
  as a deployment safety knob (non-empty → revert to allowlisted signups).
- **Multi-tenancy via Workspaces**: ace-web is multi-tenant. The unit of tenancy
  is the **Workspace** — a name + a Drive root folder + a member list with roles
  (Owner / Editor / Viewer). All opp/session/upload/videos reads scope by
  `request.user`'s workspace memberships; non-members get 404 (not 403) so
  existence isn't leaked. Drive folder IDs are unique across workspaces. The
  founding migration seeds a single `dimagi-team` workspace from
  `ACE_DRIVE_ROOT_FOLDER_ID`; after that the env var is no longer read at runtime.
  URL structure: `/w/<slug>/opps/`, `/w/<slug>/sessions/`, etc. Onboarding wizard
  at `/welcome`, invites at `/invite/<token>`, settings at
  `/w/<slug>/workspace-settings`. **Auto-join via domain match (PR #523):**
  `Workspace.auto_join_domains` (JSONField, lowercased) — on every OAuth callback,
  users whose email domain matches a workspace's list are added
  as Editor (idempotent; never downgrades). `dimagi-team` is seeded with
  `[dimagi.com, dimagi-ai.com]` (migration 0004) plus `dimagi-associate.com`
  (migration 0006, append-only) so Dimagi staff and associate sign-ins land
  inside the workspace instead of the empty `/welcome` wizard. Owners can edit
  the list via `PATCH /api/workspaces/{slug}` or the Workspace Settings page —
  so **new auto-join migrations must APPEND, never overwrite** (0004's
  wholesale-set style predates the editable UI and would clobber operator
  edits). The auto-join role is hard-coded `editor` in
  `apps/workspaces/auto_join.py`; it is not per-domain. Spec:
  `docs/specs/2026-04-27-multi-tenant-workspaces-design.md`.
- **Automation auth on labs — Bearer PAT**: scripted tools authenticate with
  `Authorization: Bearer $ACE_WEB_PAT_TOKEN`. Per-human tokens are minted via
  the `/ace:ace-web-pat-mint` skill (one-time gh-style loopback browser flow;
  the token belongs to the authorizing human, not the `ace@dimagi-ai.com` bot
  identity). The `PersonalToken` model + `BearerTokenAuthMiddleware`
  (`apps/auth/middleware.py`) handle HTTP; `AceSessionAuthMiddleware`
  (`apps/common/channels_auth.py`) handles WebSocket Bearer auth so PAT-only
  callers can connect to Channels. For browser contexts that can't set
  custom WS headers, `POST /api/auth/pat-to-session` trades a Bearer for a
  session cookie. Reference walkthrough: `tools/walkthrough/run_chat.py`
  (**broken** since the chat-retirement PR — it drives the now-deleted chat
  WebSocket; see its module docstring)
  uses Bearer PAT end-to-end.
- **Nova MCP integration**: ace-web runs Nova's OAuth 2.1 + PKCE dance server-side
  and injects a fresh access_token into every `claude -p` subprocess so the
  bundled Nova plugin's HTTP MCP can authenticate without prompting. Auth flow in
  `apps/common/nova_auth_flow.py`; views in `apps/auth/nova_oauth_views.py`.
  Token refresh is serialized across ECS tasks via a Redis SETNX
  `nova:refresh-lock` (Better-Auth rotates refresh_tokens, so concurrent
  refreshes from sibling tasks would both fail). Bot-identity write permission
  gates on `_can_write_global`, not Django's `is_staff`. See `nova-mcp-oauth.md`
  before touching this.
- **The opp-workbench live socket (`OppConsumer`, `apps/opps/{consumers,
  routing}.py`) is the one WebSocket surface left** now that chat's own
  `SessionConsumer` is retired (see below). `channels-ws-proxy-path.md` (the
  `/ace/ws/` proxy detail) and `channels-websocket-auth.md` (the handshake
  auth pattern) still apply to it.
- **Chat is canopy-hosted, full stop** — not a flag. Session state, messages,
  drafts, presence, and turn execution for interactive chat all live in
  canopy-web; the browser talks to canopy **directly** (same-origin
  `/canopy/*` on labs; a vite proxy in dev), using the shared `canopy-ui/chat`
  kit. ace-web's own backend (`apps/canopy`) keeps exactly one
  responsibility: identity brokering. Token-exchange flow: (1) ace-web holds
  a registered canopy `AppCredential`; (2) server-side,
  `apps/canopy/client.exchange_token` trades that credential + the signed-in
  user's email for a short-lived canopy `DelegatedToken` via
  `POST {canopy}/api/auth/token-exchange`; (3) the SPA uses that token as
  `Authorization: Bearer` on canopy REST and `?token=` on the canopy chat
  WebSocket — never the app credential itself. `POST
  /api/w/{workspace_slug}/canopy/sessions` (workspace-scoped, not the flat
  `/api/canopy/sessions` an earlier draft used) additionally bakes in opp
  linkage (`opp_slug`/`opp_run_id`/`opp_step_skill` metadata) AND stamps
  `metadata.origin_key = f"ace-web:{workspace_slug}"` server-side, derived
  from the membership-checked path parameter — never from the request body —
  so canopy's session LIST (`?origin_key=`) can be scoped to one ace
  workspace instead of every ace workspace sharing the same `CANOPY_WORKSPACE`
  tenant; every ace workspace maps to one canopy workspace today, so without
  this a `team-b` member could list, and open, `team-a`'s chats).
  **Residual, not fully closed:** this scopes the LIST only — canopy's own
  tenancy still lets any member of the canopy workspace open a session
  directly by id (`GET /api/canopy-sessions/{id}`). Hard isolation requires
  mapping each ace workspace onto its own canopy workspace.
  Ops + deploy prerequisites (undocumented failure modes if any is
  missed): (1) a registered prod `AppCredential` on canopy-web (name
  `ace-web`, allowed domains matching `ACE_ALLOWED_EMAIL_DOMAINS`), its raw
  value in AWS Secrets Manager (`ace-web/canopy-app-credential`), and
  `CANOPY_APP_CREDENTIAL`'s `valueFrom` in `deploy/aws/task-definition.json`
  pointed at that secret's ARN — without it `GET /api/canopy/status` reports
  `enabled: false` and chat is unreachable (see below); (2) a canopy `Agent`
  with slug matching `CANOPY_AGENT_SLUG` (default `ace`) must exist in the
  canopy workspace named by `CANOPY_WORKSPACE` — `createCanopySession` 404s
  otherwise; (3) every ace user who uses chat must actually be a member of
  that canopy workspace (canopy auto-joins by email domain, so this is
  usually automatic, but isn't guaranteed for every domain); (4) the
  signed-in user's email domain must be in the `AppCredential`'s allowed
  domains — otherwise `token-exchange` 403s and every canopy call fails.
  None of these 404/403s are silent in the UI: `useCanopyStatus()` gates
  every chat surface (`ChatPage.tsx`'s `CanopyChatRoutePage`,
  `ChatRedirectPage`, `RecentSessionsSidebar`, `WorkbenchChatPane`) and
  degrades to a visible "chat is unreachable" message rather than rendering
  a dead page; every user-triggered canopy call (new chat, discuss-this-step)
  surfaces its error rather than swallowing it — see
  `RecentSessionsSidebar.handleNew`'s try/catch.
- **ace-web's own interactive chat UI is retired.** `apps/sessions/
  {consumers,drafts,presence,routing}.py`, the `Draft`/`ShareToken` models
  and their tables, and the frontend's `useSessionSocket`/`sessionReducer`/
  local `ChatPanel`/`MessageList`/`MessageItem`/`SendBox`/`PresenceChips`/
  `SharePopover` are all gone — canopy chat is the only interactive chat
  surface now. Old `/chat/:slug` links redirect to chat home rather than
  404ing; `/chat/:slug/structure` (the read-only structure/cost breakdown
  view, `SessionStructurePage` → `StructureTab`) is a **different, still-live
  route** that survived unchanged. `apps/sessions` itself is **not** a
  "legacy chat app" you can delete wholesale, though: `Session`/`Message`/
  `SessionParticipant`/`IngestUpload` and `turn_driver.py` (+ the CLI/API
  backend selection machinery in `apps/common`) are live production
  infrastructure for **programmatic** ACE runs — the MCP-exposed
  `apps.opps.api::seeded_run`, the `drive_turn` management command,
  Slack-triggered runs, the post-deploy `resume-interrupted` self-heal, and
  `apps.ingest`/`apps.activity`/`apps.slack` all depend on them regardless of
  whether any human is chatting interactively. See
  `apps/sessions/models.py`'s module docstring and the chat-retirement PR's
  description for the full dependency map.
- **Response envelope removed**: API errors return RFC 7807 `application/problem+json`;
  success responses return bare typed payloads. The legacy `{data, error}` envelope
  was retired in PR #352 along with DRF.
- **Rich response shapes over strict Pydantic outputs**: opps list / opp
  snapshot / runs list deliberately return `response={200: dict}` and let the
  legacy `serialize_opp_*` shape flow through unchanged. The Phase 1 attempt at
  thin Pydantic schemas (e.g. `OppCardOut` with just `{slug, title, run_count}`)
  silently dropped fields the frontend rendered (`display_name`, `tags`,
  `eval_score`, `current_run.decisions`, `phases[]`, …) and caused the
  "Something went wrong" overlay everywhere. If you tighten any of these
  endpoints, run `scripts/qa/labs_probe.py` first — it'll catch the
  consumer-side fallout.
- **Health check**: `/api/health` is public. See `docs/deploy.md`.
- **Per-session and per-opp cost & timing breakdown**: ace-web aggregates wall
  time and token costs from uploaded JSONL transcripts at ingest time, persists
  to `Session.cost_breakdown` (JSONField), and surfaces them as a rollup chip on
  the Opp Workbench. Phase / skill labels reuse `apps/system/reader.py`'s
  plugin-derived registry. Aggregator: `apps/ingest/cost_aggregator.py`; pricing
  table: `apps/ingest/pricing.py` (refresh ~twice/year). Sidechain attribution
  gotcha: `sidechain-attribution.md`.
- **Workspace Activity view** (page at `/w/<slug>/activity`, also
  `/ace activity` in Slack): cross-surface "what's running across the
  workspace right now?" view. One row per opp's most recent run,
  source-attributed via active Session lookup. **Observable-facts-only
  discipline** — no "is running" / "is alive" labels anywhere; only
  "last update Nm ago" + `ace-web` / `Drive only` source labels +
  recency-based opacity fade. Backend aggregator at
  `apps/activity/workspace_activity.py`; consumes
  `apps.opps.api.list_opp_cards`. Endpoint:
  `GET /api/w/<slug>/activity/runs`. Slack uses async `response_url`
  (Drive read can be 5-15s cold). Spec:
  `docs/specs/2026-05-16-workspace-activity-view-design.md`. Runbook:
  `docs/architecture/workspace-activity.md`. Phase view is the canonical
  drill-down — row clicks go to `?run_id=<id>`, not the Workbench.
- **Per-session Structure view** (page at `/w/<workspace>/chat/<slug>/structure`):
  hierarchical session tree (phase → skill → tool, with subagent recursion +
  parallel-group clusters). Computed fresh per request from
  `IngestUpload.raw_jsonl_gz` (gzipped raw bytes persisted at ingest time);
  never stored. Aggregator: `apps/ingest/structure_aggregator.py` (shares
  helpers with cost aggregator via `apps/ingest/_common.py`). Pre-2026-05-10
  uploads have `raw_jsonl_gz=NULL` and need re-upload via
  `/ace:upload-transcript`; the endpoint returns `schema_version=0` with
  `unavailable_reason` so the UI renders a clear hint. Spec:
  `docs/plans/2026-05-10-session-structure-view.md`.
- **Opp Workbench cache (Drive Changes API)**: opp data is read-through to Drive
  but cached long-lived. Each request polls `drive.changes.list` once (~150 ms)
  with a Redis-stored pageToken; only file_ids reported as changed invalidate
  matching `OppSnapshot` / `OppCard` cache entries. Backend serves cached
  snapshots with an ETag header; `If-None-Match` round-trips return 304. Frontend
  keeps a per-tab `Map<key, {data, etag}>` cache. Net effect: ~46-55× speedup on
  a real opp. Spec: `docs/specs/2026-05-08-opp-cache-redesign.md`. Gotchas:
  `opp-cache-architecture.md` and `opps-access-module.md`. As of PR #524 the
  same `drive_changes.observe` pattern also drives videos cache invalidation —
  videos uses a separate Redis pageToken key so opps + videos don't drain each
  other's change feeds.
- **Videos app (`apps/videos/`)**: workspace-scoped Django app for the video
  program editor. **Drive is the source of truth as of 2026-05-15**: spec.yaml
  lives in Drive under `videos/<program-slug>/runs/<run-id>/spec.yaml`; local FS
  at `ACE_VIDEOS_ROOT` is render scratch only. Ninja router at
  `/api/w/<slug>/videos/*`, service in `apps/videos/service.py`, Drive primitives
  in `apps/videos/drive.py`. Renders shell out to
  `npm run hydrate && npm run render && npm run build-clip-explorer` from
  `video-production/connect-videos/`; on success the bundled `output.mp4` +
  `explorer.tar.gz` + `feedback.md` are published back to Drive (PR #383). Read
  endpoints are MCP-exposed via `x-mcp-expose: true`. Programs declare ownership
  via a top-level `workspace: <slug>` field; non-members get 404. Slug
  validation in `service.is_valid_slug` is mandatory before any subprocess spawn.
  **Media serving**: `serve_media` honors `Range` requests (PR #507) so the
  scrubber works pre-buffer, and lazy-pulls `output.mp4` from Drive on local
  cache miss (PR #514) so a fresh ECS task or sibling worker can serve a
  render it didn't produce. MP4s are emitted with faststart (PR #502).
- **Videos beat editor (React)**: as of 2026-05-15, the per-run editor
  is a native React tree under `frontend/src/components/videos/`
  (`<BeatEditor>` + reducer + drawer). Local-buffer dirty state with
  coalescing-by-target, batched save via `POST /edit-batch` (single Drive
  round-trip, all-or-nothing). Click-to-edit drawer (DrawerShell/ModalShell
  swappable). Trim widget reimplemented with window-level pointer listeners +
  keyboard nudge. Stats (`problem`, `impact[N]`) now editable via `set-stat`
  op with tri-state source semantics. Rendered whenever `run.spec` is
  populated (post-2026-05-15 runs); the legacy `build-clip-explorer.ts`
  iframe remains only as a fallback for older runs without a parsed spec.
  Spec: `docs/specs/2026-05-15-video-beat-editor-react-port-design.md`.
  Plan: `docs/plans/2026-05-15-video-beat-editor-react-rewrite.md`.
  **Editor visual caveats** (looks like UI bugs, isn't): the rendered
  `final.mp4` opens on a black frame because Remotion's intro animation
  starts there, and the tagline text ("Pay for verified service…") that
  appears overlaid on the player is part of the rendered video content,
  not a UI element — both are visible because we now show a play
  overlay on the paused player (PR #445). Clip-slot thumbnails were
  similarly mysterious before that PR: the explorer build symlinks
  every `@alias.mp4` into `~/.cache/connect-videos/<gdriveId>.<ext>`,
  which is a host path the Django container can't follow. `serve_media`
  now handles the broken-symlink case by parsing the gdrive id out and
  refetching via the workspace SA into `<videos_root>/assets/clip-cache/`.
  The narration drawer embeds the cached TTS clip by computing the
  same hash the renderer uses (`sha256("voiceId::model::script")[:16]`,
  see `video-production/connect-videos/src/lib/voiceover.ts`); changing
  voice_id or model in spec.yaml invalidates the existing audio.
- **Video-spec templates** (`apps/videos/templates.py`): Drive-backed, editable
  template kits surfaced at `videos/templates` (gallery) and
  `videos/templates/:id` (editor with meta + example panels, batched save via
  `PATCH /api/w/<slug>/videos/templates/<id>`). A template is a **3-file kit**:
  Drive stores `<workspace-drive-root>/videos/_templates/<id>/{meta.yaml,
  prompt.md, example.spec.yaml}` (repo seed names: `template.yaml`,
  `generate.prompt.md`, `example.spec.yaml`). The **example.spec.yaml is the
  single source of truth** for the spec's shape — it's both what the BeatEditor
  edits (read-only raw-YAML view alongside) AND what the generation agent adapts
  for a new program. (The old `skeleton.yaml` — a blank spec with
  `{{placeholders}}` — was removed in the templates-drop-skeleton refactor: it
  duplicated the example's structure and drifted; an agent adapts a complete
  example more reliably than it fills a blank form. `NewProgramDialog` and the
  generate prompts now start from the example.) The `repo templates/` directory
  (in `video-production/connect-videos/`) is the canonical seed source and the
  CI fixture set for connect-videos tests — never edit those files here. Seed
  on-demand or at container start via the `videos_seed_templates` management
  command (lazy auto-seed fires on the first `GET /templates` call against an
  empty Drive folder).
- **Cloud mobile emulator (`apps/mobile/`)**: ace-web orchestrates a single EC2
  instance (`m8i.xlarge` with nested virtualization) running an Android AVD via
  SSM. Packer bake in `infra/mobile-ami/`; runtime API at `/api/mobile/*`
  (status, ensure-running, run-recipe, diagnose, …). Settings:
  `ACE_MOBILE_INSTANCE_ID`, `ACE_MOBILE_S3_BUCKET`, `ACE_MOBILE_AWS_REGION`,
  `ACE_MOBILE_AMI_VERSION`. The orchestrator is `apps/mobile/controller.EmulatorController`
  (boto3, lazy clients, framed-stdout SSM probes). **`run-recipe` is async
  (202+job_id)** to dodge ALB's 60s idle timeout; the worker thread holds the
  `mobile:emulator:lock` singleton lock through completion and writes results to
  `mobile:job:<id>` in Redis. The `/api/mobile/admin/patch-launch-script`
  endpoint is the hot-fix path; gated on `_can_write_global` and every patch
  writes a `MobileLaunchScriptPatch` audit row. **AMI rolls are one command:
  `AWS_PROFILE=labs ./infra/mobile-ami/rebake.sh`** — bakes, updates the
  launch-template, terminates+recreates the EC2 instance (AMIs are pinned at
  launch), enables nested virt, updates task-def, opens+merges PR, triggers
  deploy. `status()` caches the in-VM idle marker probe for 10s. See
  `squash-merge-stale-branch-orphans-commits.md` for the merge-method gotcha
  that lost the stop busy-guard PR.

## ACE opportunity Workbench (apps/opps)

`apps/opps/` is a read-through UI on top of Google Drive showing every skill of
an ACE run, per-step artifact previews, judge verdicts, gate history, a
run-level opp-eval scorecard + trend, a pending-gates banner, and a "Discuss in
chat" CTA (`WorkbenchChatPane`) that seeds a canopy-hosted chat session
(`createCanopySession`, title + `opp_slug`/`opp_run_id`/`opp_step_skill`
metadata) from a step's context — see "Chat is canopy-hosted, full stop"
above. The older `apps/opps/api.py::seed_chat_for_step` (`POST
.../actions/seed-chat`) still exists and still seeds an ace-web `Session` the
same way it always did, but is no longer wired to any frontend button; it's
out of scope for the chat-retirement PR (not touched, not deleted) and is
effectively dead code reachable only by a direct API/MCP call.

Drive is the source of truth — **no ORM tables** for opps / runs / steps /
artifacts. The data lives as files under `<workspace.drive_root_folder_id>/<opp-slug>/`
in Drive. The ACE plugin writes `run_state.yaml`, `pdd.md`, and skill-specific
subfolders; which skill owns which file is declared in the plugin's
`lib/artifact-manifest.ts`. ace-web parses that manifest and uses it for
file-to-skill attribution (`apps/system/parsers.py`).

**Pre-run is a valid state.** An opp folder with `idea.md` / `pdd.md` /
`opp.yaml` but no completed run (an empty `runs/` subfolder, or no
`run_state.yaml`) is a normal intermediate — the Workbench renders an empty
shell labelled "No runs yet" instead of 404ing. Fix landed in PR #390;
the loader falls through to the flat-layout reader and synthesises a
placeholder `RunDetail`. Don't tighten the loader to require a real run.

**Multi-run per opp:** Each opp is expected to have multiple runs under
`runs/run-001/`, `runs/run-002/`, … The Workbench reads them through the
multi-run reader; the run selector + URL `?run_id=…` chooses the active run. The
improvement loop is "run → inspect → chat → upgrade skill → rerun → compare
across runs".

**Skill registry is dynamic:** `apps/opps/skills.py` imports agent frontmatter
and the artifact manifest from `ACE_PLUGIN_PATH` at first access. Adding or
renaming a skill in the plugin is a one-file edit there; ace-web picks it up on
next process start.

**Identity + Drive access:** identity via the hand-rolled Connect OAuth
flow. Drive access via a single shared Google service account (the same one the
`ace` CLI uses), delivered through `ACE_DRIVE_SA_KEY_JSON` in AWS Secrets
Manager. No per-user Drive consent. See `drive-service-account.md`.

**Root folder config:** `ACE_DRIVE_ROOT_FOLDER_ID` in `config/settings/base.py`
pins the shared ACE Google Drive folder. Used at workspace-migration time only
(workspaces store their own `drive_root_folder_id`).

**Transcript ingest linkage:** `POST /api/ingest/upload` accepts optional
`opp_slug` / `opp_run_id` / `opp_step_skill` multipart fields so uploaded
transcripts from `/ace:run --ace-web-url` (via the plugin's `upload-transcript`
skill) surface under the originating opp in the Workbench's linked-chats panel.

## Learnings (read before touching the relevant area)

Infra & scaling:
- [channels-single-instance](docs/learnings/channels-single-instance.md) — resolved Phase 3; `CHANNEL_LAYERS` uses channels-redis against shared ElastiCache. Raising ECS desired count past 1 is a separate operational step.
- [channels-websocket-auth](docs/learnings/channels-websocket-auth.md) — ASGI session-cookie middleware for WebSocket handshakes; tenant-specific cookie name.
- [redis-presence-hash](docs/learnings/redis-presence-hash.md) — HASH-per-session presence with debounced Postgres writes.
- [channels-ws-proxy-path](docs/learnings/channels-ws-proxy-path.md) — `/ace/ws/` nginx proxy strips the prefix because `FORCE_SCRIPT_NAME` doesn't cover Channels routing.

Auth & identity:
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`); first-login races handled at the DB layer.
- [drive-service-account](docs/learnings/drive-service-account.md) — opps Workbench talks to Drive via a shared SA, not per-user OAuth; key JSON in `ACE_DRIVE_SA_KEY_JSON`.
- [connect-oauth-openid-email](docs/learnings/connect-oauth-openid-email.md) — Connect's token introspection returns empty `email` for HQ-linked accounts; request `openid` scope AND `response_type=token` on the token-exchange POST.
- [nova-mcp-oauth](docs/learnings/nova-mcp-oauth.md) — Nova MCP auth: RFC 8707 `resource` indicator is mandatory; `${VAR:-}` expansion in `.mcp.json` headers beats `headersHelper`; Better-Auth rotates refresh_tokens (need `nova:refresh-lock` SETNX); bot identity uses `_can_write_global` not `is_staff`.

Conversation engine:
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.
- [sse-django-async](docs/learnings/sse-django-async.md) — historical (SSE was superseded by WebSocket in Phase 3); kept for the async-cleanup patterns.
- [api-envelope-convention](docs/learnings/api-envelope-convention.md) — historical (`{data, error}` envelope retired in PR #352 alongside DRF); kept for context when grepping older code that still references the shape.
- [stream-resume-vercel-open-agents](docs/learnings/stream-resume-vercel-open-agents.md) — two stream-resume hazards: stop-during-reconnect drops the stop frame (Hazard 1, addressed); reconnect-during-stream loses up to 250ms of characters (Hazard 2, deferred).

Cost / timing / structure:
- [sidechain-attribution](docs/learnings/sidechain-attribution.md) — `apps/ingest/cost_aggregator.py` rolls subagent assistant turns into the parent skill segment via `parentUuid` → containing-message uuid match. Without this, Phase totals under-report by the cost of every Agent dispatch.

Opp Workbench (`apps/opps/`):
- [opp-cache-architecture](docs/learnings/opp-cache-architecture.md) — Drive Changes API per-request poll + long-lived `OppSnapshot` / `OppCard` cache + ETag round-trip. `workspace.pk` is a slug not an int; cold-load needs `bypass=True`; ETag is `sha256` of the serialized payload; 410 on `pageToken` clears the workspace cache; `_KEY_VERSION` must bump when `OppSnapshot` shape changes.
- [opps-access-module](docs/learnings/opps-access-module.md) — patch on `apps.opps.access.X`, not on per-view modules. Views call `access.X(...)` via attribute lookup so a single patch intercepts every caller.
- [drive-changes-api-parent-folder-blind-spot](docs/learnings/drive-changes-api-parent-folder-blind-spot.md) — Drive Changes API reports new file_ids but does NOT consistently report their parent folder as modified, so cached folder LISTINGS (`runs_summary`, `OppCard.run_count`) never invalidate when children are added externally. `apps/opps/freshness_overlays.py` is a registry of listing-derived fields that get re-listed on every cache hit (one Drive call per overlay). Add an overlay when a new cached field is listing-derived + externally-appendable; never clobber the cached value on a Drive blip.
- [run-state-vs-artifact-presence](docs/learnings/run-state-vs-artifact-presence.md) — Read step status from `run_state.yaml` content (one existing file_id, Changes API reliably reports edits), not artifact-file presence in subfolders (new child files, Changes API blind spot). PR #575 switched `_build_steps` to use `phases.<phase>.steps.<skill>.status` as the primary source; artifact-presence stays as the legacy fallback. Multi-viewer falls out for free: shared `OppSnapshot` invalidates once per agent write, every viewer hits the same fresh cache.

Slack:
- [slack-integration](docs/learnings/slack-integration.md) — `SlackConfig.ready()` runs in every management command (guard with env + sys.argv); `channel_not_found` is silent (wrapper normalises to `SlackChannelGone`); `(channel_id, ts)` must be stored together; dedup lock must be `cache.add` (SETNX); `Workspace` field is `name` not `display_name`; `bot_token` is a property (no `set_bot_token`); use `asyncio.get_running_loop()` not `get_event_loop()`.

Frontend:
- [draft-soft-lock-idle-timer](docs/learnings/draft-soft-lock-idle-timer.md) — React UIs showing wall-clock-driven transitions need explicit `setTimeout`-driven re-renders.
- [card-click-and-grid-stretch](docs/learnings/card-click-and-grid-stretch.md) — two layout traps that masquerade as React state bugs: (1) `<button>` nested in `<Link>` routes clicks ambiguously; (2) CSS Grid's default `align-items: stretch` makes collapsed neighbors visually expand.

Deploy & infrastructure:
- [alb-nginx-django-https](docs/learnings/alb-nginx-django-https.md) — `SECURE_PROXY_SSL_HEADER` + nginx `$real_scheme` map preserve the ALB's `https`; every `proxy_pass` must rewrite `Host` so ALB health checks don't trip `ALLOWED_HOSTS`.
- [mcp-bootstrap-container-traps](docs/learnings/mcp-bootstrap-container-traps.md) — (1) `op inject` parses `{{ }}` and `op://` literals inside `.env.tpl` comments and aborts; (2) `npx tsx` from a cwd without `node_modules` triggers a registry install that races Claude Code's 30s MCP connection timeout.
- [long-running-turns-vs-deploys](docs/learnings/long-running-turns-vs-deploys.md) — ECS task replacement kills in-flight `claude -p` subprocesses; Drive state is the durable source of truth. **Operational rule:** deploys and chats can run concurrently — but if you fire a deploy while a `/ace:run` (or any long chat turn) is streaming, the WebSocket will drop mid-turn. Don't avoid the deploy; resume the run from Drive once the deploy lands. For `/ace:run`, that's the `<opp>/<run-id>` form (e.g. `/ace:run bednet-spot-check/20260524-2354`) which reads the existing `run_state.yaml` and continues at the first non-`complete` phase.
- [cloud-emulator-snapshot-persistence](docs/learnings/cloud-emulator-snapshot-persistence.md) — mobile AVD snapshot/restore semantics on the EC2 host; read before touching the rebake or in-VM launcher.

QA / probe:
- [e2e-probe](docs/qa/e2e-probe.md) — `scripts/qa/labs_probe.py` walks every UI surface + cross-checks the OpenAPI schema for orphan endpoints. Re-run after every deploy: `LABS_TOKEN=... uv run --extra walkthrough python scripts/qa/labs_probe.py`. Caught three Phase-5 regressions (public summary endpoint deleted, cross-opp compare deleted, empty-runs-folder 404) that nothing else surfaced.

Repo / merge process:
- [squash-merge-stale-branch-orphans-commits](docs/learnings/squash-merge-stale-branch-orphans-commits.md) — squash-merge from a topic branch that hasn't pulled an intervening merge silently overwrites the intervening commits on `main`. Repo defense set 2026-05-12: `allow_squash_merge=false`. Don't re-enable without "Always suggest updating PR branches" + a branch-protection rule.

## Workflow

- **Local dev**: `docker compose up`. App at `http://localhost:8000`, Postgres at
  `localhost:5434`. Backend hot-reload + working Vite dev server.
- **Local Python env (one-time per worktree, REQUIRED before tests/lint).** The
  `.venv` is gitignored, so a fresh checkout/worktree has none — bare `pytest` /
  `ruff` then silently resolve to a global interpreter that's missing project
  deps (`orjson`, `django-environ`, `email-validator`, …) and fail with
  confusing `ModuleNotFoundError`s. Provision it exactly as CI does, then always
  invoke the venv binaries:
  ```bash
  uv venv --python=3.11 .venv
  uv pip install --python .venv/bin/python -e ".[dev]"
  ```
- **Tests**: `.venv/bin/pytest -v` from repo root (in-memory SQLite; fast
  hashers; ~20s for the full unit suite — no Postgres needed). Frontend:
  `bun run test` from `frontend/`. **Run this before arming auto-merge —
  `pytest + ruff` is NOT a required check, so a red suite can still auto-merge.**
- **Post-deploy probe**: `LABS_TOKEN=... uv run --extra walkthrough python
  scripts/qa/labs_probe.py` — walks every UI surface on labs + cross-checks the
  OpenAPI schema for orphan endpoints. ~90s for ~40 steps. Writes
  `qa-results/<UTC-iso>/report.{json,md}` + per-step PNGs. See
  `docs/qa/e2e-probe.md`.
- **Lint**: `.venv/bin/ruff check .` — `line-length=100`, `target=py311`, rules `E,F,W,I,UP,B`.
- **Typecheck**: `basedpyright` (CI-gated). Frontend: `bunx tsc -b` (stricter
  than `tsc --noEmit`; Docker build uses this).
- **Deploy**: GitHub Actions workflow `.github/workflows/deploy-ace-web-labs.yml`.
  Manual trigger (Actions → Deploy to Labs (AWS) → Run workflow). Set
  `run_migrations: true` on schema-changing deploys. First-time setup:
  `deploy/aws/one-time-setup.sh`. See `docs/deploy.md` for the full runbook.

## What does NOT ship yet

- Stream-reconnect Hazard 2 (reconnect-during-stream gap, up to 250ms char loss)
  is documented but **deferred** until observed in real user reports. See
  `stream-resume-vercel-open-agents.md`.
- Phase 5 of the original ace-web design (observability eval harness, a11y pass,
  full security review, demo prep) is deferred indefinitely — revisit if a
  specific pain point surfaces. Don't propose it as planned work.
- Per-user CLI tokens (currently one global SystemConfig row).
