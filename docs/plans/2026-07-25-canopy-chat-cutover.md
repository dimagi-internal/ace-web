# ace-web → canopy hosted chat cutover (Part 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ace-web keeps its chat UX but all chat state + execution move to canopy-web: sessions, messages, drafts, presence, turns, and the runner fleet. ace-web's backend keeps exactly one chat responsibility — brokering identity via canopy's token exchange — plus a session-create convenience that bakes in opp linkage.

**Architecture:** The browser talks to canopy-web **directly** (same origin in prod: `labs.connect.dimagi.com/ace/` ↔ `/canopy/`; vite proxy in dev). ace-web's server exchanges its registered `AppCredential` + the authenticated user's email for a short-lived canopy `DelegatedToken`; the SPA uses that token as `Authorization: Bearer` on canopy REST and `?token=` on canopy WS. The chat UI is the shared `canopy-ui/chat` kit (already a dependency at 0.3.0; 0.4.0 adds `./chat`). Legacy `apps/sessions` chat stays intact behind the flag until the labs gate passes, then PR 6 deletes it.

**Canopy-side contract (all shipped on canopy-web main today):**
- `POST {canopy}/api/auth/token-exchange` — auth `Bearer <app credential>`, body `{"acting_as_email": ..., "ttl_seconds": 3600}` → `{"token", "expires_at"}`. 401 bad credential, 403 domain/inactive.
- `POST {canopy}/api/w/{ws}/canopy-sessions/` — auth `Bearer <delegated token>`, body `{"agent_slug": "ace", "title": ..., "metadata": {...}}` → session (`id` UUID). Metadata is opaque; ace uses `{"source": "ace-web", "opp_slug": ..., "opp_run_id": ..., "opp_step_skill": ...}`.
- `GET {canopy}/api/canopy-sessions/?source=ace-web[&opp_slug=…][&opp_run_id=…][&state=active|archived|all]` — the chat index. `GET /{id}?full=`, `GET /{id}/messages?before=&limit=` (scroll-back), `POST /{id}/stop`, `POST /{id}/place`, `POST /{id}/archive|unarchive`.
- `GET {canopy}/api/harness/runners/` — runner names/status for the placement banner.
- WS `{canopy}/ws/canopy-sessions/{id}/?token=<delegated token>` — canonical protocol (`session.state`, `chat.send`, `chat.stop`, `chat.stream_*`, `draft.*`, `presence.*`, `session.title_updated`). Close 4001 = bad/expired token → refresh + reconnect.
- Reference consumer implementation: `/Users/acedimagi/emdash/repositories/canopy-web/frontend/src/pages/ChatPage.tsx` (+ `frontend/src/lib/wsUrl.ts`, `frontend/src/api/chat.ts`, `frontend/src/components/chat/runnerEligibility.ts`). Read these before Task 4.
- Spec (the "why" record): canopy-web `docs/superpowers/specs/2026-07-25-ace-web-canopy-chat-cutover-design.md`.

**Tech Stack:** Django 5 + django-ninja + django-environ; React 19 + Vite + Tailwind 4 + `canopy-ui`; vitest (frontend), pytest (backend, settings `config.settings.test`).

## Global Constraints

- Backend tests: `uv run pytest tests/<file> -v`; full suite `uv run pytest` once before each commit batch. Frontend: `cd frontend && npm run test` (vitest) and `npm run build`.
- New Ninja routers follow the repo pattern: `Router(auth=session_auth, tags=[…])` in `apps/<app>/api.py`, registered in `apps/api/api.py` via `api.add_router(...)` (deferred imports at the bottom, `# noqa: E402`).
- Settings via `django-environ` in `config/settings/base.py` (`env("NAME", default=…)`); secret values never get real defaults.
- Do NOT add a `/canopy/` block to `frontend/nginx.prod.conf` — in prod the shared ALB routes `/canopy/*` to canopy-web directly; ace-web's nginx must stay `/ace/*`-only.
- Feature flag: canopy chat is ON iff `CANOPY_BASE_URL` and `CANOPY_APP_CREDENTIAL` are both set; the frontend learns this from `GET /api/canopy/status` (the repo's per-feature status-endpoint pattern, cf. `useCliAuthStatus`).
- Commit messages end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- PR bodies end with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
- PR 5 = branch `feat/canopy-chat` off `origin/main`; PR 6 = branch `feat/retire-sessions` off PR 5's merge (gated — see Task 6).

---

## PR 5 — branch `feat/canopy-chat`

### Task 1: Backend `apps/canopy` — status, token, session-create

**Files:**
- Create: `apps/canopy/__init__.py`, `apps/canopy/apps.py`, `apps/canopy/client.py`, `apps/canopy/api.py`
- Modify: `config/settings/base.py` (settings block), `config/settings/development.py` (dev defaults), `apps/api/api.py` (router), `config/settings/base.py` INSTALLED_APPS
- Test: `tests/test_canopy_client.py` (create)
- Also: `git add docs/plans/2026-07-25-canopy-chat-cutover.md` (this plan, already on disk) with your commit.

**Interfaces:**
- Produces: `GET /api/canopy/status` → `{"enabled": bool, "base_url": str, "workspace": str, "agent": str}`; `POST /api/canopy/token` → `{"token": str, "expires_at": str}`; `POST /api/canopy/sessions` body `{"title": str = "", "opp_slug": str = "", "opp_run_id": str = "", "opp_step_skill": str = ""}` → `{"id": str}`. `client.exchange_token(email, ttl=3600)` and `client.create_session(user_token, *, title, metadata)` are the outbound seams tests mock.

- [ ] **Step 1: Settings** — in `config/settings/base.py` (near the other integration settings):

```python
# --- canopy-web hosted chat (Part 2 cutover; spec lives in canopy-web) -------
# Server-side base for outbound calls (token exchange, session create).
CANOPY_BASE_URL = env("CANOPY_BASE_URL", default="")
# Registered AppCredential raw value (canopy: manage.py create_app_credential).
CANOPY_APP_CREDENTIAL = env("CANOPY_APP_CREDENTIAL", default="")
# Browser-facing base: same-origin path prefix on labs, vite proxy path in dev.
CANOPY_PUBLIC_BASE_URL = env("CANOPY_PUBLIC_BASE_URL", default="/canopy")
CANOPY_WORKSPACE = env("CANOPY_WORKSPACE", default="connect")
CANOPY_AGENT_SLUG = env("CANOPY_AGENT_SLUG", default="ace")
```

Add `"apps.canopy"` to `INSTALLED_APPS`. In `development.py`: `CANOPY_BASE_URL = env("CANOPY_BASE_URL", default="http://127.0.0.1:8000")` (local canopy dev server; still off until a credential is set).

- [ ] **Step 2: Failing tests** (`tests/test_canopy_client.py`) — follow the repo's test style; mock the outbound seam, never the network:

```python
"""apps.canopy — the thin identity-brokering surface for canopy hosted chat."""
from unittest import mock

import pytest
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db

ENABLED = dict(CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="secret-cred")


def _login(client):
    # mirror the login helper used by existing api tests (grep "force_login" in tests/)
    ...


def test_status_disabled_by_default():
    c = Client(); _login(c)
    body = c.get("/api/canopy/status").json()
    assert body["enabled"] is False


@override_settings(**ENABLED)
def test_status_enabled_and_shapes():
    c = Client(); _login(c)
    body = c.get("/api/canopy/status").json()
    assert body == {"enabled": True, "base_url": "/canopy", "workspace": "connect", "agent": "ace"}


@override_settings(**ENABLED)
def test_token_exchanges_for_request_user():
    c = Client(); user = _login(c)
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t", "expires_at": "x"}) as ex:
        r = c.post("/api/canopy/token")
    assert r.status_code == 200 and r.json()["token"] == "t"
    ex.assert_called_once_with(user.email, ttl=3600)


def test_token_503_when_disabled():
    c = Client(); _login(c)
    assert c.post("/api/canopy/token").status_code == 503


@override_settings(**ENABLED)
def test_session_create_forwards_metadata_with_user_token():
    c = Client(); _login(c)
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "usertok", "expires_at": "x"}), \
         mock.patch("apps.canopy.client.create_session", return_value={"id": "abc"}) as cs:
        r = c.post("/api/canopy/sessions", data={"title": "T", "opp_slug": "field-hep"},
                   content_type="application/json")
    assert r.status_code == 200 and r.json()["id"] == "abc"
    kwargs = cs.call_args.kwargs
    assert cs.call_args.args[0] == "usertok"
    assert kwargs["metadata"] == {"source": "ace-web", "opp_slug": "field-hep"}
    assert kwargs["title"] == "T"
```

Fill `_login` from the existing pattern (grep `force_login`/test-login in `tests/`); anonymous access must be rejected by `session_auth` (add one 401/403 assertion for `/api/canopy/token`).

- [ ] **Step 3: Run (FAIL 404)** — `uv run pytest tests/test_canopy_client.py -v`
- [ ] **Step 4: Implement.** `apps/canopy/client.py` — stdlib urllib (no new dependency), 10s timeout, raises a small `CanopyError(status, detail)`:

```python
"""Outbound calls to canopy-web. Two calls only: token exchange (the app
credential's single power) and session create (so opp-linkage rules live
server-side). Everything else is browser → canopy directly."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings


class CanopyError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(f"canopy {status}: {detail}")


def _post(path: str, payload: dict, *, bearer: str) -> dict:
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc


def exchange_token(email: str, *, ttl: int = 3600) -> dict:
    return _post("/api/auth/token-exchange",
                 {"acting_as_email": email, "ttl_seconds": ttl},
                 bearer=settings.CANOPY_APP_CREDENTIAL)


def create_session(user_token: str, *, title: str, metadata: dict) -> dict:
    return _post(f"/api/w/{settings.CANOPY_WORKSPACE}/canopy-sessions/",
                 {"agent_slug": settings.CANOPY_AGENT_SLUG, "title": title, "metadata": metadata},
                 bearer=user_token)
```

`apps/canopy/api.py` — `router = Router(auth=session_auth, tags=["canopy"])`; `status` returns the settings-derived dict (enabled = both settings truthy); `token` 503s when disabled, else `client.exchange_token(request.user.email, ttl=3600)` mapped to the response schema (a `CanopyError` becomes an HttpError with its status, detail sanitized); `sessions` builds metadata from the non-empty optional fields plus `"source": "ace-web"`, exchanges a token for the user, calls `client.create_session`, returns `{"id": ...}`. Register `api.add_router("/canopy", canopy_router)`.

- [ ] **Step 5: Green + full suite** — `uv run pytest tests/test_canopy_client.py -v && uv run pytest`
- [ ] **Step 6: Commit** (branch `feat/canopy-chat` off `origin/main`; include this plan doc).

### Task 2: Frontend foundation — canopy-ui 0.4.0 + vite proxy

**Files:**
- Modify: `frontend/package.json` (+lock) — `canopy-ui` `0.3.0` → `0.4.0`
- Modify: `frontend/vite.config.ts` (dev proxy)
- Test: build + one import smoke test

**Interfaces:** Produces a resolvable `import { ChatPanel, useSessionSocket, PlacementBanner } from "canopy-ui/chat"` and a dev-mode `/canopy/*` proxy (HTTP + WS) to a local canopy-web on `:8000`.

- [ ] **Step 1:** `cd frontend && npm install canopy-ui@0.4.0`. Check `canopy-ui/chat`'s imports resolve with existing deps (`npm run build`); the kit ships raw TS and its peers (`@base-ui/react`, `clsx`, `class-variance-authority`, `tailwind-merge`) are already direct or transitive deps from the 0.3.0 adoption — add any that are missing as the build errors name them.
- [ ] **Step 2:** vite proxy, next to the existing `/ace/*` entries:

```ts
"/canopy": {
  target: `http://127.0.0.1:${env.CANOPY_BACKEND_PORT ?? "8000"}`,
  changeOrigin: true,
  ws: true,
  rewrite: (p) => p.replace(/^\/canopy/, ""),
},
```

(Local canopy-web serves at the root, so the `/canopy` prefix — which mirrors the labs path — is stripped, exactly like the `/ace` rewrite above it. Match the file's existing style for reading env.)

- [ ] **Step 3:** Smoke test `frontend/src/canopy/kit.test.ts`: `import { ChatPanel, useSessionSocket, PlacementBanner } from "canopy-ui/chat"; test("kit exports resolve", () => { expect(ChatPanel).toBeTruthy(); expect(useSessionSocket).toBeTruthy(); expect(PlacementBanner).toBeTruthy(); });`
- [ ] **Step 4:** `npm run test && npm run build` green; also confirm ace's existing UI still builds (the token/preset CSS wiring from 0.3.0 is unchanged by 0.4.0 — no CSS action expected; if the build surfaces missing tailwind scanning for the new chat sources, extend the existing `@source`/content config the same way the 0.3.0 adoption did).
- [ ] **Step 5: Commit.**

### Task 3: Frontend canopy client — token lifecycle + REST + WS URL

**Files:**
- Create: `frontend/src/canopy/token.ts`, `frontend/src/canopy/api.ts`, `frontend/src/canopy/ws.ts`, `frontend/src/canopy/useCanopyStatus.ts`
- Test: `frontend/src/canopy/token.test.ts` (create)

**Interfaces (consumed by Task 4):**

```ts
// useCanopyStatus.ts — fetch /api/canopy/status once (module cache), like useCliAuthStatus but no polling
export interface CanopyStatus { enabled: boolean; base_url: string; workspace: string; agent: string }
export function useCanopyStatus(): CanopyStatus | null

// token.ts — cached delegated token with expiry-aware refresh
export async function getCanopyToken(force?: boolean): Promise<string>   // POST /api/canopy/token via ace API helper; caches until 5 min before expires_at; force bypasses cache
export function peekCanopyToken(): string | null                        // sync read for wsUrl builders

// api.ts — browser → canopy REST, Authorization: Bearer <delegated token>, retry-once-on-401 with force refresh
export interface CanopySessionSummary { id: string; title: string; agent_slug: string | null; updated_at: string; runner_name?: string | null; metadata?: Record<string, string> }
export function listCanopySessions(base: string, filters?: {opp_slug?: string; opp_run_id?: string; state?: string}): Promise<CanopySessionSummary[]>  // always sends source=ace-web
export function createCanopySession(input: {title?: string; opp_slug?: string; opp_run_id?: string; opp_step_skill?: string}): Promise<{id: string}>   // ace backend POST /api/canopy/sessions
export function fetchOlderMessages(base: string, id: string, before: number): Promise<unknown[]>
export function stopCanopySession(base: string, id: string): Promise<void>
export function placeCanopySession(base: string, id: string, placement: "wait" | {runner_id: string}): Promise<void>
export function listCanopyRunners(base: string): Promise<{id: string; name: string; live_status?: string; ready?: boolean; capabilities?: Record<string, unknown>}[]>

// ws.ts
export function buildCanopyWsUrl(base: string, sessionId: string): string  // wss/ws + host from location when base is a path; appends ?token=<peekCanopyToken()>
```

Match the exact response field names against canopy's OpenAPI: with a local canopy-web checkout at `/Users/acedimagi/emdash/repositories/canopy-web`, read `frontend/src/api/generated.ts` there for `SessionOut` / `RunnerOut` field names rather than guessing.

- [ ] **Step 1: Failing token tests** — cache behavior with fake timers: first call fetches; second call within TTL returns cached without a fetch; a call after `expires_at - 5min` refetches; `force` always refetches; 401-triggered `getCanopyToken(true)` path returns the new token. Mock the ace API helper (`vi.mock`) — never real fetch.
- [ ] **Step 2:** Implement per the interfaces. `api.ts` request helper: attach `Authorization: Bearer ${await getCanopyToken()}`; on 401 response, one retry with `getCanopyToken(true)`. Canopy REST paths are `${base}/api/canopy-sessions/...` and `${base}/api/harness/runners/`.
- [ ] **Step 3:** `npm run test -- canopy && npm run build`; commit.

### Task 4: `CanopyChatPanel` + surface integration behind the flag

**Files:**
- Create: `frontend/src/canopy/CanopyChatPanel.tsx` (container: kit `ChatPanel` + kit `useSessionSocket` + placement banner wiring)
- Modify: `frontend/src/pages/ChatPage.tsx`, `frontend/src/components/RecentSessionsSidebar.tsx` (or the current chat-list component ChatPage uses), `frontend/src/components/opps/WorkbenchChatPane.tsx`, router (`frontend/src/App.tsx` or router file) — new route `/w/:workspaceSlug/chat/c/:canopyId`
- Test: `frontend/src/canopy/CanopyChatPanel.test.tsx`

**Interfaces:**
- Consumes: everything from Task 3; kit `useSessionSocket({ sessionId, wsUrl, onTitleUpdated })` + `ChatPanel` props (`state, connected, currentUserId, onSend, onStop, onUpdateDraft, onTakeOver, onDiscard, renderMarkdown?, banner?, emptyState?, disabledReason?, historySlot?`) + `PlacementBanner`.
- Produces: `<CanopyChatPanel sessionId={id} />` — a drop-in chat body for any ace surface.

Behavior contract (read canopy-web's `frontend/src/pages/ChatPage.tsx` first — it is the reference container; this component is its ace-web twin):
1. `useSessionSocket({ sessionId, wsUrl: (path) => buildCanopyWsUrl(status.base_url, sessionId), onTitleUpdated })` — note the kit calls `wsUrl` on every (re)connect, so the token read must happen inside the builder (fresh `peekCanopyToken()`); on WS close-4001 the kit retries — pre-empt dead tokens by `getCanopyToken()` on mount and on each reconnect attempt via the builder.
2. `currentUserId` comes from the `session.state` snapshot (kit exposes it on `state`).
3. Stop → kit `stopChat`; also surface the placement banner: poll `listCanopyRunners` while the session's bound runner is offline (mirror the reference page's `runnerEligibility` logic), render kit `PlacementBanner` through the `banner` slot with `onWait` → `placeCanopySession(base, id, "wait")`, `onPlace` → `placeCanopySession(base, id, {runner_id})`.
4. `historySlot`: "Load earlier" button → `fetchOlderMessages` → kit `prependMessages`.
5. Markdown: pass ace's existing markdown renderer (grep how `MessageItem`/`MessageList` render markdown today; reuse that function via the kit's `renderMarkdown` seam).

Surface integration (flag = `useCanopyStatus()?.enabled`):
- **ChatPage / chat list:** when enabled, the sidebar lists canopy sessions (`listCanopySessions(base)`) alongside a "Legacy" section for existing ace sessions (old routes unchanged); "New chat" → `createCanopySession({})` → navigate to `/w/:ws/chat/c/{id}`. The new route renders page chrome + `<CanopyChatPanel/>`; title comes from the session list / `session.title_updated`.
- **WorkbenchChatPane:** when enabled, "Discuss this step" → `createCanopySession({title, opp_slug, opp_run_id, opp_step_skill})`; linked chats = `listCanopySessions(base, {opp_slug, opp_run_id})`; selection renders `<CanopyChatPanel/>`. Legacy linked chats keep rendering via the old path.
- When disabled, ZERO behavior change (all existing tests must stay green).

- [ ] **Step 1:** Read the reference implementation + kit sources (`node_modules/canopy-ui/src/chat/*`). Write failing component tests: (a) renders and wires `ChatPanel` from a mocked socket state; (b) `onStop` calls kit stop; (c) banner appears when runner offline props say so and `onPlace` posts placement; (d) flag off → legacy panel renders (mock `useCanopyStatus`).
- [ ] **Step 2:** Implement `CanopyChatPanel` + surface changes.
- [ ] **Step 3:** `npm run test && npm run build`; full backend suite untouched but run `uv run pytest` once (router/PWA files sometimes import-check).
- [ ] **Step 4: Commit.**

### Task 5: Deploy + ops wiring

**Files:**
- Modify: `deploy/aws/task-definition.json` (`api` container only), `CLAUDE.md` (chat section), `.env.example`
- No nginx changes (Global Constraints).

- [ ] **Step 1:** task-definition `environment`: add `{"name": "CANOPY_BASE_URL", "value": "https://labs.connect.dimagi.com/canopy"}`, `{"name": "CANOPY_PUBLIC_BASE_URL", "value": "/canopy"}`, `{"name": "CANOPY_WORKSPACE", "value": "connect"}`, `{"name": "CANOPY_AGENT_SLUG", "value": "ace"}`. `secrets`: add `{"name": "CANOPY_APP_CREDENTIAL", "valueFrom": "<Secrets Manager ARN — placeholder arn:aws:secretsmanager:us-east-1:858923557655:secret:ace-web/canopy-app-credential>"}` (the secret itself is provisioned out-of-band; keep the ARN consistent with the file's existing secret naming).
- [ ] **Step 2:** `.env.example`: the five CANOPY_* vars with comments (dev: point at local canopy-web + a credential from `manage.py create_app_credential --name ace-web-dev --domains dimagi.com`).
- [ ] **Step 3:** CLAUDE.md: replace/augment the chat architecture paragraph — chat is canopy-hosted when CANOPY_* is configured; legacy `apps/sessions` remains until PR 6; document the token-exchange flow in 3 lines and the ops steps (canopy prod credential mint, Secrets Manager, deploy).
- [ ] **Step 4:** `uv run pytest` + `cd frontend && npm run build` once more; commit; **create PR 5** (`gh pr create --head feat/canopy-chat`).

### PR 5 exit criteria
All tasks reviewed; PR open; flag OFF by default everywhere (labs turns on only when the credential secret exists).

---

## PR 6 — branch `feat/retire-sessions` (GATED)

**Gate (manual, on labs, before starting):** canopy chat enabled on labs and a full opp chat exercised through the new path — send, streamed reply, stop mid-turn, interjection, reconnect, two humans in one session. Do not start Task 6 until the human confirms the gate.

### Task 6: Retire `apps/sessions` and the legacy chat path

**Files (discovery-driven — the deletion list must be derived, not assumed):**
- Delete: `apps/sessions/` (models, consumers, drafts, turn_driver, routing, ingest views if chat-only), legacy chat frontend (`useSessionSocket.ts`, `sessionReducer.ts`, local `ChatPanel`/`MessageList`/`MessageItem`/`SendBox`/`PresenceChips`, `pairToolMessages`, legacy ChatPage plumbing), `apps/common/cli_backend.py` chat path + `backend_selector` + `auto_title` (keep any piece a non-chat consumer imports — `grep -rn` every symbol before deleting; the videos/system/mobile subprocess spawns are unrelated and stay).
- Migration: drop the `sessions`, `session_participants`, `messages`, `drafts`, `share_tokens` tables (decision: existing chat data is deleted; `IngestUpload` stays only if the cost/structure views survive — check its consumers).
- Update: `e2e/tests/chat-lifecycle.spec.ts` (retire or repoint), `config/asgi.py` (WS routing), nav/router redirects from old chat URLs to the canopy chat home.

- [ ] **Step 1:** Build the dependency map (`grep -rn` each module's importers); write it into the PR description.
- [ ] **Step 2:** Delete + migrate + redirect; full backend suite, frontend build, e2e suite green.
- [ ] **Step 3:** Commit; create PR 6; hold for review.

---

## Self-review notes

- Spec Part 2 coverage: `canopy_client`-equivalent (Task 1), kit adoption + direct browser connection (Tasks 2-4), deploy (Task 5), retirement + data deletion (Task 6, gated). The spec's "seeding rides as first message text" lands in Task 4's WorkbenchChatPane discuss flow (title + metadata; the ACE agent loads opp state from its own environment).
- Types/names consistent: `useCanopyStatus`/`getCanopyToken`/`peekCanopyToken`/`buildCanopyWsUrl`/`createCanopySession` defined in Task 3, consumed in Task 4; `client.exchange_token`/`client.create_session` defined and mocked in Task 1.
- Deliberately not in scope: ALB routing (already routes `/canopy/*`), canopy-side changes (none needed), token in localStorage (kept in module memory — a page reload re-fetches).
