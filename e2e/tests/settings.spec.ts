import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";

/**
 * Settings page E2E tests.
 *
 * Exercises the upload-token management surface at /ace/settings:
 *   1. Creating a personal token shows the raw token in a "Token created"
 *      dialog that can be dismissed with "I've saved this".
 *   2. After creation the token's label appears in the token list.
 *   3. Clicking the Trash2 icon button for a token revokes it, shows a
 *      "Token revoked" toast, and removes the row from the list.
 *
 * Each test uses a distinct email address so user state never leaks between
 * tests (users persist for the lifetime of the SQLite e2e DB, which is reset
 * between runs by global-setup.ts).
 */
test.describe("Settings page", () => {
  test("create a personal token", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "settings-create@dimagi.com",
      "Settings Create",
    );

    await page.goto("/ace/settings");

    // The page heading should say "Settings"; the section heading "Upload tokens".
    await expect(
      page.getByRole("heading", { name: "Settings" }),
    ).toBeVisible({ timeout: 10_000 });

    // Click "Create token" to open the create dialog.
    await page.getByRole("button", { name: /Create token/i }).click();

    // The dialog should appear with the correct title and description.
    await expect(
      page.getByRole("heading", { name: "Create upload token" }),
    ).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Give this token a label")).toBeVisible();

    // Fill in the label and click "Create".
    const labelInput = page.getByPlaceholder("Token label");
    await labelInput.fill("my-laptop");
    await page.locator('[role="dialog"]').getByRole("button", { name: "Create" }).click();

    // The "Token created" dialog should appear next.
    await expect(
      page.getByRole("heading", { name: "Token created" }),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByText("Copy this token now"),
    ).toBeVisible();

    // The raw token should be inside a <code> element.
    const codeEl = page.locator('[role="dialog"] code');
    await expect(codeEl).toBeVisible({ timeout: 5_000 });
    const rawToken = await codeEl.textContent();
    expect(rawToken).toBeTruthy();
    expect((rawToken ?? "").length).toBeGreaterThan(10);

    // Dismiss with "I've saved this".
    await page.getByRole("button", { name: "I've saved this" }).click();

    // The dialog should close.
    await expect(
      page.getByRole("heading", { name: "Token created" }),
    ).not.toBeVisible({ timeout: 5_000 });

    await context.close();
  });

  test("token appears in list after creation", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "settings-list@dimagi.com",
      "Settings List",
    );

    await page.goto("/ace/settings");

    // Open the create dialog.
    await page.getByRole("button", { name: /Create token/i }).click();
    await expect(
      page.getByRole("heading", { name: "Create upload token" }),
    ).toBeVisible({ timeout: 5_000 });

    // Label the token and create it.
    await page.getByPlaceholder("Token label").fill("my-token");
    await page.locator('[role="dialog"]').getByRole("button", { name: "Create" }).click();

    // Dismiss the raw-token dialog.
    await expect(
      page.getByRole("heading", { name: "Token created" }),
    ).toBeVisible({ timeout: 5_000 });
    await page.getByRole("button", { name: "I've saved this" }).click();

    // After dismissal the token list should show the new row with the label.
    await expect(page.getByText("my-token")).toBeVisible({ timeout: 10_000 });

    await context.close();
  });

  test("revoke a token", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "settings-revoke@dimagi.com",
      "Settings Revoke",
    );

    await page.goto("/ace/settings");

    // Create a token labelled "revoke-me".
    await page.getByRole("button", { name: /Create token/i }).click();
    await expect(
      page.getByRole("heading", { name: "Create upload token" }),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByPlaceholder("Token label").fill("revoke-me");
    await page.locator('[role="dialog"]').getByRole("button", { name: "Create" }).click();

    // Dismiss the raw-token dialog.
    await expect(
      page.getByRole("heading", { name: "Token created" }),
    ).toBeVisible({ timeout: 5_000 });
    await page.getByRole("button", { name: "I've saved this" }).click();

    // Wait for the token label to appear in the list.
    await expect(page.getByText("revoke-me")).toBeVisible({ timeout: 10_000 });

    // The token list is a bordered div; inside it each row is a flex container
    // with the label on the left and a Trash2 icon button on the right.
    // Scope to the token list container, find the row that contains "revoke-me",
    // then target the icon button (h-7 w-7 text-destructive).
    const tokenList = page.locator("div.divide-y.divide-border.rounded.border");
    const tokenRow = tokenList.locator("div.flex.items-center.justify-between", {
      hasText: "revoke-me",
    });
    await expect(tokenRow).toBeVisible({ timeout: 5_000 });

    const revokeButton = tokenRow.getByRole("button");
    await expect(revokeButton).toBeVisible({ timeout: 5_000 });
    await revokeButton.click();

    // A sonner toast should confirm the revocation.
    await expect(page.getByText("Token revoked")).toBeVisible({
      timeout: 5_000,
    });

    // The token row should disappear from the list.
    await expect(page.getByText("revoke-me")).not.toBeVisible({
      timeout: 5_000,
    });

    await context.close();
  });
});
