# ACE Web E2E Tests

Playwright-based smoke tests for the ace-web surfaces that still run
end-to-end in this repo — opp lifecycle, the read-only sessions/
upload surface, settings, and a system smoke test. Runs the full
stack (Django + Channels + React) locally without Docker, Postgres,
or Redis.

**Chat is no longer tested here.** Interactive chat (multiplayer
WebSocket collaboration — draft co-editing, presence, live
streaming) was ace-web's own feature through `apps.sessions`
(`consumers.py`/`drafts.py`/`presence.py`/`routing.py`) and was
retired in favor of canopy-hosted chat; `chat-lifecycle.spec.ts`,
`multiplayer.spec.ts`, and `share-flow.spec.ts` (session sharing,
also retired) were deleted with it. See the chat-retirement PR's
description for the full dependency map and what replaces this
coverage (short version: canopy-web owns the chat backend/E2E now;
ace-web's own `CanopyChatPanel` has component-level tests instead of
an E2E one — there's no cross-repo E2E harness that spins up both
ace-web and canopy-web together).

## Prerequisites

- `uv` installed (Python package manager)
- `bun` installed (for the frontend build)
- No Docker required

## First-time setup

```bash
cd e2e
bun install
bunx playwright install chromium
```

(`bunx playwright install chromium` downloads the Chromium binary
Playwright drives. Only needed once per machine.)

## Running the tests

From the `e2e/` directory:

```bash
bun run test              # headless
bun run test:headed       # see the browser windows
bun run test:ui           # Playwright UI mode (interactive)
```

Playwright's `webServer` config auto-launches uvicorn on
`http://127.0.0.1:8000` with
`DJANGO_SETTINGS_MODULE=config.settings.e2e`. That module:

- switches the DB to a file sqlite (`e2e-test.sqlite3` at the repo
  root, wiped and re-migrated by `globalSetup`)
- switches `CHANNEL_LAYERS` back to `InMemoryChannelLayer`
- sets `FORCE_SCRIPT_NAME = "/ace"` so the hardcoded `base: "/ace/"`
  Vite build and `basename: "/ace"` React Router serve through a
  single uvicorn process
- leaves `ACE_ALLOW_TEST_LOGIN=True` and
  `ACE_USE_FAKE_CLI_BACKEND=True` from `development.py` enabled

The ASGI entry point is `config.asgi_e2e:application`, which:

- wraps the real `config.asgi.application` with a tiny
  prefix-stripping middleware so `/ace/ws/opps/<slug>/...` reaches
  the Channels router (which registers the bare `^ws/opps/...$`
  pattern — the opp-workbench live socket, the one WebSocket surface
  left after chat's retirement). In production nginx does the same
  rewrite; in Vite dev the proxy does it. Neither runs during the
  E2E suite, so the wrapper emulates the strip. See
  `docs/learnings/channels-ws-proxy-path.md`.
- patches `apps.common.redis_client.get_redis` to return a
  `fakeredis.aioredis.FakeRedis` instance so Redis-backed code
  (`apps.common.nova_auth_flow`, `apps.videos.service`,
  `apps.mobile`) works without a real Redis during the suite.

The `globalSetup` hook runs migrations and builds the frontend if
`frontend/dist/index.html` is missing. Delete the dist directory
to force a rebuild.

Note: `manage.py runserver` is intentionally not used because it
does not honour `FORCE_SCRIPT_NAME` the way uvicorn does (runserver
produces double-prefixed URLs like `/ace/ace/api/...`).

## How it works

1. Each test opens a fresh browser context per user via
   `newAuthedContext(browser, email, displayName)`.
2. `loginAs(page, ...)` POSTs to the dev-only
   `/ace/auth/test-login/` endpoint. The Django `sessionid` cookie
   lands on the context. A follow-up GET to `/ace/` warms the
   `csrftoken` cookie so subsequent API POSTs can set the
   `X-CSRFToken` header.
3. `createSession` (`helpers/session.ts`) drives the REST API
   through `postJson`, which automatically attaches the CSRF
   token — used by `sessions.spec.ts` to seed rows for the
   `/ace/sessions` list/search/filter/archive/delete/pagination
   surface.
4. `uploadJsonlFixture` (`helpers/upload.ts`) drives the sessions
   page's hidden file input to exercise the ingest path
   (`upload-flow.spec.ts`).
5. `opp-lifecycle.spec.ts` and `settings.spec.ts` exercise their
   own surfaces independently of sessions/chat.

## Security

The two dev-only backend hooks
(`ACE_ALLOW_TEST_LOGIN` and `ACE_USE_FAKE_CLI_BACKEND`) are
triple-gated:

1. Default `False` in `config/settings/base.py`.
2. Only `True` in `config/settings/development.py` and
   `config/settings/e2e.py`.
3. The `/auth/test-login/` URL itself is only registered when BOTH
   `ACE_ALLOW_TEST_LOGIN` and `DEBUG` are True — so in production
   the route does not exist.

`production.py` and `connectlabs.py` both have `DEBUG=False`, so
the hooks are unreachable in any prod path.

## Troubleshooting

- **"CSRF token missing" on API POSTs.** `loginAs` should warm
  the CSRF cookie via a follow-up GET to `/ace/`. If this fails,
  check that the test is passing the result of `loginAs` into
  `createSession` through the same browser context.
- **Opp-workbench WebSocket closes immediately with no frame.**
  fakeredis patching happens at import-time in
  `config/asgi_e2e.py`. If you change the import order, make sure
  the patch still happens before `from config.asgi import
  application`.
- **404 on `/ace/assets/index-XXX.js`.** The frontend dist is
  either stale or missing. Delete `frontend/dist/` and re-run —
  `globalSetup` will rebuild it.
- **The test-login endpoint 404s.** Check that
  `config/settings/e2e.py` inherits from `development.py` and
  that `ACE_ALLOW_TEST_LOGIN` is still True there.
