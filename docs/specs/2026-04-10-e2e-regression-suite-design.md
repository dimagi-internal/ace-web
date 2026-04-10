# E2E Regression Suite — Design Spec

**Date:** 2026-04-10
**Status:** Approved for execution
**Scope:** Expand the existing Playwright E2E test suite to cover every testable
user flow in ace-web. The existing `multiplayer.spec.ts` (5 tests) remains
untouched; this adds 5 new spec files covering single-player chat, library CRUD,
share token lifecycle, JSONL upload, and personal token management.

## 1. Problem

The existing E2E suite covers multi-player WebSocket collaboration (chat, drafts,
presence, reconnect) but nothing else. The library page, share tokens, upload flow,
settings page, and single-player chat have zero E2E coverage. These are the flows
the team will use daily — regressions here would be caught only in production.

## 2. Approach

Hybrid spec structure: page-level specs for self-contained CRUD surfaces,
journey specs for multi-page flows. Follows every convention established by
`multiplayer.spec.ts`: `newAuthedContext()` for auth, REST helpers for setup,
DOM assertions + API-level database verification, `.animate-pulse` for streaming
state.

### What we test

| Spec file | Flow | Tests |
|-----------|------|-------|
| `chat-lifecycle.spec.ts` | Single-player: create → type → stream → stop → title edit → library nav | 5 |
| `library.spec.ts` | List, search, filter, archive, delete, empty state, pagination | 7 |
| `share-flow.spec.ts` | Create token → copy → view as anon → revoke → verify revoked | 5 |
| `upload-flow.spec.ts` | Upload JSONL → appears in library → open → read-only | 3 |
| `settings.spec.ts` | Token create → shown once → list → revoke | 3 |

~23 new tests, bringing the total to ~28.

### What we skip

- **Opps workbench** — requires Google Drive data; solid backend unit tests; read-only surface
- **CLI auth page** — requires real Claude CLI subprocess; tested via backend unit tests
- **Health page** — trivial; already covered by Playwright's `webServer` health check
- **HomePage** — static landing, no interactive behavior

## 3. New files

### Test specs

```
e2e/tests/
  chat-lifecycle.spec.ts     # NEW
  library.spec.ts            # NEW
  share-flow.spec.ts         # NEW
  upload-flow.spec.ts        # NEW
  settings.spec.ts           # NEW
```

### Helpers

```
e2e/helpers/
  share.ts                   # NEW — createShareToken, revokeShareToken
  upload.ts                  # NEW — uploadJsonl
```

### Fixtures

```
e2e/fixtures/
  sample-session.jsonl       # NEW — minimal valid JSONL for upload tests
```

No changes to existing files (`multiplayer.spec.ts`, `auth.ts`, `session.ts`,
`playwright.config.ts`, `global-setup.ts`).

## 4. Spec details

### 4.1 `chat-lifecycle.spec.ts`

Single-player chat through the FakeCLIBackend. One authenticated user.

**Test 1: "create session via /chat redirect"**
- Navigate to `/ace/chat`
- `ChatRedirectPage` creates a session and redirects to `/ace/chat/:slug`
- Verify: URL matches `/ace/chat/<slug>`, send box is visible

**Test 2: "type a message and receive streaming response"**
- Type "Hello world" in the send box, press Enter
- Streaming cursor (`.animate-pulse`) appears
- "Echo: Hello world" streams into the message list
- Cursor disappears when streaming completes
- Verify via `listMessages()`: user message + assistant message, both `status=complete`

**Test 3: "stop button cancels in-flight stream"**
- Type a message, press Enter
- Wait for streaming cursor to appear
- Click the stop button
- Verify: assistant message has `status=error`, `error_detail` contains "cancelled"
- Verify via `listMessages()`: message persisted with error state

**Test 4: "inline title edit"**
- The session starts with an empty title (or auto-titled)
- Click the title area, type "My test session", press Enter
- Verify: title updates in the header
- Navigate to `/ace/library`, verify session appears with "My test session"

**Test 5: "recent sessions sidebar shows current session"**
- After creating a session, the sidebar lists it
- Verify: sidebar contains at least one entry linking to the current slug

### 4.2 `library.spec.ts`

Session list CRUD. One authenticated user. Tests create sessions via the REST
API (not the UI) to keep setup fast, then exercise the library UI.

**Test 1: "empty state when no sessions"**
- Navigate to `/ace/library`
- Verify: "No sessions yet — start a chat." message visible

**Test 2: "sessions appear in list"**
- Create 3 sessions via API with distinct titles
- Navigate to library
- Verify: all 3 titles visible in the list

**Test 3: "search filters by title"**
- Create sessions: "Alpha design", "Beta review", "Alpha followup"
- Type "Alpha" in search box
- Verify: 2 results visible, "Beta review" not visible

**Test 4: "status filter shows only matching"**
- Create 2 sessions, archive one via API
- Click "Archived" filter tab
- Verify: only the archived session visible
- Click "Active" filter tab
- Verify: only the active session visible

**Test 5: "archive and restore a session"**
- Create a session
- Open the row's dropdown menu → click "Archive"
- Verify: toast "Session archived"
- Switch to "Archived" filter → session appears
- Open dropdown → click "Restore"
- Switch to "Active" filter → session appears

**Test 6: "delete a session with confirmation"**
- Create a session
- Open dropdown → click "Delete"
- Verify: confirmation dialog appears with session title
- Click "Delete" in dialog
- Verify: session gone from list, toast "Session deleted"

**Test 7: "pagination controls"**
- Create 25 sessions via API
- Navigate to library
- Verify: "Page 1 of 2" footer visible, 20 items in list
- Click "Next →"
- Verify: "Page 2 of 2", 5 items visible

### 4.3 `share-flow.spec.ts`

Multi-page share token lifecycle. Two browser contexts: one authenticated
(the owner), one unauthenticated (the viewer).

**Test 1: "create share link and see popover"**
- Create a session with messages via API (user + assistant)
- Navigate to `/ace/chat/:slug`
- Click "share" button → popover opens
- Click "Create share link" → "Link copied to clipboard" feedback shown
- Token appears in the "Active links" list

**Test 2: "share link loads read-only view for authenticated user"**
- Create a share token via API
- Navigate to the share URL (`/ace/share/:token`) in the same context
- Verify: "Shared session — read only" banner visible
- Verify: messages render, no send box

**Test 3: "share link works for unauthenticated user via API"**
- Create a share token via API
- Fetch `/ace/api/share/:token` from a raw request (no cookies)
- Verify: 200 response with title and messages

**Test 4: "revoke share token"**
- Create a share token, verify it works
- Open the share popover → click "revoke" on the token
- Token disappears from the list
- Fetch `/ace/api/share/:token` → 404 with code "revoked"

**Test 5: "invalid token shows error"**
- Navigate to `/ace/share/totally-bogus-token`
- Verify: "This share link is invalid or has expired." message visible

### 4.4 `upload-flow.spec.ts`

JSONL upload lifecycle. Uses `e2e/fixtures/sample-session.jsonl`.

**Test 1: "upload JSONL file from library"**
- Navigate to `/ace/library`
- Trigger file upload with the fixture file
- Verify: toast with message count appears
- Verify: session appears in library list with "upload" source badge

**Test 2: "imported session renders messages"**
- Upload the fixture, navigate to the session
- Verify: messages from the JSONL render in the message list
- Verify: user and assistant messages both present

**Test 3: "imported session send box is disabled"**
- Open the imported session
- Verify: send box textarea is disabled or hidden
- Verify: a visual indicator shows the session is imported/read-only

### 4.5 `settings.spec.ts`

Personal token CRUD on the settings page.

**Test 1: "create a personal token"**
- Navigate to `/ace/settings`
- Click "Create token" → dialog appears
- Type label "test-token", click "Create"
- Verify: raw token dialog appears with a token value
- Click "I've saved this" → dialog closes

**Test 2: "token appears in list"**
- After creating a token, the list shows "test-token" with creation date
- Verify: token row visible with correct label

**Test 3: "revoke a token"**
- Click the delete/revoke button on the token row
- Verify: toast "Token revoked"
- Verify: token disappears from list

## 5. Helpers

### `e2e/helpers/share.ts`

```typescript
import type { Page } from "@playwright/test";
import { getCsrfToken } from "./auth";

type Envelope<T> = { data: T | null; error: { code: string; message: string } | null };

interface ShareTokenData {
  token: string;
  url: string;
  created_at: string;
}

export async function createShareToken(page: Page, slug: string): Promise<ShareTokenData> {
  const csrf = await getCsrfToken(page.context());
  const resp = await page.request.post(`/ace/api/sessions/${slug}/share`, {
    headers: { "X-CSRFToken": csrf },
  });
  const envelope = (await resp.json()) as Envelope<ShareTokenData>;
  if (envelope.error) throw new Error(JSON.stringify(envelope.error));
  return envelope.data!;
}

export async function revokeShareToken(page: Page, slug: string, token: string): Promise<void> {
  const csrf = await getCsrfToken(page.context());
  await page.request.delete(`/ace/api/sessions/${slug}/share/${token}`, {
    headers: { "X-CSRFToken": csrf },
  });
}
```

### `e2e/helpers/upload.ts`

```typescript
import type { Page } from "@playwright/test";

/**
 * Upload a .jsonl file via the library page's file input.
 * The page must be on /ace/library and authenticated.
 */
export async function uploadJsonl(page: Page, fixturePath: string): Promise<void> {
  const fileInput = page.locator('input[type="file"][accept=".jsonl"]');
  await fileInput.setInputFiles(fixturePath);
}
```

## 6. Fixture

### `e2e/fixtures/sample-session.jsonl`

A minimal valid Claude CLI `--output-format stream-json` file with 2 turns
(1 user message, 1 assistant response). The parser expects:

- A `{"type": "system", "subtype": "init", "session_id": "..."}` line
- A `{"type": "user", "message": {"content": [{"type": "text", "text": "..."}]}}` line (optional — the parser handles its absence)
- One or more `{"type": "assistant", "message": {"id": "...", "content": [{"type": "text", "text": "..."}]}}` lines
- A `{"type": "result", ...}` line (signals end of turn)

The fixture produces 2 `ParsedTurn` rows: 1 assistant turn. The user message
in the JSONL `user` event doesn't produce a ParsedTurn (the parser only extracts
`tool_result` blocks from user events). The ingest view creates the user message
from the init context. We'll craft the fixture to produce at least 2 message rows
for meaningful verification.

Actually, looking at the parser more carefully: user-type events only produce
turns for `tool_result` blocks. A simple text user message is not captured as a
turn. The ingest upload view should handle this — let me check.

Correction: The upload endpoint in `apps/ingest/views.py` creates Message rows
from `ParsedTurn` objects. If the parser only emits assistant turns from a simple
conversation, the fixture needs to produce enough variety. The simplest approach:
include two assistant messages with different `message.id` values so the parser
emits 2 turns.

The fixture will contain:
```jsonl
{"type":"system","subtype":"init","session_id":"e2e-test-session-001"}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":"Hello! How can I help you today?"}]}}
{"type":"result","result":{"type":"text","text":"Hello! How can I help you today?"},"session_id":"e2e-test-session-001"}
{"type":"assistant","message":{"id":"msg_02","content":[{"type":"text","text":"I can help with coding, writing, and analysis."}]}}
{"type":"result","result":{"type":"text","text":"I can help with coding, writing, and analysis."},"session_id":"e2e-test-session-001"}
```

This produces 2 assistant `ParsedTurn` rows, which become 2 `Message` rows.

## 7. Conventions

All new specs follow the patterns in `multiplayer.spec.ts`:

- **Auth:** `newAuthedContext(browser, email, displayName)` per user
- **Setup:** REST API helpers for creating sessions/messages (fast, no UI interaction)
- **Assertions:** DOM state (`toBeVisible`, `toContainText`) + API verification (`listMessages`)
- **Streaming:** `.animate-pulse` for in-flight, absence for complete
- **No flaky waits:** Playwright auto-waiting only. No `setTimeout` or `sleep`.
- **Serial within file:** `test.describe.serial` where tests share state
- **Independent across files:** Each spec creates its own users. No cross-file coupling.
- **Context cleanup:** Each spec closes its browser contexts in `afterAll`

## 8. What does NOT change

- `multiplayer.spec.ts` — untouched
- `playwright.config.ts` — no changes needed (already discovers all `*.spec.ts`)
- `global-setup.ts` — no changes needed
- `e2e/helpers/auth.ts` — no changes needed
- `e2e/helpers/session.ts` — no changes needed (already has `createSession`, `listMessages`)
- Backend code — no changes. All tests exercise existing endpoints.
