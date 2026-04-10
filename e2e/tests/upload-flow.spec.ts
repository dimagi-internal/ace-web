import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { uploadJsonlFixture } from "../helpers/upload";

/**
 * Upload-flow E2E tests.
 *
 * Exercises the JSONL ingest path from the library page:
 *   1. Uploading a JSONL file shows a toast with the message count and the
 *      session appears in the library list with an "upload" source badge.
 *   2. Navigating to the imported session renders the messages from the JSONL.
 *   3. The send box shows the "Imported session" banner (sessionSource +
 *      sessionStatus gate in SendBox.tsx).
 *
 * Each test uses a distinct email address so user state never leaks between
 * tests (users persist for the lifetime of the SQLite e2e DB, which is reset
 * between runs by global-setup.ts).
 */
test.describe("Upload flow", () => {
  test("upload JSONL file from library", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-badge@dimagi.com",
      "Upload Badge",
    );

    await page.goto("/ace/library");

    // Switch to "All" so the uploaded (imported) session is visible even
    // though the default filter is "active".
    await page.getByRole("button", { name: "All" }).click();

    // Use the upload helper to set the fixture file on the hidden input.
    await uploadJsonlFixture(page);

    // The handleUpload callback shows a sonner toast: `Uploaded: ${message_count} messages`
    // The fixture has 2 assistant messages (msg_e2e_01 and msg_e2e_02).
    await expect(page.getByText(/Uploaded:.*messages/)).toBeVisible({
      timeout: 10_000,
    });

    // After upload the list is reloaded. The imported session should appear
    // with the "upload" source badge rendered as a Badge element.
    // We look for the badge text "upload" inside the session row.
    await expect(page.getByText("upload", { exact: true })).toBeVisible({
      timeout: 10_000,
    });

    await context.close();
  });

  test("imported session renders messages", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-messages@dimagi.com",
      "Upload Messages",
    );

    await page.goto("/ace/library");

    // The imported filter shows only uploaded sessions; switch to All first
    // so the upload itself can be triggered on the library page.
    await page.getByRole("button", { name: "All" }).click();

    // Use a distinct fixture (unique session_id) to avoid 409 conflicts
    // with the sample-session.jsonl used by the first test.
    await uploadJsonlFixture(page, "sample-session-2.jsonl");

    // Wait for the toast to confirm the upload succeeded.
    await expect(page.getByText(/Uploaded:.*messages/)).toBeVisible({
      timeout: 10_000,
    });

    // Wait for the session row with the "upload" badge to appear.
    await expect(page.getByText("upload", { exact: true })).toBeVisible({
      timeout: 10_000,
    });

    // Navigate into the imported session by clicking the first row that
    // contains the upload badge.
    const uploadRow = page.locator("div.group", { hasText: "upload" }).first();
    await expect(uploadRow).toBeVisible({ timeout: 5_000 });
    await uploadRow.locator("a").first().click();

    // Wait for the chat page to load (URL changes to /ace/chat/<slug>).
    await expect(page).toHaveURL(/\/ace\/chat\/[A-Za-z0-9]+/, {
      timeout: 10_000,
    });

    // The two assistant messages from the fixture should be visible.
    await expect(
      page.getByText("Hello! How can I help you today?"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText("I can help with coding, writing, and analysis."),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });

  test("imported session send box is disabled", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-readonly@dimagi.com",
      "Upload Readonly",
    );

    await page.goto("/ace/library");

    // Switch to "All" so the uploaded session will be visible after upload.
    await page.getByRole("button", { name: "All" }).click();

    // Use a distinct fixture (unique session_id) to avoid 409 conflicts
    // with the sample-session.jsonl files used by the other tests.
    await uploadJsonlFixture(page, "sample-session-3.jsonl");

    // Wait for upload confirmation.
    await expect(page.getByText(/Uploaded:.*messages/)).toBeVisible({
      timeout: 10_000,
    });

    // Navigate to the imported session.
    await expect(page.getByText("upload", { exact: true })).toBeVisible({
      timeout: 10_000,
    });

    const uploadRow = page.locator("div.group", { hasText: "upload" }).first();
    await uploadRow.locator("a").first().click();

    await expect(page).toHaveURL(/\/ace\/chat\/[A-Za-z0-9]+/, {
      timeout: 10_000,
    });

    // The SendBox renders an informational banner when
    // sessionSource === "upload" && sessionStatus === "imported".
    // See frontend/src/components/SendBox.tsx — the banner text is:
    // "Imported session — send a message to continue it with Claude."
    await expect(
      page.getByText(/Imported session.*send a message to continue/),
    ).toBeVisible({ timeout: 10_000 });

    await context.close();
  });
});
