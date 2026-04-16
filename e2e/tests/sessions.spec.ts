import { test, expect } from "@playwright/test";

import { newAuthedContext, getCsrfToken } from "../helpers/auth";
import { createSession } from "../helpers/session";

/**
 * Sessions page E2E tests.
 *
 * Exercises the full CRUD surface of the /ace/sessions route:
 *   1. Empty state message when a fresh user has no sessions.
 *   2. Sessions created via API appear in the list.
 *   3. Search box (debounced 300ms) filters by title.
 *   4. Status filter buttons (Active / Archived / Imported / All) show
 *      only the matching sessions.
 *   5. Dropdown → Archive archives the session (toast + Archived list);
 *      Dropdown → Restore returns it to Active.
 *   6. Dropdown → Delete opens a confirmation dialog; confirming deletes
 *      the session and shows a toast.
 *   7. Pagination: 25 sessions produce "Page 1 of 2", 20 items on page 1,
 *      click "Next →" → page 2 has 5 items.
 *
 * Each test uses a unique email address so user state never leaks between
 * tests (users persist for the lifetime of the SQLite e2e DB, which is
 * reset between runs by global-setup.ts).
 */
test.describe("Sessions page", () => {
  test("empty state when no sessions", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-empty@dimagi.com",
      "Lib Empty",
    );

    await page.goto("/ace/sessions");

    // The "All" filter shows every session regardless of status.
    // For a fresh user there are none, so we click "All" to bypass the
    // default "active" filter — this ensures the empty state appears even
    // if there are no active sessions.
    await page.getByRole("button", { name: "All" }).click();

    await expect(
      page.getByText("No sessions yet — start a chat."),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });

  test("sessions appear in list", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-list@dimagi.com",
      "Lib List",
    );

    // Create 3 sessions via the API helper.
    const titles = ["First session", "Second session", "Third session"];
    for (const title of titles) {
      await createSession(page, title);
    }

    await page.goto("/ace/sessions");

    // The sessions page defaults to the "Active" filter; all 3 were just created
    // so they are active.
    for (const title of titles) {
      await expect(page.getByText(title)).toBeVisible({ timeout: 10_000 });
    }

    await context.close();
  });

  test("search filters by title", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-search@dimagi.com",
      "Lib Search",
    );

    await createSession(page, "Alpha design");
    await createSession(page, "Beta review");
    await createSession(page, "Alpha followup");

    await page.goto("/ace/sessions");

    // Wait for the initial load to complete before typing.
    await expect(page.getByText("Alpha design")).toBeVisible({
      timeout: 10_000,
    });

    const searchInput = page.getByPlaceholder("Search titles…");
    await searchInput.fill("Alpha");

    // The component debounces the query by 300ms then fires the API call.
    // Wait generously past that.
    await page.waitForTimeout(500);

    // "Alpha design" and "Alpha followup" should be visible.
    await expect(page.getByText("Alpha design")).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Alpha followup")).toBeVisible({
      timeout: 5_000,
    });

    // "Beta review" must not appear once the filter is applied.
    await expect(page.getByText("Beta review")).not.toBeVisible();

    await context.close();
  });

  test("status filter shows only matching", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-filter@dimagi.com",
      "Lib Filter",
    );

    const slug1 = await createSession(page, "Active session");
    const slug2 = await createSession(page, "Soon archived");

    // Archive the second session directly via the API.
    const csrf = await getCsrfToken(page.context());
    const patchResp = await page.request.patch(`/ace/api/sessions/${slug2}`, {
      data: { status: "archived" },
      headers: { "X-CSRFToken": csrf },
    });
    expect(patchResp.ok()).toBeTruthy();

    await page.goto("/ace/sessions");

    // Default filter is "Active" — only slug1 shows.
    await expect(page.getByText("Active session")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Soon archived")).not.toBeVisible();

    // Switch to "Archived" filter.
    await page.getByRole("button", { name: "Archived" }).click();
    await expect(page.getByText("Soon archived")).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Active session")).not.toBeVisible();

    // "All" shows both.
    await page.getByRole("button", { name: "All" }).click();
    await expect(page.getByText("Active session")).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText("Soon archived")).toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });

  test("archive and restore a session", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-archive@dimagi.com",
      "Lib Archive",
    );

    await createSession(page, "Archivable session");

    await page.goto("/ace/sessions");

    // Wait for the session row to appear.
    const rowLocator = page.locator("div.group", {
      hasText: "Archivable session",
    });
    await expect(rowLocator).toBeVisible({ timeout: 10_000 });

    // Hover the row to reveal the MoreHorizontal trigger (opacity-0 → opacity-100).
    await rowLocator.hover();

    // Click the ghost icon button that contains the MoreHorizontal SVG.
    const triggerButton = rowLocator.getByRole("button");
    await triggerButton.click();

    // The dropdown menu appears; click "Archive".
    await page.getByRole("menuitem", { name: /Archive/i }).click();

    // Toast confirms the operation.
    await expect(page.getByText("Session archived")).toBeVisible({
      timeout: 5_000,
    });

    // After archiving, the page is still on "Active" filter so the row
    // should be gone.
    await expect(rowLocator).not.toBeVisible({ timeout: 5_000 });

    // Switch to "Archived" to find the session.
    await page.getByRole("button", { name: "Archived" }).click();

    const archivedRow = page.locator("div.group", {
      hasText: "Archivable session",
    });
    await expect(archivedRow).toBeVisible({ timeout: 5_000 });

    // Restore via the dropdown.
    await archivedRow.hover();
    const restoreTrigger = archivedRow.getByRole("button");
    await restoreTrigger.click();

    await page.getByRole("menuitem", { name: /Restore/i }).click();

    await expect(page.getByText("Session restored")).toBeVisible({
      timeout: 5_000,
    });

    // The session should no longer appear under "Archived".
    await expect(archivedRow).not.toBeVisible({ timeout: 5_000 });

    // Switch back to "Active" — it should be there again.
    await page.getByRole("button", { name: "Active" }).click();
    await expect(
      page.locator("div.group", { hasText: "Archivable session" }),
    ).toBeVisible({ timeout: 5_000 });

    await context.close();
  });

  test("delete a session with confirmation", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-delete@dimagi.com",
      "Lib Delete",
    );

    await createSession(page, "Deletable session");

    await page.goto("/ace/sessions");

    const rowLocator = page.locator("div.group", {
      hasText: "Deletable session",
    });
    await expect(rowLocator).toBeVisible({ timeout: 10_000 });

    // Hover to reveal the trigger, open the dropdown.
    await rowLocator.hover();
    const triggerButton = rowLocator.getByRole("button");
    await triggerButton.click();

    // Click "Delete" in the dropdown.
    await page.getByRole("menuitem", { name: /Delete/i }).click();

    // The confirmation dialog should appear.
    await expect(
      page.getByRole("heading", { name: "Delete session?" }),
    ).toBeVisible({ timeout: 5_000 });

    // Click the destructive "Delete" button in the dialog footer.
    // The dialog is rendered via Radix UI portal — scope to the open dialog
    // element directly rather than relying on ARIA role scoping, which can
    // miss portaled content in some Playwright versions.
    const dialogDeleteButton = page.locator('[role="dialog"]').getByRole("button", { name: "Delete" });
    await expect(dialogDeleteButton).toBeVisible({ timeout: 5_000 });
    await dialogDeleteButton.click();

    // Toast confirms deletion.
    await expect(page.getByText("Session deleted")).toBeVisible({
      timeout: 5_000,
    });

    // The row should be gone.
    await expect(rowLocator).not.toBeVisible({ timeout: 5_000 });

    await context.close();
  });

  test("pagination controls", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "lib-pagination@dimagi.com",
      "Lib Pagination",
    );

    // Create 25 sessions — page size is 20, so we expect 2 pages.
    for (let i = 1; i <= 25; i++) {
      await createSession(page, `Paginated session ${String(i).padStart(2, "0")}`);
    }

    await page.goto("/ace/sessions");

    // "All" filter to see all 25 regardless of status.
    await page.getByRole("button", { name: "All" }).click();

    // Wait for the list to load. The footer is only shown when totalPages > 1.
    await expect(page.getByText("Page 1 of 2")).toBeVisible({
      timeout: 10_000,
    });

    // Count the session rows on page 1 — should be 20.
    const rows = page.locator("div.divide-y > div.group");
    await expect(rows).toHaveCount(20, { timeout: 5_000 });

    // Navigate to page 2.
    await page.getByRole("button", { name: "Next →" }).click();

    await expect(page.getByText("Page 2 of 2")).toBeVisible({
      timeout: 5_000,
    });

    // Page 2 should have the remaining 5 sessions.
    await expect(rows).toHaveCount(5, { timeout: 5_000 });

    // "← Prev" navigates back.
    await page.getByRole("button", { name: "← Prev" }).click();
    await expect(page.getByText("Page 1 of 2")).toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });
});
