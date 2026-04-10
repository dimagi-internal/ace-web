import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { createSession, listMessages } from "../helpers/session";

/**
 * Single-player chat lifecycle E2E tests.
 *
 * Exercises the full browser → WebSocket → FakeCLIBackend → DOM path:
 *   1. /chat redirect creates a session and lands on /chat/:slug.
 *   2. Sending "Hello world" yields "Echo: Hello world" in the DOM,
 *      with a visible streaming cursor during the stream and a clean
 *      persisted row afterward.
 *   3. Clicking stop during a long in-flight stream cancels the turn
 *      and flips the assistant message to status="error".
 *   4. InlineTitleEdit lets the user rename the session in the header;
 *      the updated title shows in the library.
 *   5. RecentSessionsSidebar shows the current session by title.
 *
 * Each test uses a distinct email address so user state never leaks
 * between tests (users are persisted for the lifetime of the sqlite
 * e2e database, which is reset between test runs by global-setup.ts).
 */
test.describe("Chat lifecycle", () => {
  test("create session via /chat redirect", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lifecycle-create@dimagi.com",
      "Lifecycle Create",
    );

    // Navigating to /ace/chat triggers ChatRedirectPage, which calls
    // createSession() and then navigate(`/chat/${slug}`, { replace: true }).
    await page.goto("/ace/chat");

    // The URL should change to /ace/chat/<slug> once the redirect fires.
    // Slugs are base58-ish (alphanumeric, mixed case, no hyphens).
    await expect(page).toHaveURL(/\/ace\/chat\/[A-Za-z0-9]+/, { timeout: 10_000 });

    // The SendBox textarea should be visible and in the "Connecting…"
    // state until the WebSocket handshake completes and session.state
    // arrives; then the placeholder flips to "Type a message…".
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    await context.close();
  });

  test("type a message and receive streaming response", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lifecycle-stream@dimagi.com",
      "Lifecycle Stream",
    );

    const slug = await createSession(page, "Stream test");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // Type the message and send.
    await textarea.fill("Hello world");
    const sendButton = page.getByRole("button", { name: /^send$/ });
    await expect(sendButton).toBeEnabled({ timeout: 5_000 });
    await sendButton.click();

    // The textarea clears once the WebSocket receives draft.committed.
    await expect(textarea).toHaveValue("", { timeout: 5_000 });

    // The user bubble appears immediately (inserted by the
    // draft.committed reducer without waiting for a round-trip).
    await expect(page.getByText("Hello world", { exact: true })).toBeVisible();

    // The streaming cursor (animate-pulse caret inside the assistant
    // bubble) should appear while FakeCLIBackend is streaming and
    // then disappear once chat.stream_complete arrives.
    await expect(page.locator(".animate-pulse")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 10_000,
    });

    // The full echo response should be visible in the DOM.
    await expect(page.getByText(/Echo: Hello world/)).toBeVisible({
      timeout: 10_000,
    });

    // Verify the server-side rows are correct.
    const messages = await listMessages(page, slug);
    const userMsg = messages.find((m) => m.role === "user");
    const assistantMsg = messages.find((m) => m.role === "assistant");
    expect(userMsg?.plaintext).toBe("Hello world");
    expect(userMsg?.status).toBe("complete");
    expect(assistantMsg?.plaintext).toBe("Echo: Hello world");
    expect(assistantMsg?.status).toBe("complete");

    await context.close();
  });

  test("stop button cancels in-flight stream", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lifecycle-stop@dimagi.com",
      "Lifecycle Stop",
    );

    const slug = await createSession(page, "Stop test single-player");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // A moderately long prompt gives FakeCLIBackend (4-char chunks @
    // 100ms) a ~1.5s streaming window so we can click stop before the
    // turn completes.
    const prompt = "a moderately long prompt for stop testing end-to-end flow";
    await textarea.fill(prompt);
    const sendButton = page.getByRole("button", { name: /^send$/ });
    await expect(sendButton).toBeEnabled({ timeout: 5_000 });
    await sendButton.click();

    // Wait for the stop button to appear (the draft.committed reducer
    // inserts the assistant placeholder into React state, which flips
    // isStreaming to true, which causes SendBox to render the stop button).
    const stopButton = page.getByRole("button", { name: /^stop$/ });
    await expect(stopButton).toBeVisible({ timeout: 5_000 });
    await stopButton.click();

    // After the stop the streaming cursor disappears and the stop
    // button is gone (isStreaming flips back to false).
    await expect(stopButton).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 5_000,
    });

    // The server-side assistant row should have status="error" with a
    // "cancel" detail. Poll because the DB write may lag the UI update
    // by a beat.
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

    const finalMessages = await listMessages(page, slug);
    const assistant = finalMessages.find((m) => m.role === "assistant");
    expect(assistant?.error_detail ?? "").toMatch(/cancel/i);

    await context.close();
  });

  test("inline title edit updates header and library", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lifecycle-title@dimagi.com",
      "Lifecycle Title",
    );

    // Create session with no initial title so the header shows "Untitled".
    const slug = await createSession(page, "");
    await page.goto(`/ace/chat/${slug}`);

    // Wait for the WebSocket so meta is loaded and InlineTitleEdit renders.
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // InlineTitleEdit renders the title (or "Untitled") as a button.
    // Clicking it opens the edit input.
    const titleButton = page.getByRole("button", { name: /Untitled/i });
    await expect(titleButton).toBeVisible({ timeout: 5_000 });
    await titleButton.click();

    // The input appears and should be focused automatically (autoFocus).
    const titleInput = page.locator(
      "input.rounded.border.border-ring",
    );
    await expect(titleInput).toBeVisible({ timeout: 3_000 });

    const newTitle = "My renamed session";
    await titleInput.fill(newTitle);
    await titleInput.press("Enter");

    // The input is replaced by the button again, now showing the new title.
    await expect(page.getByRole("button", { name: newTitle })).toBeVisible({
      timeout: 5_000,
    });

    // Navigate to the library and verify the session shows the updated title.
    await page.goto("/ace/library");
    // Library filters to "active" by default, which includes our session.
    await expect(page.getByText(newTitle)).toBeVisible({ timeout: 10_000 });

    await context.close();
  });

  test("recent sessions sidebar shows current session", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lifecycle-sidebar@dimagi.com",
      "Lifecycle Sidebar",
    );

    const sessionTitle = "Sidebar visibility test";
    const slug = await createSession(page, sessionTitle);
    await page.goto(`/ace/chat/${slug}`);

    // Wait for the WebSocket so the sidebar's useRecentSessions hook
    // has had a chance to fetch. The hook runs on mount; by the time
    // the textarea is ready the initial fetch should have resolved.
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // The RecentSessionsSidebar renders session titles as <Link> elements
    // inside the <aside>. Look for the title in the sidebar specifically.
    const sidebar = page.locator("aside");
    await expect(sidebar.getByText(sessionTitle)).toBeVisible({
      timeout: 10_000,
    });

    await context.close();
  });
});
