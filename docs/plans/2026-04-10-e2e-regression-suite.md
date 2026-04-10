# E2E Regression Suite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the Playwright E2E suite from 5 multi-player tests to ~28 tests covering every testable user flow in ace-web.

**Architecture:** 5 new spec files + 2 new helpers + 1 JSONL fixture. No backend changes. Tests run against the existing `config/settings/e2e.py` + `config/asgi_e2e.py` stack (SQLite, InMemoryChannelLayer, FakeCLIBackend, fakeredis). All new specs follow the patterns in `e2e/tests/multiplayer.spec.ts`.

**Tech Stack:** Playwright, TypeScript, existing Django E2E infrastructure.

**Spec:** `docs/specs/2026-04-10-e2e-regression-suite-design.md`

---

## File plan

### New files

```
e2e/helpers/share.ts                  # createShareToken, revokeShareToken
e2e/helpers/upload.ts                 # uploadJsonl
e2e/fixtures/sample-session.jsonl     # minimal valid JSONL for ingest
e2e/tests/chat-lifecycle.spec.ts      # single-player chat (5 tests)
e2e/tests/library.spec.ts            # library CRUD (7 tests)
e2e/tests/share-flow.spec.ts         # share token lifecycle (5 tests)
e2e/tests/upload-flow.spec.ts        # JSONL upload (3 tests)
e2e/tests/settings.spec.ts           # personal token CRUD (3 tests)
```

### No modifications to existing files

---

## Task 1: JSONL fixture + upload helper + share helper

These are prerequisites for later tasks. No tests to run yet — they're consumed by the spec files.

**Files:**
- Create: `e2e/fixtures/sample-session.jsonl`
- Create: `e2e/helpers/share.ts`
- Create: `e2e/helpers/upload.ts`

- [ ] **Step 1: Create the JSONL fixture**

Create `e2e/fixtures/sample-session.jsonl`. This must match the format that `apps/ingest/parser.py` expects. The parser extracts assistant turns from `type: "assistant"` events. Each distinct `message.id` produces a separate turn.

```jsonl
{"type":"system","subtype":"init","session_id":"e2e-test-session-001"}
{"type":"assistant","message":{"id":"msg_e2e_01","content":[{"type":"text","text":"Hello! How can I help you today?"}]}}
{"type":"result","result":{"type":"text","text":"Hello! How can I help you today?"},"session_id":"e2e-test-session-001"}
{"type":"assistant","message":{"id":"msg_e2e_02","content":[{"type":"text","text":"I can help with coding, writing, and analysis."}]}}
{"type":"result","result":{"type":"text","text":"I can help with coding, writing, and analysis."},"session_id":"e2e-test-session-001"}
```

This produces 2 `ParsedTurn` rows (both assistant), which become 2 `Message` rows in the DB.

- [ ] **Step 2: Create the share helper**

Create `e2e/helpers/share.ts`:

```typescript
import type { Page } from "@playwright/test";

import { getCsrfToken } from "./auth";

type Envelope<T> = {
  data: T | null;
  error: { code: string; message: string } | null;
};

interface ShareTokenData {
  token: string;
  url: string;
  created_at: string;
}

/**
 * Create a share token for a session via the REST API.
 * Requires the page to be authenticated as a session owner or editor.
 */
export async function createShareToken(
  page: Page,
  slug: string,
): Promise<ShareTokenData> {
  const csrf = await getCsrfToken(page.context());
  const resp = await page.request.post(`/ace/api/sessions/${slug}/share`, {
    headers: { "X-CSRFToken": csrf },
  });
  if (!resp.ok()) {
    throw new Error(
      `createShareToken failed: ${resp.status()} ${await resp.text()}`,
    );
  }
  const envelope = (await resp.json()) as Envelope<ShareTokenData>;
  if (envelope.error) {
    throw new Error(
      `createShareToken error: ${JSON.stringify(envelope.error)}`,
    );
  }
  return envelope.data!;
}

/**
 * Revoke a share token via the REST API.
 */
export async function revokeShareToken(
  page: Page,
  slug: string,
  token: string,
): Promise<void> {
  const csrf = await getCsrfToken(page.context());
  const resp = await page.request.delete(
    `/ace/api/sessions/${slug}/share/${token}`,
    { headers: { "X-CSRFToken": csrf } },
  );
  if (!resp.ok()) {
    throw new Error(
      `revokeShareToken failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}
```

- [ ] **Step 3: Create the upload helper**

Create `e2e/helpers/upload.ts`:

```typescript
import type { Page } from "@playwright/test";
import path from "path";

const FIXTURES_DIR = path.resolve(__dirname, "..", "fixtures");

/**
 * Upload a JSONL fixture file via the library page's hidden file input.
 * The page must be on /ace/library and authenticated.
 */
export async function uploadJsonlFixture(
  page: Page,
  filename: string = "sample-session.jsonl",
): Promise<void> {
  const filePath = path.join(FIXTURES_DIR, filename);
  const fileInput = page.locator('input[type="file"][accept=".jsonl"]');
  await fileInput.setInputFiles(filePath);
}
```

- [ ] **Step 4: Commit**

```bash
git add e2e/fixtures/sample-session.jsonl e2e/helpers/share.ts e2e/helpers/upload.ts
git commit -m "test(e2e): add JSONL fixture, share helper, and upload helper"
```

---

## Task 2: `chat-lifecycle.spec.ts`

**Files:**
- Create: `e2e/tests/chat-lifecycle.spec.ts`

- [ ] **Step 1: Write the spec**

Create `e2e/tests/chat-lifecycle.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { createSession, listMessages } from "../helpers/session";

/**
 * Single-player chat lifecycle E2E tests.
 *
 * Exercises the basic chat flow through the FakeCLIBackend:
 * create a session, type, stream, stop, edit title. Complements
 * the multi-player tests in multiplayer.spec.ts which focus on
 * WebSocket collaboration between two users.
 */
test.describe("Chat lifecycle", () => {
  test("create session via /chat redirect", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "chat-lifecycle@dimagi.com",
      "ChatUser",
    );

    await page.goto("/ace/chat");
    // ChatRedirectPage creates a session and redirects to /ace/chat/:slug
    await expect(page).toHaveURL(/\/ace\/chat\/[a-zA-Z0-9]+/, {
      timeout: 10_000,
    });
    // The send box should be visible after the WebSocket connects
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    await context.close();
  });

  test("type a message and receive streaming response", async ({
    browser,
  }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "chat-stream@dimagi.com",
      "StreamUser",
    );

    const slug = await createSession(page, "Stream test");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // Type and send a message
    await textarea.fill("Hello world");
    const sendButton = page.getByRole("button", { name: /^send$/ });
    await expect(sendButton).toBeEnabled({ timeout: 5_000 });
    await sendButton.click();

    // Textarea clears after send
    await expect(textarea).toHaveValue("", { timeout: 5_000 });

    // User message appears
    await expect(
      page.getByText("Hello world", { exact: true }),
    ).toBeVisible();

    // Streaming cursor appears then disappears
    await expect(page.locator(".animate-pulse")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 10_000,
    });

    // FakeCLIBackend echoes: "Echo: Hello world"
    await expect(page.getByText(/Echo: Hello world/)).toBeVisible({
      timeout: 10_000,
    });

    // Verify persisted state
    const messages = await listMessages(page, slug);
    const userMsg = messages.find((m) => m.role === "user");
    const assistantMsg = messages.find((m) => m.role === "assistant");
    expect(userMsg?.plaintext).toBe("Hello world");
    expect(userMsg?.status).toBe("complete");
    expect(assistantMsg?.status).toBe("complete");
    expect(assistantMsg?.plaintext).toBe("Echo: Hello world");

    await context.close();
  });

  test("stop button cancels in-flight stream", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "chat-stop@dimagi.com",
      "StopUser",
    );

    const slug = await createSession(page, "Stop test");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // Use a long prompt so FakeCLIBackend streams long enough to click stop
    const prompt =
      "a moderately long prompt to give us time to click the stop button";
    await textarea.fill(prompt);
    const sendButton = page.getByRole("button", { name: /^send$/ });
    await expect(sendButton).toBeEnabled({ timeout: 5_000 });
    await sendButton.click();

    // Wait for streaming to start, then click stop
    const stopButton = page.getByRole("button", { name: /^stop$/ });
    await expect(stopButton).toBeVisible({ timeout: 5_000 });
    await stopButton.click();

    // Stop button disappears, streaming cursor clears
    await expect(stopButton).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 5_000,
    });

    // Verify persisted state: assistant message has error status
    await expect
      .poll(
        async () => {
          const messages = await listMessages(page, slug);
          const assistant = messages.find((m) => m.role === "assistant");
          return assistant?.status ?? null;
        },
        { timeout: 10_000 },
      )
      .toBe("error");

    const messages = await listMessages(page, slug);
    const assistant = messages.find((m) => m.role === "assistant");
    expect(assistant?.error_detail ?? "").toMatch(/cancel/i);

    await context.close();
  });

  test("inline title edit updates header and library", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "chat-title@dimagi.com",
      "TitleUser",
    );

    const slug = await createSession(page, "");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });

    // The InlineTitleEdit component renders an input on click.
    // Find it and type a title.
    const titleArea = page.locator("header input");
    // If no input is visible, click the title text to activate edit mode
    const titleText = page.locator("header").getByText("Untitled");
    if (await titleText.isVisible()) {
      await titleText.click();
    }
    await titleArea.fill("My test session");
    await titleArea.press("Enter");

    // Navigate to library and verify the title shows
    await page.goto("/ace/library");
    await expect(page.getByText("My test session")).toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });

  test("recent sessions sidebar shows current session", async ({
    browser,
  }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "chat-sidebar@dimagi.com",
      "SidebarUser",
    );

    const slug = await createSession(page, "Sidebar visible test");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });

    // The RecentSessionsSidebar should contain a link to the current session
    const sidebar = page.locator('[class*="sidebar"], aside, nav').first();
    await expect(
      sidebar.getByText("Sidebar visible test"),
    ).toBeVisible({ timeout: 5_000 });

    await context.close();
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd e2e && npx playwright test tests/chat-lifecycle.spec.ts --reporter=list`
Expected: 5 passed. If any fail, debug and fix.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/chat-lifecycle.spec.ts
git commit -m "test(e2e): add chat lifecycle — create, stream, stop, title, sidebar"
```

---

## Task 3: `library.spec.ts`

**Files:**
- Create: `e2e/tests/library.spec.ts`

- [ ] **Step 1: Write the spec**

Create `e2e/tests/library.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

import { newAuthedContext, postJson } from "../helpers/auth";
import { createSession } from "../helpers/session";

/**
 * Library page E2E tests.
 *
 * Exercises session list CRUD: empty state, search, filter, archive,
 * delete, pagination. Sessions are created via the REST API for speed;
 * tests exercise the library UI.
 */
test.describe("Library", () => {
  test("empty state when no sessions", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-empty@dimagi.com",
      "EmptyUser",
    );

    await page.goto("/ace/library");
    await expect(
      page.getByText("No sessions yet — start a chat."),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });

  test("sessions appear in list", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-list@dimagi.com",
      "ListUser",
    );

    await createSession(page, "Alpha session");
    await createSession(page, "Beta session");
    await createSession(page, "Gamma session");

    await page.goto("/ace/library");
    await expect(page.getByText("Alpha session")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Beta session")).toBeVisible();
    await expect(page.getByText("Gamma session")).toBeVisible();

    await context.close();
  });

  test("search filters by title", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-search@dimagi.com",
      "SearchUser",
    );

    await createSession(page, "Alpha design");
    await createSession(page, "Beta review");
    await createSession(page, "Alpha followup");

    await page.goto("/ace/library");
    // Wait for sessions to load
    await expect(page.getByText("Alpha design")).toBeVisible({
      timeout: 10_000,
    });

    // Type in the search box
    const searchInput = page.getByPlaceholder("Search titles");
    await searchInput.fill("Alpha");

    // Wait for debounced search (300ms + request)
    await expect(page.getByText("Alpha design")).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Alpha followup")).toBeVisible();
    await expect(page.getByText("Beta review")).not.toBeVisible();

    await context.close();
  });

  test("status filter shows only matching", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-filter@dimagi.com",
      "FilterUser",
    );

    const activeSlug = await createSession(page, "Active session");
    const archiveSlug = await createSession(page, "Archived session");

    // Archive one session via API
    const csrf = (await page.context().cookies()).find(
      (c) => c.name === "csrftoken",
    )?.value;
    await page.request.patch(`/ace/api/sessions/${archiveSlug}`, {
      data: { status: "archived" },
      headers: { "X-CSRFToken": csrf ?? "" },
    });

    await page.goto("/ace/library");
    // Default filter is "Active"
    await expect(page.getByText("Active session")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Archived session")).not.toBeVisible();

    // Click "Archived" filter
    await page.getByRole("button", { name: "Archived" }).click();
    await expect(page.getByText("Archived session")).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Active session")).not.toBeVisible();

    await context.close();
  });

  test("archive and restore a session", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-archive@dimagi.com",
      "ArchiveUser",
    );

    await createSession(page, "Archive me");

    await page.goto("/ace/library");
    await expect(page.getByText("Archive me")).toBeVisible({
      timeout: 10_000,
    });

    // Open the row's dropdown menu and click Archive
    const row = page.locator("div").filter({ hasText: "Archive me" }).first();
    await row.hover();
    await row.getByRole("button").filter({ has: page.locator("svg") }).click();
    await page.getByText("Archive").click();

    // Toast confirmation
    await expect(page.getByText("Session archived")).toBeVisible({
      timeout: 5_000,
    });

    // Session gone from active list
    await expect(page.getByText("Archive me")).not.toBeVisible({
      timeout: 5_000,
    });

    // Switch to Archived filter — session is there
    await page.getByRole("button", { name: "Archived" }).click();
    await expect(page.getByText("Archive me")).toBeVisible({ timeout: 5_000 });

    // Restore it
    const archivedRow = page
      .locator("div")
      .filter({ hasText: "Archive me" })
      .first();
    await archivedRow.hover();
    await archivedRow
      .getByRole("button")
      .filter({ has: page.locator("svg") })
      .click();
    await page.getByText("Restore").click();
    await expect(page.getByText("Session restored")).toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });

  test("delete a session with confirmation", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-delete@dimagi.com",
      "DeleteUser",
    );

    await createSession(page, "Delete me");

    await page.goto("/ace/library");
    await expect(page.getByText("Delete me")).toBeVisible({
      timeout: 10_000,
    });

    // Open dropdown → Delete
    const row = page.locator("div").filter({ hasText: "Delete me" }).first();
    await row.hover();
    await row.getByRole("button").filter({ has: page.locator("svg") }).click();
    await page.getByText("Delete").first().click();

    // Confirmation dialog
    await expect(page.getByText("Delete session?")).toBeVisible({
      timeout: 3_000,
    });
    await expect(page.getByText(/Delete me/)).toBeVisible();

    // Confirm deletion
    await page.getByRole("button", { name: "Delete" }).last().click();

    // Toast + session gone
    await expect(page.getByText("Session deleted")).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Delete me")).not.toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });

  test("pagination controls", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-page@dimagi.com",
      "PageUser",
    );

    // Create 25 sessions
    for (let i = 0; i < 25; i++) {
      await createSession(page, `Paginated ${String(i).padStart(2, "0")}`);
    }

    await page.goto("/ace/library");
    // Wait for first page to load
    await expect(page.getByText(/Page 1 of 2/)).toBeVisible({
      timeout: 10_000,
    });

    // Page 1 has 20 items
    const rows = page.locator('[class*="divide-y"] > div');
    await expect(rows).toHaveCount(20, { timeout: 5_000 });

    // Navigate to page 2
    await page.getByRole("button", { name: /Next/ }).click();
    await expect(page.getByText(/Page 2 of 2/)).toBeVisible({
      timeout: 5_000,
    });
    await expect(rows).toHaveCount(5, { timeout: 5_000 });

    await context.close();
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd e2e && npx playwright test tests/library.spec.ts --reporter=list`
Expected: 7 passed. If any fail, debug and fix.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/library.spec.ts
git commit -m "test(e2e): add library — empty state, search, filter, archive, delete, pagination"
```

---

## Task 4: `share-flow.spec.ts`

**Files:**
- Create: `e2e/tests/share-flow.spec.ts`

- [ ] **Step 1: Write the spec**

Create `e2e/tests/share-flow.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { createSession, listMessages } from "../helpers/session";
import { createShareToken, revokeShareToken } from "../helpers/share";

/**
 * Share token lifecycle E2E tests.
 *
 * Exercises the full share flow: create a token via the UI popover,
 * verify the read-only view works for authenticated and anonymous
 * users, revoke the token, and verify revoked tokens return errors.
 */
test.describe("Share flow", () => {
  test("create share link via popover", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-create@dimagi.com",
      "ShareCreator",
    );

    const slug = await createSession(page, "Share test session");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });

    // Click the share button to open the popover
    await page.getByRole("button", { name: "share" }).click();
    await expect(page.getByText("Share links")).toBeVisible({
      timeout: 3_000,
    });

    // Create a share link
    await page.getByRole("button", { name: "Create share link" }).click();

    // "Link copied to clipboard" feedback
    await expect(page.getByText("Link copied to clipboard")).toBeVisible({
      timeout: 5_000,
    });

    // Token appears in the active links list (last 8 chars shown)
    await expect(page.locator("span.font-mono")).toBeVisible({
      timeout: 3_000,
    });

    await context.close();
  });

  test("share link loads read-only view", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-view@dimagi.com",
      "ShareViewer",
    );

    // Create a session with a message via chat
    const slug = await createSession(page, "Viewable session");
    await page.goto(`/ace/chat/${slug}`);
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });
    await textarea.fill("Hello from owner");
    const sendButton = page.getByRole("button", { name: /^send$/ });
    await expect(sendButton).toBeEnabled({ timeout: 5_000 });
    await sendButton.click();
    // Wait for streaming to complete
    await expect(page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 10_000,
    });

    // Create share token via API
    const tokenData = await createShareToken(page, slug);

    // Navigate to the share URL
    await page.goto(`/ace/share/${tokenData.token}`);

    // Verify read-only view
    await expect(
      page.getByText("Shared session — read only"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Viewable session")).toBeVisible();
    await expect(page.getByText("Hello from owner")).toBeVisible();
    await expect(page.getByText(/Echo: Hello from owner/)).toBeVisible();

    // No send box
    await expect(page.getByRole("textbox")).not.toBeVisible();

    await context.close();
  });

  test("share API works without authentication", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-anon@dimagi.com",
      "ShareAnon",
    );

    const slug = await createSession(page, "Anon viewable");
    const tokenData = await createShareToken(page, slug);

    // Make a raw request without cookies (unauthenticated)
    const anonContext = await browser.newContext();
    const anonPage = await anonContext.newPage();
    const resp = await anonPage.request.get(
      `/ace/api/share/${tokenData.token}`,
    );
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data.title).toBe("Anon viewable");

    await context.close();
    await anonContext.close();
  });

  test("revoke share token via popover", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-revoke@dimagi.com",
      "ShareRevoker",
    );

    const slug = await createSession(page, "Revoke test");
    const tokenData = await createShareToken(page, slug);

    // Verify token works before revocation
    const resp = await page.request.get(
      `/ace/api/share/${tokenData.token}`,
    );
    expect(resp.status()).toBe(200);

    // Navigate to chat and open share popover
    await page.goto(`/ace/chat/${slug}`);
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: "share" }).click();
    await expect(page.getByText("Share links")).toBeVisible({
      timeout: 3_000,
    });

    // Click revoke
    await page.getByRole("button", { name: "revoke" }).click();

    // Token disappears from list
    await expect(page.locator("span.font-mono")).not.toBeVisible({
      timeout: 5_000,
    });

    // Verify API returns 404 with "revoked" code
    const revokedResp = await page.request.get(
      `/ace/api/share/${tokenData.token}`,
    );
    expect(revokedResp.status()).toBe(404);
    const body = await revokedResp.json();
    expect(body.error.code).toBe("revoked");

    await context.close();
  });

  test("invalid token shows error page", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-invalid@dimagi.com",
      "ShareInvalid",
    );

    await page.goto("/ace/share/totally-bogus-token");
    await expect(
      page.getByText("This share link is invalid or has expired."),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd e2e && npx playwright test tests/share-flow.spec.ts --reporter=list`
Expected: 5 passed. If any fail, debug and fix.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/share-flow.spec.ts
git commit -m "test(e2e): add share flow — create, view, anon API, revoke, invalid"
```

---

## Task 5: `upload-flow.spec.ts`

**Files:**
- Create: `e2e/tests/upload-flow.spec.ts`

- [ ] **Step 1: Write the spec**

Create `e2e/tests/upload-flow.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { uploadJsonlFixture } from "../helpers/upload";

/**
 * JSONL upload E2E tests.
 *
 * Exercises the ingest flow: upload a .jsonl file from the library
 * page, verify it appears in the list, open it, verify messages
 * render and the session is read-only.
 */
test.describe("Upload flow", () => {
  test("upload JSONL file from library", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-test@dimagi.com",
      "UploadUser",
    );

    await page.goto("/ace/library");
    // Wait for the page to be ready (empty state or existing sessions)
    await expect(
      page.getByRole("button", { name: /Upload/ }),
    ).toBeVisible({ timeout: 10_000 });

    // Upload the fixture
    await uploadJsonlFixture(page);

    // Toast with message count
    await expect(page.getByText(/Uploaded.*messages/)).toBeVisible({
      timeout: 10_000,
    });

    // Session appears in the list with "upload" source badge
    await expect(page.getByText("upload").first()).toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });

  test("imported session renders messages", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-view@dimagi.com",
      "UploadViewer",
    );

    await page.goto("/ace/library");
    await expect(
      page.getByRole("button", { name: /Upload/ }),
    ).toBeVisible({ timeout: 10_000 });

    await uploadJsonlFixture(page);
    await expect(page.getByText(/Uploaded.*messages/)).toBeVisible({
      timeout: 10_000,
    });

    // Click on the imported session to open it
    // The session title is empty (imported sessions have no title),
    // so look for the "Untitled" link
    await page.getByText("Untitled").first().click();

    // Verify messages from the JSONL render
    await expect(
      page.getByText("Hello! How can I help you today?"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText("I can help with coding, writing, and analysis."),
    ).toBeVisible();

    await context.close();
  });

  test("imported session send box is disabled", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-readonly@dimagi.com",
      "UploadReadonly",
    );

    await page.goto("/ace/library");
    await expect(
      page.getByRole("button", { name: /Upload/ }),
    ).toBeVisible({ timeout: 10_000 });

    await uploadJsonlFixture(page);
    await expect(page.getByText(/Uploaded.*messages/)).toBeVisible({
      timeout: 10_000,
    });

    // Navigate to the imported session
    // Switch to "Imported" filter to find it easily
    await page.getByRole("button", { name: "Imported" }).click();
    await page.getByText("Untitled").first().click();

    // The send box should indicate the session is read-only.
    // For imported sessions, the textarea is disabled and/or shows
    // an "imported" indicator.
    const textarea = page.getByRole("textbox");
    // Either the textarea is disabled or not present
    const isDisabled = await textarea.isDisabled().catch(() => true);
    expect(isDisabled).toBe(true);

    await context.close();
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd e2e && npx playwright test tests/upload-flow.spec.ts --reporter=list`
Expected: 3 passed. If any fail, debug and fix.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/upload-flow.spec.ts
git commit -m "test(e2e): add upload flow — upload, view messages, read-only"
```

---

## Task 6: `settings.spec.ts`

**Files:**
- Create: `e2e/tests/settings.spec.ts`

- [ ] **Step 1: Write the spec**

Create `e2e/tests/settings.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";

/**
 * Settings page E2E tests.
 *
 * Exercises personal token CRUD: create, view in list, revoke.
 */
test.describe("Settings — personal tokens", () => {
  test("create a personal token", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "settings-create@dimagi.com",
      "SettingsUser",
    );

    await page.goto("/ace/settings");
    await expect(page.getByText("Upload tokens")).toBeVisible({
      timeout: 10_000,
    });

    // Click "Create token"
    await page.getByRole("button", { name: /Create token/ }).click();

    // Dialog appears
    await expect(page.getByText("Create upload token")).toBeVisible({
      timeout: 3_000,
    });

    // Type label and create
    await page.getByPlaceholder("Token label").fill("test-laptop");
    await page.getByRole("button", { name: "Create" }).click();

    // Raw token dialog appears
    await expect(page.getByText("Token created")).toBeVisible({
      timeout: 5_000,
    });
    // A code element contains the raw token
    const tokenEl = page.locator("code");
    await expect(tokenEl).toBeVisible();
    const rawToken = await tokenEl.textContent();
    expect(rawToken).toBeTruthy();
    expect(rawToken!.length).toBeGreaterThan(10);

    // Dismiss
    await page.getByRole("button", { name: /I've saved this/ }).click();
    await expect(page.getByText("Token created")).not.toBeVisible();

    await context.close();
  });

  test("token appears in list after creation", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "settings-list@dimagi.com",
      "ListUser",
    );

    await page.goto("/ace/settings");
    await expect(page.getByText("Upload tokens")).toBeVisible({
      timeout: 10_000,
    });

    // Create a token
    await page.getByRole("button", { name: /Create token/ }).click();
    await page.getByPlaceholder("Token label").fill("my-token");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Token created")).toBeVisible({
      timeout: 5_000,
    });
    await page.getByRole("button", { name: /I've saved this/ }).click();

    // Token visible in the list
    await expect(page.getByText("my-token")).toBeVisible({ timeout: 5_000 });

    await context.close();
  });

  test("revoke a token", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "settings-revoke@dimagi.com",
      "RevokeUser",
    );

    await page.goto("/ace/settings");
    await expect(page.getByText("Upload tokens")).toBeVisible({
      timeout: 10_000,
    });

    // Create a token first
    await page.getByRole("button", { name: /Create token/ }).click();
    await page.getByPlaceholder("Token label").fill("revoke-me");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Token created")).toBeVisible({
      timeout: 5_000,
    });
    await page.getByRole("button", { name: /I've saved this/ }).click();

    // Token visible
    await expect(page.getByText("revoke-me")).toBeVisible({ timeout: 5_000 });

    // Click the revoke/delete button (Trash2 icon button in the row)
    const tokenRow = page.locator("div").filter({ hasText: "revoke-me" });
    await tokenRow.getByRole("button").click();

    // Toast confirmation
    await expect(page.getByText("Token revoked")).toBeVisible({
      timeout: 5_000,
    });

    // Token gone from list
    await expect(page.getByText("revoke-me")).not.toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd e2e && npx playwright test tests/settings.spec.ts --reporter=list`
Expected: 3 passed. If any fail, debug and fix.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/settings.spec.ts
git commit -m "test(e2e): add settings — token create, list, revoke"
```

---

## Task 7: Full suite run

- [ ] **Step 1: Run the entire E2E suite**

Run: `cd e2e && npx playwright test --reporter=list`
Expected: ~28 tests pass (5 existing + 23 new).

If any tests fail due to flaky selectors or timing, fix them in the relevant spec file and re-run.

- [ ] **Step 2: Run backend tests for sanity**

Run: `/Users/jjackson/emdash-projects/ace-web/.venv/bin/pytest -v`
Expected: all pass (no backend changes, so this is a sanity check).

- [ ] **Step 3: Commit any fixups**

If any fixups were needed:
```bash
git add -A
git commit -m "fix(e2e): test stabilization"
```
