# CLAUDE.md — ace-web

Agent context for the ACE web harness. Read this at the start of every session.

`ace-web` is Module 1 of the ACE initiative: the opp Workbench that runs and observes
ACE's own agent work (via Claude, driven through the local CLI or API), with
persistent transcripts and upload support for existing local `.jsonl` sessions.
Phases 1–4 of the original design spec shipped (foundation, conversation engine,
multi-player, library/ingest); Phase 5 (Polish) is deferred indefinitely. Interactive
chat moved out to canopy-hosted chat (canopy-web) — ace-web's own multi-player
WebSocket chat UI was retired; see "Chat is canopy-hosted, full stop" below. Active
surfaces in 2026-09 are the opp Workbench (Phases/Runs/Review tabs + run replay), the
public run summary, the cloud mobile emulator, and the videos app.

## Where things live

- **Design spec** (original whole vision — historical; its GCP/IAP and
  ace-web-hosted-chat parts were superseded): `docs/specs/2026-04-08-ace-web-design.md`
- **Other specs**: `docs/specs/` (per-feature design docs — workspaces, opp summary,
  videos editor, mobile cloud, opp-cache redesign, products contract, …)
- **Implementation plans**: `docs/plans/` (historical for shipped phases; check
  the file header for status)
- **Learnings**: `docs/learnings/` (load-bearing gotchas — read these before
  touching the relevant area)
- **Archive**: `docs/archive/` — learnings/plans/specs for code that no longer
  exists (retired chat stream, `{data, error}` envelope, …). Not guidance;
  `docs/archive/README.md` says why each was archived.
- **Architecture docs**: `docs/architecture/cli-credentials.md` (per-user
  `UserCredential` blobs, shipped PR #117, with the global `SystemConfig` row as
  fallback), `docs/architecture/mcp-surface.md`, `docs/architecture/slack-integration.md`,
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
**In prod those subprocesses are the fallback path, not the main one:** with
`CANOPY_RUN_EXECUTION=true` (set in `deploy/aws/ace-web.cfn.yaml` since 2026-07-28)
programmatic runs execute on canopy's cloud runner — see "Programmatic runs execute
on canopy" below. The baked plugin still feeds the System Overview tab and the
flag-off / local path.

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
  Served via nginx sidecar container in prod, built with bun. Canopy SDK packages
  from npm (unscoped): `canopy-ui` (shared chat + presence kit) and `canopy-client`
  (token store / REST / WS primitives, adopted in PR #779). **ace-web runs the
  NEWEST of both, automatically**: canopy-web publishes on merging a version
  bump; Dependabot here checks daily and opens one grouped PR
  (`.github/dependabot.yml`); `canopy-sdk-automerge.yml` runs the frontend gate
  (tsc + vitest + build — not a required check here, which is why it runs it
  itself) and only then arms auto-merge. Pins stay EXACT on purpose: with a
  lockfile a range would not update anything by itself, and exact means every
  version ace-web runs passed its CI. One manual edge: `main protection` is
  strict, so a bump PR that main overtakes while its checks run sits behind —
  click "Update branch" or comment `@dependabot rebase` (a workflow cannot do
  either usefully: Dependabot ignores bot comments, and a GITHUB_TOKEN push
  runs no CI).
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
│   ├── canopy/          # canopy identity brokering (token exchange), workspace-scoped
│   │                     # session create, run_dispatch (runs → canopy Turns)
│   ├── common/          # CLI backend, channels auth, Nova auth flow, problem+json
│   ├── ingest/          # JSONL upload + cost/timing + structure aggregators + pricing
│   ├── mobile/          # Cloud emulator controller + jobs
│   ├── opps/            # ACE opp Workbench (Drive-backed) + summary page + cache
│   ├── presence/        # Cross-app viewer presence (ws/presence/ + Redis HASH store)
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
├── frontend/src/        # api, canopy, components, hooks, pages, presence, router
├── e2e/                 # Playwright smoke/regression suite (separate bun workspace)
├── tests/               # Project-level tests (asgi smoke)
├── tools/               # Walkthrough/demo helpers
├── video-production/    # connect-videos/ — Remotion renderer the videos app shells out to
├── docs/                # specs/, plans/, learnings/, architecture/, qa/, deploy.md
├── scripts/qa/          # Re-runnable Playwright probe of the deployed UI
├── infra/mobile-ami/    # Packer bake for the mobile EC2 AMI + rebake.sh
├── deploy/aws/          # ace-web.cfn.yaml (task def + service) + ace-mobile.cfn.yaml
│                        # (the mobile emulator's EC2/S3/IAM, imported 2026-09)
├── .github/workflows/   # build-backend, build-frontend, deploy-ace-web-labs, ci,
│                        # contract-tests, regen-openapi, typecheck, frontend,
│                        # videos, sync-video-library-labs, canopy-contract-drift
└── pyproject.toml
```

The sessions data model has 5 core tables: `users`, `sessions`,
`session_participants`, `messages`, `ingest_uploads` — `drafts` and
`share_tokens` were dropped when ace-web's own interactive chat UI (co-edited
drafts, session share links) was retired in favor of canopy-hosted chat; see
"ace-web's own interactive chat UI is retired" below. `apps/workspaces/` adds
`Workspace`, `WorkspaceMembership`, `WorkspaceInvite`, and audit-log tables.
Drive is the source of truth for opp and video **content**: `opps` keeps only a
thin `OppWorkspace` wrapper row (display name, working session), and `videos` keeps
a Postgres library index (`VideoLibraryEntry`/`VideoSnippet`/`AudioLibraryEntry`)
that is reconstructible from Drive via `videos_sync_library --direction=import`.
`presence` adds one `PresencePreference` row per user.

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
  session cookie. (`tools/walkthrough/run_chat.py`, the old Bearer-PAT
  walkthrough over ace-web's own chat WebSocket, was deleted with that
  WebSocket; don't recreate it against canopy's chat socket — that drives a
  different service's execution and tests the wrong thing.)
- **Nova MCP integration**: ace-web runs Nova's OAuth 2.1 + PKCE dance server-side
  and injects a fresh access_token into every `claude -p` subprocess so the
  bundled Nova plugin's HTTP MCP can authenticate without prompting. Auth flow in
  `apps/common/nova_auth_flow.py`; views in `apps/auth/nova_oauth_views.py`.
  Token refresh is serialized across ECS tasks via a Redis SETNX
  `nova:refresh-lock` (Better-Auth rotates refresh_tokens, so concurrent
  refreshes from sibling tasks would both fail). Bot-identity write permission
  gates on `_can_write_global`, not Django's `is_staff`. See `nova-mcp-oauth.md`
  before touching this.
- **Two WebSocket surfaces remain** now that chat's own `SessionConsumer` is
  retired (see below): the opp-workbench live socket (`OppConsumer`,
  `apps/opps/{consumers,routing}.py`, `ws/opps/<slug>/[runs/<run>/]`) and
  cross-app viewer presence (`PresenceConsumer`, `apps/presence/`,
  `ws/presence/`). Both are mounted in `config/asgi.py`;
  `channels-ws-proxy-path.md` (the `/ace/ws/` proxy detail) and
  `channels-websocket-auth.md` (the handshake auth pattern) apply to both.
- **Cross-app viewer presence** (PR #699, spec
  `docs/specs/2026-07-27-cross-app-presence-design.md`): the Google-Docs-style
  "who else is viewing" badge, one shared `canopy-ui/presence` React module with
  a per-app Channels backend writing to that app's own Redis
  (`apps/presence/store.py`, HASH per page key). Rules that carry the security
  weight: the page key is CLIENT-SUPPLIED, so its workspace segment is checked
  against memberships LIVE on every `presence.enter` (never cached for the
  socket's life); `show_presence=False` is enforced server-side only; page keys
  are hashed before use as Channels group names (`:`/`/` are illegal there).
  Heartbeat 20s / field TTL 60s / key TTL 120s are tuned together — don't
  change one alone. Every failure degrades to "badge renders nothing".
- **Chat is canopy-hosted, full stop** — not a flag. Session state, messages,
  drafts, presence, and turn execution for interactive chat all live in
  canopy-web; the browser talks to canopy **directly** (same-origin
  `/canopy/*` on labs; a vite proxy in dev), using the shared `canopy-ui/chat`
  kit. ace-web's own backend (`apps/canopy`) keeps exactly one
  responsibility: **acting as the person whose command it is carrying
  out**. ace-web is a canopy **Connected site**: (1) it holds an Ed25519
  private key (`CANOPY_SIGNING_KEY`); canopy holds only the public half on
  its `ace-web` site row, so canopy's database contains nothing that can
  impersonate anyone; (2) server-side, `apps/canopy/client.act_as(email)`
  signs a 60-second, single-use assertion naming that person and trades it at
  `POST {canopy}/api/auth/contact-token` for a short-lived token; (3) the SPA
  uses that token as `Authorization: Bearer` on canopy REST and `?token=` on
  the canopy chat WebSocket — never the signing key. **Who that person is, is
  canopy's answer, not ours**: an existing canopy user at one of the site's
  resolvable domains arrives as THEMSELVES (their own ACL); anyone else
  arrives as a **contact** — a real principal with its own surface
  (`/api/contact/…`), not a degraded user, and never a newly created account.
  `client.Principal` is that answer, and it routes every later call to the
  right surface, so nothing else in ace-web branches on it. **There is no
  fallback identity**: a run whose owner has no email is refused
  (`DispatchError`), because a run attributed to someone else is a run that
  lies about who asked. This replaced `CANOPY_APP_CREDENTIAL` + token-exchange,
  a shared secret that minted a token for any address in ace-web's allowed
  domains and JIT-created the canopy user as a side effect.
  `POST
  /api/w/{workspace_slug}/canopy/sessions` (workspace-scoped, not the flat
  `/api/canopy/sessions` an earlier draft used) additionally bakes in opp
  linkage (`opp_slug`/`opp_run_id`/`opp_step_skill` metadata) AND stamps
  `metadata.origin_key = f"ace-web:{workspace_slug}"` server-side, derived
  from the membership-checked path parameter — never from the request body —
  so canopy's session LIST (`?origin_key=`) can be scoped to one ace
  workspace instead of every ace workspace sharing the same `CANOPY_WORKSPACE`
  tenant; every ace workspace maps to one canopy workspace today, so without
  this a `team-b` member could list, and open, `team-a`'s chats).
  **By-id reads are closed upstream too** — do NOT go build per-workspace
  canopy tenancy for isolation. canopy-web#749 (2026-09-17) gave canopy's list
  and `GET /api/canopy-sessions/{id}` ONE visibility predicate
  (`apps/canopy_sessions/access.py::visible_session_q` in canopy-web: creator,
  participant, or a bound runner-discovered session), so a co-tenant holding a
  session UUID can't read that chat. `origin_key` is still ours and still
  required for LIST scoping.
  Ops + deploy prerequisites (undocumented failure modes if any is
  missed): (1) the `ace-web` **Connected site** on canopy-web must carry our
  PUBLIC key, the `connect` workspace, `resolvable_domains` covering
  `ACE_ALLOWED_EMAIL_DOMAINS`, and agent `ace`; the private half lives in AWS
  Secrets Manager (`ace-web/canopy-signing-key`) with `CANOPY_SIGNING_KEY`'s
  `ValueFrom` in `deploy/aws/ace-web.cfn.yaml` pointed at it — without it
  `GET /api/canopy/status` reports `enabled: false` and chat is unreachable;
  (2) a canopy `Agent` with slug matching `CANOPY_AGENT_SLUG` (default `ace`)
  must exist in the workspace named by `CANOPY_WORKSPACE` —
  `createCanopySession` 404s otherwise; (3) `aud` must match: we sign
  `CANOPY_BASE_URL` (override with `CANOPY_ASSERTION_AUDIENCE`) and canopy
  verifies against its own public URL, so a canopy rename breaks every
  assertion in flight; (4) a domain NOT in the site's `resolvable_domains`
  still works — those people arrive as contacts rather than as their canopy
  account, which is a narrower ACL, not an error.
  None of these 404/403s are silent in the UI: `useCanopyStatus()` gates
  every chat surface (`ChatPage.tsx`'s `CanopyChatRoutePage`,
  `ChatRedirectPage`, `RecentSessionsSidebar`, `WorkbenchChatPane`) and
  degrades to a visible "chat is unreachable" message rather than rendering
  a dead page; every user-triggered canopy call (new chat, discuss-this-step)
  surfaces its error rather than swallowing it — see
  `RecentSessionsSidebar.handleNew`'s try/catch.
- **ace-web's view of canopy's API is GENERATED, not hand-written.**
  `frontend/src/api/canopy-generated.ts` comes from canopy-web's own OpenAPI
  schema via `npm run gen:canopy-api` (`frontend/scripts/gen-canopy-contract.mjs`).
  Before this, `canopy/api.ts` hand-mapped canopy's responses — 27 unchecked
  primitive casts with manual renames (`status` -> `live_status`,
  `last_activity_at` -> `updated_at`) — while canopy-web's OWN frontend read the
  identical endpoints through generated types. Two descriptions of one contract,
  one of them unchecked, and it had already cost a production bug: comparing
  `Runner.live_status` against `"ONLINE"` (the Python constant's NAME, not its
  lowercase VALUE) made every runner look offline and mis-fired the placement
  banner on every chat. Now 0 casts; a rename is a compile error.
  **The `CONSUMED` allowlist in that script is the contract surface** — canopy's
  full schema is 208 paths / 322 schemas (~17,900 generated lines), so it prunes
  to the 11 operations ace-web actually calls (905 lines). Calling a new canopy
  endpoint means adding a line there, which is the right moment to notice the
  coupling widening. A listed operation that canopy no longer serves is FATAL,
  deliberately: a silent skip would regenerate smaller, pass `tsc`, and 404 at
  runtime. One thing the contract cannot check — `EmdashSessionOut.recent_messages`
  is `readonly unknown[]` in canopy's own schema, so the `.text` read is narrowed
  explicitly in `listActiveRuns` and is the one unverified field on that path.
  Drift is caught by `.github/workflows/canopy-contract-drift.yml`, which runs
  **daily, not on PRs** — regenerating needs the deployed schema over the
  network, so as a required check a canopy deploy could block an unrelated
  ace-web PR. The transport underneath (`canopy/{token,api,ws,client}.ts`)
  builds on the `canopy-client` npm package's primitives (`createTokenStore` /
  `createRest` / `buildSessionWsUrl`, PR #779) — deliberately not its bundled
  client, because `CanopyChatPanel` needs `get(force)` to rate-limit forced
  token refreshes on reconnect. What stays ours: `createCanopySession` (the
  server-stamped `origin_key` path) and the `/api/harness/*` reads the package
  doesn't model.
- **The Workbench tells the agent what is on screen (page state).** A canopy
  session's `metadata` (`opp_slug`/`opp_run_id`/`opp_step_skill`) is stamped
  once at create and then FROZEN, so before this the agent kept answering about
  the step a chat was opened on — pick another step or another run and it was
  confidently discussing a screen the reader had left. canopy's page contract
  (2026-09-16) replaces that: `PUT /api/canopy-sessions/{id}/page-state` holds
  a live declaration the agent re-reads on demand via its own `current_page`
  MCP tool, plus a copy folded into the first message so turn one does not race
  the MCP connection. ace-web's half is `canopy/usePageState.ts`
  (`useCanopyPageState`) + `declareCanopyPageState` in `canopy/api.ts`, wired
  into `WorkbenchChatPane`. **This is plain REST on the session with the
  delegated token ace-web already mints — it needs no iframe, no widget, and no
  change to `CanopyChatPanel`.** Three rules it must keep: it declares the
  SELECTION (ids + `backing_tool`, the MCP tool that resolves them), never the
  rows — canopy refuses a declaration over 8 KiB with `too_large` precisely to
  enforce that, and sending rows would duplicate our own API, go stale between
  render and send, and add a second place to get access control wrong; a failed
  declaration is non-fatal (the agent knows less, the chat still works); and
  only one PUT is ever in flight, because canopy replaces wholesale and a slow
  PUT for the previous step landing last restores the exact staleness this
  exists to remove. `backing_tool` must name a REAL MCP tool — today
  `apps_opps_api_get_step`, the operationId FastMCP derives from
  `GET /api/w/{ws}/opps/{slug}/steps/{skill}`; a name that resolves to nothing
  is worse than sending none, because the agent will try it.
- **`page.invalidate` is NOT wired, and that is a finding rather than a gap.**
  canopy's page contract has a third limb beside state and actions: a
  `page.invalidate` WS frame telling a page its data moved, which canopy's own
  `/insights` consumes through `useResource`. It does not apply to ace-web, and
  checking why is cheaper than discovering it half-built. canopy raises these at
  the MODEL layer — `invalidation.mark_dirty` is called from Django `post_save`/
  `post_delete` receivers on canopy's OWN rows, and `sessions_showing` matches
  `page_state__resource` EXACTLY. Grep it: the only producer in canopy is
  `apps/projects/signals.py` raising `insight://`. **ace-web's opp data is in
  Google Drive**, written by agents through Drive, which canopy has no model,
  no signal and no knowledge of — so nothing can ever publish `opp://…` and a
  handler for it would be dead code that reads as live. ace-web already has the
  right mechanism for this anyway: the Drive Changes API poll behind the opp
  cache (`opp-cache-architecture.md`). Making the two meet would mean ace-web
  becoming a *producer* of canopy invalidations, which needs an API surface
  canopy does not expose (`mark_dirty` is internal) plus an answer to "who may
  tell whom to refresh" — a design question, not a wiring job.
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
  Slack-triggered runs (`apps/slack/run_starter.py` creates a pending
  assistant turn and dispatches it — see below),
  the post-deploy `resume-interrupted` self-heal, and
  `apps.ingest`/`apps.activity`/`apps.slack` all depend on them regardless of
  whether any human is chatting interactively. See
  `apps/sessions/models.py`'s module docstring and the chat-retirement PR's
  description for the full dependency map.
- **Programmatic runs execute on canopy, not in this container.** Every run
  caller (`seeded_run`, Slack `/ace run`, session resume) goes through ONE seam,
  `apps.canopy.run_dispatch.start_turn(assistant_message_id)`: with
  `CANOPY_RUN_EXECUTION` on (it is `true` in `deploy/aws/ace-web.cfn.yaml` since
  2026-07-28) it enqueues a **session-targeted** canopy Turn (never agent-
  targeted — `one_executing_turn_per_agent` would serialize every ACE run in the
  fleet) that canopy's cloud runner executes; off, it falls back to
  `turn_driver.start_turn_subprocess` (local `claude -p` via `CLIBackend`).
  Monkeypatch `apps.sessions.turn_driver.start_turn_subprocess`, not
  `run_dispatch`, in tests. Plan: `docs/plans/2026-07-26-run-convergence-ace-side.md`.
  **Active runs** (`frontend/src/components/ActiveRuns.tsx`, PRs #755/#756) shows
  in-progress ACE runs however they started (inbound email, schedule, laptop),
  reading canopy's `/api/harness/sessions` feed PLUS turn events — the harness
  feed alone is emdash-derived and structurally blind to the cloud runner.
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
- **Run replay** (a mode of the Workbench's Phases screen, not a separate
  page): **Replay this run** is a STEP-THROUGH of a saved run, one beat at a
  time — entering a phase, starting a skill, finishing one. **→ / ←** step,
  **Play** advances one step every 1.5s, **R** starts over, **Esc** exits. The
  open phase follows the cursor; phases/skills not yet reached dim; the current
  skill is ringed and auto-expanded. **Nothing the cursor hasn't reached may be
  shown**: `asOfCursor` withholds verdict, QA, artifacts and preview, and every
  surface that SUMMARISES steps (phase tiles' "n/m done" + mean, the panel
  header) must read the as-of-cursor map `shownStepsByPhase`, not the real one —
  an unreached tile once announced "5/6 done · 74/100". `isPhaseRunning` stays
  on REAL steps (it locks decision editing during a live run). **Deliberately
  no clock and nothing time-proportional**: runs span many hours with long idle
  gaps (one phase of `hh-poverty-targeting/20260722-1341` holds 82% of its
  elapsed time), so timed playback spends most of its length showing nothing
  change. The step track under the controls gives every phase an EQUAL share of
  the width (its steps subdivide it) — step-proportional widths squeezed short
  phases until their names were cut off. Off by default and lazily fetched; once on, it warms every step's
  detail in the background. Backend: `apps/opps/replay.py` at
  `GET /api/w/<ws>/opps/<slug>/runs/<run>/replay` — it still computes timing
  fields (`timing_source`, `phase_timings`, the time-ledger act) that the UI no
  longer reads; left in place because removing `RunDetail.phase_timings` would
  need another `_KEY_VERSION` bump and a global cold-cache. Phase colours are
  `--replay-phase-1..10` at `:root`/`.dark`. Frontend:
  `frontend/src/components/replay/`. Spec + why it isn't a standalone player:
  `docs/specs/2026-09-17-ace-demo-player-design.md` (see the addenda).
- **Run compare** (`/w/<ws>/opps/<slug>/compare?base=<run>&head=<run>`; tick two runs
  on the Runs tab): "What the later run did differently" — new decisions, decisions
  answered differently, new checks, then (collapsed) anything dropped and a plain
  per-step verdict table. **Deliberately leads with what's NEW, not scores**: on
  `hh-poverty-targeting` the run after an outside review passed FEWER of its own
  checks (24 vs 31, +6 warn, +2 fail) because its graders got stricter — a
  score-delta view puts a red arrow on the better run. The verdict table shows each
  run's verdict plainly with no better/worse framing. Says WHAT changed, never WHY
  (ACE changes for many reasons between runs). Answers are compared ignoring case,
  spacing and trailing punctuation ("weekly" -> "Weekly" is not a change).
  `load_run_compare` checks the loaded run id matches the requested one, because
  the snapshot loader falls back to the latest run for an unknown id. Backend
  `apps/opps/run_compare.py` (pure, over two cached rich snapshots). Replaced the
  old unused multi-run `/compare?run_ids=` endpoint and `OppCompareOut`.
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
  deploy. The emulator's AWS resources (instance, launch template, SG, IAM,
  `ace-mobile-artifacts-labs` bucket — `DeletionPolicy: Retain`, never replace)
  are owned by the `ace-mobile` CloudFormation stack
  (`deploy/aws/ace-mobile.cfn.yaml`, adopted by resource import 2026-09; the old
  laptop-state Terraform is deleted). `rebake.sh` still rolls the AMI via the AWS
  CLI directly — **after a rebake, update the stack's `AmiId` parameter** or the
  next drift check flags it. `status()` caches the in-VM idle marker probe for 10s. See
  `squash-merge-stale-branch-orphans-commits.md` for the merge-method gotcha
  that lost the stop busy-guard PR.

## ACE opportunity Workbench (apps/opps)

`apps/opps/` is a read-through UI on top of Google Drive showing every skill of
an ACE run, per-step artifact previews, judge verdicts, gate history, a
run-level opp-eval scorecard + trend, a pending-gates banner, and a "Discuss in
chat" CTA (`WorkbenchChatPane`) that seeds a canopy-hosted chat session
(`createCanopySession`, title + `opp_slug`/`opp_run_id`/`opp_step_skill`
metadata) from a step's context — see "Chat is canopy-hosted, full stop"
above.

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
`runs/<run-id>/` (timestamped ids like `20260824-1404`). The Workbench reads them
through the multi-run reader; the run selector + URL `?run_id=…` chooses the
active run, and the **Runs tab** (`components/opps/RunsTable.tsx`, PR #727) shows
one row per run with a per-phase track and deep links (public summary, Drive
folder, workbench). The improvement loop is "run → inspect → chat → upgrade
skill → rerun → compare across runs".

**Public run summary** (`apps/opps/summary.py`, served anonymously by
`public_summary_router` at `GET /api/opps/public/<ws>/<opp>/runs/<run>/summary`):
the partner-facing review page. Its payload is frozen as an external contract
(PR #723 — change it deliberately). Beyond the build memo, decisions and open
questions (see the `public-summary-*` learnings), it renders a **Deep QA**
section only when `/ace:qa-deep` actually ran (read from Drive by path, not
`run_state.yaml`, because qa-deep writes nothing there — PR #746) and the run's
frozen **claim set**, "What changed because you asked" (verdicts
`MET`/`UNMET`/`NOT REACHED`/`INDETERMINATE` from the plugin's
`lib/run-claims.ts`; an unknown verdict is carried as "no verdict", never
coerced — PR #773). Audit it anonymously (`/ace:run-surface-audit`) before
sending anyone the URL.

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
- [channels-single-instance](docs/learnings/channels-single-instance.md) — resolved Phase 3; `CHANNEL_LAYERS` uses channels-redis against shared ElastiCache. The service now runs `DesiredCount: 2` (`deploy/aws/ace-web.cfn.yaml`), so any new in-process state must be cross-task safe.
- [channels-websocket-auth](docs/learnings/channels-websocket-auth.md) — ASGI session-cookie middleware for WebSocket handshakes; tenant-specific cookie name. Written for the retired `SessionConsumer`; the pattern is what `OppConsumer` + `PresenceConsumer` use today.
- [redis-presence-hash](docs/learnings/redis-presence-hash.md) — HASH-per-key presence with debounced Postgres writes. Its original home (`apps/sessions/presence.py`) was retired with chat; the HASH + TTL pattern, the fakeredis import-the-module rule, and the known race it documents carry over to `apps/presence/store.py`.
- [channels-ws-proxy-path](docs/learnings/channels-ws-proxy-path.md) — `/ace/ws/` nginx proxy strips the prefix because `FORCE_SCRIPT_NAME` doesn't cover Channels routing.

Auth & identity:
- [user-google-sub-nullable](docs/learnings/user-google-sub-nullable.md) — `google_sub` must be NULL (not `""`); first-login races handled at the DB layer.
- [drive-service-account](docs/learnings/drive-service-account.md) — opps Workbench talks to Drive via a shared SA, not per-user OAuth; key JSON in `ACE_DRIVE_SA_KEY_JSON`.
- [connect-oauth-openid-email](docs/learnings/connect-oauth-openid-email.md) — Connect's token introspection returns empty `email` for HQ-linked accounts; request `openid` scope AND `response_type=token` on the token-exchange POST.
- [nova-mcp-oauth](docs/learnings/nova-mcp-oauth.md) — Nova MCP auth: RFC 8707 `resource` indicator is mandatory; `${VAR:-}` expansion in `.mcp.json` headers beats `headersHelper`; Better-Auth rotates refresh_tokens (need `nova:refresh-lock` SETNX); bot identity uses `_can_write_global` not `is_staff`.

Conversation engine:
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.

Cost / timing / structure:
- [sidechain-attribution](docs/learnings/sidechain-attribution.md) — `apps/ingest/cost_aggregator.py` rolls subagent assistant turns into the parent skill segment via `parentUuid` → containing-message uuid match. Without this, Phase totals under-report by the cost of every Agent dispatch.

Opp Workbench (`apps/opps/`):
- [opp-cache-architecture](docs/learnings/opp-cache-architecture.md) — Drive Changes API per-request poll + long-lived `OppSnapshot` / `OppCard` cache + ETag round-trip. `workspace.pk` is a slug not an int; cold-load needs `bypass=True`; ETag is `sha256` of the serialized payload; 410 on `pageToken` clears the workspace cache; `_KEY_VERSION` must bump when `OppSnapshot` shape changes.
- [opps-access-module](docs/learnings/opps-access-module.md) — patch on `apps.opps.access.X`, not on per-view modules. Views call `access.X(...)` via attribute lookup so a single patch intercepts every caller.
- [drive-changes-api-parent-folder-blind-spot](docs/learnings/drive-changes-api-parent-folder-blind-spot.md) — Drive Changes API reports new file_ids but does NOT consistently report their parent folder as modified, so cached folder LISTINGS (`runs_summary`, `OppCard.run_count`) never invalidate when children are added externally. `apps/opps/freshness_overlays.py` is a registry of listing-derived fields that get re-listed on every cache hit (one Drive call per overlay). Add an overlay when a new cached field is listing-derived + externally-appendable; never clobber the cached value on a Drive blip.
- [public-summary-embed-key](docs/learnings/public-summary-embed-key.md) — the public per-run summary serves the OCS `embed_key` anonymously. Accepted, documented exposure: the widget authenticates client-side, so any key it can use is readable by the page's reader; dropping it deletes the "Need help?" assistant. Real fixes are OCS-side (server-minted session token, or origin-locked keys + rate limits).
- [public-summary-link-access](docs/learnings/public-summary-link-access.md) — gated links on the public run summary are SHOWN and tagged `admin only`, never hidden (Jonathan, 2026-08-14: "nothing is 'Dimagi only' at scale for ACE"). Access is a property of the payload — each reader in `apps/opps/summary.py` declares `access` for the link it produced; `viewer.is_member` only decides whether the page draws the tag. Don't reintroduce a flag that changes WHICH links are served. The public summary also carries the CONTENT of `decisions.yaml` + `open-questions.md` (the review surface), because those two docs are never shared — and of the run's **build memo** (`products.connect.build_memo`, ace-web#767), rendered first on the Overview because the PDD makes it the review artifact. The memo body is the Drive `text/markdown` export passed through VERBATIM (tables survive; the plain export flattens them) — never `unescape_markdown` it, the page's CommonMark renderer resolves the escapes.
- [public-summary-reactions](docs/learnings/public-summary-reactions.md) — a partner can react to ONE decision row on the public summary. Reactions are written as `skills/feedback-ledger` records (`ACE/<opp>/feedback/<YYYYMMDD>-public-<reviewer>.yaml`), NOT as gate decisions and NOT as `decision-overrides.yaml` — an anonymous self-asserted name must not rewrite the next run's inputs. The `public` slug marker is load-bearing: it keeps privately-captured reviews in the same folder off a page anyone can open. Public write endpoint ⇒ rate limits, length caps, HTML rejected.
- [public-summary-editing](docs/learnings/public-summary-editing.md) — decision rows on the public summary are EDITABLE by anyone with the link (Jonathan, 2026-08-14: "reviewer 2 can change / update reviewer 1 anyways in the UI, and that should just be the same as Dimagi going in and updating things on top of the anonymous input"). This reverses #710's guard. Edits write the SAME `inputs/decision-overrides.yaml` the Workbench writes, through the same merge/serializer/editor component — the surfaces differ only in identity resolution (signed in ⇒ never anonymous; else a required self-reported name) and in staging (Workbench buffers, public writes through). Safety is attribution + history + undo, NOT permission; keep `schema_version: 1` and add fields only. **Commit mode follows IDENTITY, not surface** — `confirm` only while we don't yet know who is editing; a returning or signed-in reviewer edits click-and-done like the Workbench (copy is a separate `voice` axis). **Phase is the organising structure of the decisions tab**, matching the Workbench; the flagged rows are surfaced by a jump list, never by a second rendering.
- [drive-prose-export](docs/learnings/drive-prose-export.md) — everything ACE writes to Drive is a GOOGLE DOC, and the default `text/plain` export drops `**bold**`/`#` and turns `-` bullets into `*`. Read prose (`*.md`) with `export_as="text/markdown"` via `apps/opps/drive_export.read_prose` (which also unescapes markdown's `\+`). **Name-gated, never global** — `run_state.yaml` / `decisions.yaml` / verdicts are Google Docs too and a markdown export escapes their YAML.
- **A fork DOES carry each copied phase's `products` block** (ace#1888). The forker synthesizes run_state rather than copying it — right for statuses, wrong for the one key that is a typed HANDOFF. Without it a fork is a convincing shell: every pre-fork phase reads `done`, every artifact is present, `fork/status` says `done` — and the first phase that runs cannot find the Connect opportunity those artifacts describe. Only `done` phases carry it; a phase at/after the fork mints its own. Best-effort read, so an unreadable source run_state still forks.
- **A SKILL fork carries the fork phase's earlier STATE, not just its files** (ace#2341). The artifact trim keeps files from skills below the fork skill; until this fix the phase's `run_state` block still reset to `pending` / `products: {}`, so the kept work was orphaned — the re-run redid it and three Phase-7 gates that read `products.synthetic.*` went quiet. `_skill_fork_phase_block` now carries `steps.<skill>` for lower-ordinal skills verbatim (a `<producer>-qa` / `-eval` companion follows its producer; a step the registry cannot place is DROPPED and named — the opposite of the file rule, because a stray `done` skips work while a stray file only costs a copy), resets the fork skill and later to `pending`, sets `status: in_progress` with `verdict` / `completed_at` / `summary_artifact` OMITTED (the validator rejects `verdict: null`), and writes a `fork_note`. `products` are carried WHOLE and marked UNATTRIBUTED because the plugin declares no product-key → skill map (`skills.product_producers` is the seam; `products.synthetic` is one block written by three skills, so even a top-level map could not split it) — never dropped silently, never guessed; the one derivable case, a fork at a phase's first skill, drops them. The endpoint echoes `OppForkOut.carried` and the fork's system turn records the same payload. Phase forks are unchanged.
- **A fork does NOT carry a pre-fork phase's `screenshots/` or `videos/` subtree** (ace-web#758). They are device-walk evidence nothing at a later phase reads, they were the majority of a 178-file Phase-7 fork, and the training deck references them by file ID into the SOURCE run, which a fork never deletes from. Scoped to phases strictly before the fork point, so a skill fork of the walk's own phase keeps them. `_MEDIA_SUBTREES_SKIPPED_BEFORE_FORK`; the counter honours the same rule or the progress bar never reaches 1.0. Also: `copy_file` now retries a **429 only** — a rate limit proves the write never ran, a 5xx does not, and retrying a 5xx duplicates.
- [fork-run-state-first](docs/learnings/fork-run-state-first.md) — `fork_opp` writes `run_state.yaml` BEFORE the bulk copy (it's what makes a folder a run; a stalled fork must still be resumable). Also: `ForkProgress` is a StrictModel and the forker must emit exactly its field names — for months every emitted payload failed validation and `fork/status` could only ever say `unknown`, because the endpoint's only test monkeypatched `cache.get` with a hand-written payload no producer emits. The POST is BLOCKING; a timed-out caller polls (which now reports `new_run_id` from folder-creation onward) instead of retrying into a second partial fork.
- [run-state-vs-artifact-presence](docs/learnings/run-state-vs-artifact-presence.md) — Read step status from `run_state.yaml` content (one existing file_id, Changes API reliably reports edits), not artifact-file presence in subfolders (new child files, Changes API blind spot). PR #575 switched `_build_steps` to use `phases.<phase>.steps.<skill>.status` as the primary source; artifact-presence stays as the legacy fallback. Multi-viewer falls out for free: shared `OppSnapshot` invalidates once per agent write, every viewer hits the same fresh cache.

Slack:
- [slack-integration](docs/learnings/slack-integration.md) — `SlackConfig.ready()` runs in every management command (guard with env + sys.argv); `channel_not_found` is silent (wrapper normalises to `SlackChannelGone`); `(channel_id, ts)` must be stored together; dedup lock must be `cache.add` (SETNX); `Workspace` field is `name` not `display_name`; `bot_token` is a property (no `set_bot_token`); use `asyncio.get_running_loop()` not `get_event_loop()`.

Frontend:
- [draft-soft-lock-idle-timer](docs/learnings/draft-soft-lock-idle-timer.md) — React UIs showing wall-clock-driven transitions need explicit `setTimeout`-driven re-renders. (The draft soft-lock it came from is retired; the lesson is general.)
- [card-click-and-grid-stretch](docs/learnings/card-click-and-grid-stretch.md) — two layout traps that masquerade as React state bugs: (1) `<button>` nested in `<Link>` routes clicks ambiguously; (2) CSS Grid's default `align-items: stretch` makes collapsed neighbors visually expand.

Deploy & infrastructure:
- [alb-nginx-django-https](docs/learnings/alb-nginx-django-https.md) — `SECURE_PROXY_SSL_HEADER` + nginx `$real_scheme` map preserve the ALB's `https`; every `proxy_pass` must rewrite `Host` so ALB health checks don't trip `ALLOWED_HOSTS`.
- [mcp-bootstrap-container-traps](docs/learnings/mcp-bootstrap-container-traps.md) — (1) `op inject` parses `{{ }}` and `op://` literals inside `.env.tpl` comments and aborts; (2) `npx tsx` from a cwd without `node_modules` triggers a registry install that races Claude Code's 30s MCP connection timeout.
- [long-running-turns-vs-deploys](docs/learnings/long-running-turns-vs-deploys.md) — ECS task replacement kills in-flight `claude -p` subprocesses; Drive state is the durable source of truth. **Mostly moot in prod since 2026-07-28:** with `CANOPY_RUN_EXECUTION=true` runs execute on canopy's cloud runner, so an ace-web deploy doesn't kill them. It still applies to the flag-off / local `claude -p` path: don't avoid the deploy; resume the run from Drive once it lands. For `/ace:run`, that's the `<opp>/<run-id>` form (e.g. `/ace:run bednet-spot-check/20260524-2354`) which reads the existing `run_state.yaml` and continues at the first non-`complete` phase.
- [cloud-emulator-snapshot-persistence](docs/learnings/cloud-emulator-snapshot-persistence.md) — mobile AVD snapshot/restore semantics on the EC2 host; read before touching the rebake or in-VM launcher.

QA / probe:
- [e2e-probe](docs/qa/e2e-probe.md) — `scripts/qa/labs_probe.py` walks every UI surface + cross-checks the OpenAPI schema for orphan endpoints. Re-run after every deploy: `LABS_TOKEN=... uv run --extra walkthrough python scripts/qa/labs_probe.py`. Caught three Phase-5 regressions (public summary endpoint deleted, cross-opp compare deleted, empty-runs-folder 404) that nothing else surfaced.

Repo / merge process:
- [squash-merge-stale-branch-orphans-commits](docs/learnings/squash-merge-stale-branch-orphans-commits.md) — squash-merge from a topic branch that hasn't pulled an intervening merge silently overwrites the intervening commits on `main`. Defense CHANGED 2026-09-17: squash is enabled again, and the `main protection` ruleset's `strict_required_status_checks_policy: true` is what closes the hazard now — a stale branch cannot merge at all. The old `allow_squash_merge=false` note is superseded; don't re-disable squash on the strength of it.

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
  `bun run test` from `frontend/`. **Required checks** (`main protection`
  ruleset, strict — branch must be up to date): `pytest + ruff`, `schemathesis
  contract tests`, `basedpyright`. The frontend job (`tsc + vitest + build`) is
  **NOT** required, so run `bun run test` + `bunx tsc -b` locally before arming
  auto-merge on a frontend change.
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

- Phase 5 of the original ace-web design (observability eval harness, a11y pass,
  full security review, demo prep) is deferred indefinitely — revisit if a
  specific pain point surfaces. Don't propose it as planned work.
- The ace-web bootstrap/app CloudFormation stack split
  (`docs/plans/2026-09-09-ace-web-bootstrap-split.md`) is planned, not applied —
  `ace-web.cfn.yaml` still owns the log group + listener rule the CI role can't
  write.
