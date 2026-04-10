import { test, expect } from "@playwright/test";

import { newAuthedContext, loginAs, getCsrfToken } from "../helpers/auth";
import { createSession } from "../helpers/session";
import { createShareToken } from "../helpers/share";

/**
 * Share token lifecycle E2E tests.
 *
 * Exercises the full create → view → revoke path for share tokens:
 *   1. Creating a share link via the SharePopover (UI flow).
 *   2. Navigating to the public share view as an authenticated user.
 *   3. Fetching the share API endpoint from an unauthenticated context.
 *   4. Revoking a share token via the SharePopover (UI flow).
 *   5. Navigating to an invalid share token shows an error page.
 *
 * Each test uses a distinct email address so user state never leaks
 * between tests (users are persisted for the lifetime of the sqlite
 * e2e database, which is reset between test runs by global-setup.ts).
 */
test.describe("Share flow", () => {
  test("create share link via popover", async ({ browser }) => {
    // Grant clipboard permissions so navigator.clipboard.writeText
    // doesn't throw inside the SharePopover handleCreate handler.
    const context = await browser.newContext({
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await context.newPage();
    await loginAs(page, "share-create@dimagi.com", "Share Create");

    const slug = await createSession(page, "Share popover test");
    await page.goto(`/ace/chat/${slug}`);

    // Wait for the WebSocket to connect and session.state to populate.
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // Click the "share" button to open the SharePopover.
    // Use exact:true to avoid matching the session title button which
    // contains the word "share" (e.g. "Share popover test").
    const shareButton = page.getByRole("button", { name: "share", exact: true });
    await expect(shareButton).toBeVisible({ timeout: 5_000 });
    await shareButton.click();

    // The popover should open with "Share links" header and "Create share link" button.
    await expect(page.getByText("Share links")).toBeVisible({ timeout: 3_000 });
    const createButton = page.getByRole("button", { name: "Create share link" });
    await expect(createButton).toBeVisible();
    await createButton.click();

    // After creating, "Link copied to clipboard" feedback should appear.
    await expect(page.getByText("Link copied to clipboard")).toBeVisible({
      timeout: 5_000,
    });

    // The token should appear in the "Active links" list with a "revoke" button.
    await expect(page.getByText("Active links")).toBeVisible({ timeout: 3_000 });
    await expect(
      page.getByRole("button", { name: "revoke", exact: true }),
    ).toBeVisible({ timeout: 3_000 });

    await context.close();
  });

  test("share link loads read-only view", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-view@dimagi.com",
      "Share View",
    );

    // Create a session and send a message so there's content to view.
    const slug = await createSession(page, "Read-only view test");
    await page.goto(`/ace/chat/${slug}`);

    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // Send a message and wait for the stream to complete.
    await textarea.fill("Hello share view");
    const sendButton = page.getByRole("button", { name: /^send$/ });
    await expect(sendButton).toBeEnabled({ timeout: 5_000 });
    await sendButton.click();

    // Wait for the streaming cursor to appear then disappear (stream complete).
    await expect(page.locator(".animate-pulse")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 10_000,
    });

    // Create a share token via the API helper.
    const tokenData = await createShareToken(page, slug);

    // Navigate to the public share view.
    await page.goto(`/ace/share/${tokenData.token}`);

    // The blue "read only" banner should be visible.
    await expect(
      page.getByText("Shared session — read only"),
    ).toBeVisible({ timeout: 10_000 });

    // The user message and echo response should both be visible.
    await expect(
      page.getByText("Hello share view", { exact: true }),
    ).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Echo: Hello share view/)).toBeVisible({
      timeout: 5_000,
    });

    // There should be no send textbox — the share view is read-only.
    await expect(page.getByRole("textbox")).not.toBeVisible();

    await context.close();
  });

  test("share API works without authentication", async ({ browser }) => {
    // Create a session and share token as an authenticated user.
    const { page: authedPage, context: authedContext } = await newAuthedContext(
      browser,
      "share-anon@dimagi.com",
      "Share Anon",
    );

    const slug = await createSession(authedPage, "Anon API test session");
    const tokenData = await createShareToken(authedPage, slug);

    // Create a fresh, unauthenticated browser context — no loginAs call.
    const anonContext = await browser.newContext();
    const anonPage = await anonContext.newPage();

    // Fetch the share API endpoint without any auth cookies.
    const resp = await anonPage.request.get(
      `/ace/api/share/${tokenData.token}`,
    );
    expect(resp.status()).toBe(200);

    const envelope = await resp.json();
    expect(envelope.error).toBeNull();
    expect(envelope.data).not.toBeNull();
    expect(envelope.data.title).toBe("Anon API test session");

    await anonContext.close();
    await authedContext.close();
  });

  test("revoke share token via popover", async ({ browser }) => {
    // Grant clipboard permissions so the create button works when we
    // later open the popover, and so re-loading tokens after revoke
    // doesn't race with clipboard API.
    const context = await browser.newContext({
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await context.newPage();
    await loginAs(page, "share-revoke@dimagi.com", "Share Revoke");

    // Create session and a share token via the API helper.
    const slug = await createSession(page, "Revoke test session");
    const tokenData = await createShareToken(page, slug);
    const tokenSuffix = tokenData.token.slice(-8);

    // Navigate to the chat page.
    await page.goto(`/ace/chat/${slug}`);

    // Wait for WebSocket to connect.
    const textarea = page.getByRole("textbox");
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toHaveAttribute("placeholder", /Type a message/, {
      timeout: 10_000,
    });

    // Open the share popover. Use exact:true to avoid matching the
    // session title button ("Revoke test session" contains "revoke").
    const shareButton = page.getByRole("button", { name: "share", exact: true });
    await expect(shareButton).toBeVisible({ timeout: 5_000 });
    await shareButton.click();

    // The popover opens and the token should be listed.
    await expect(page.getByText("Share links")).toBeVisible({ timeout: 3_000 });
    await expect(page.getByText("Active links")).toBeVisible({ timeout: 3_000 });

    // The token's last-8-chars display should be present.
    await expect(page.getByText(`...${tokenSuffix}`)).toBeVisible({
      timeout: 3_000,
    });

    // Click the "revoke" button (exact match to avoid the title button).
    await page.getByRole("button", { name: "revoke", exact: true }).click();

    // The token row should disappear from the popover.
    await expect(page.getByText(`...${tokenSuffix}`)).not.toBeVisible({
      timeout: 5_000,
    });

    // Confirm via API that the token now returns 404 with code "revoked".
    const checkResp = await page.request.get(
      `/ace/api/share/${tokenData.token}`,
    );
    expect(checkResp.status()).toBe(404);
    const checkEnvelope = await checkResp.json();
    expect(checkEnvelope.error?.code).toBe("revoked");

    await context.close();
  });

  test("invalid token shows error page", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "share-invalid@dimagi.com",
      "Share Invalid",
    );

    // Navigate to a completely bogus share token.
    await page.goto("/ace/share/totally-bogus-token");

    // The error page should show the "invalid or has expired" message.
    await expect(
      page.getByText("This share link is invalid or has expired."),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });
});
