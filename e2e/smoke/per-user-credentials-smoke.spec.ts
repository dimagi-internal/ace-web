import { test, expect } from "@playwright/test";

import { newSmokeContext } from "./auth";

/**
 * Post-deploy smoke test for per-user CLI credentials (PR #117).
 *
 * Runs against a LIVE deployment as ace@dimagi-ai.com via
 * /ace/auth/e2e-login/. Read-only — deliberately does NOT upload
 * credentials or mutate server state so the real ACE subscription
 * blob isn't burned or perturbed.
 *
 * Assertions:
 *   1. /api/health is 200.
 *   2. Authenticating as ace@dimagi-ai.com works via e2e-login.
 *   3. /api/auth/cli/status returns the two-panel shape
 *      ({authenticated, user: {has_blob, token_prefix}, global: {has_blob}}).
 *   4. /settings renders the "Claude CLI credentials" section with
 *      both the "Your token" and "Instance fallback" panels visible.
 *
 * Verifies the feature flag flip cleanly survived the deploy without
 * touching any credential blob.
 */
test.describe("per-user CLI credentials — smoke", () => {
  test("health endpoint is alive", async ({ request }) => {
    const resp = await request.get("/ace/api/health");
    expect(resp.status()).toBe(200);
  });

  test("e2e-login as ace@dimagi-ai.com works", async ({ browser }) => {
    const { context, user } = await newSmokeContext(browser);
    try {
      expect(user.email).toBe("ace@dimagi-ai.com");
      expect(typeof user.userId).toBe("number");
    } finally {
      await context.close();
    }
  });

  test("/api/auth/cli/status returns two-panel shape", async ({ browser }) => {
    const { context, page } = await newSmokeContext(browser);
    try {
      const resp = await page.request.get("/ace/api/auth/cli/status");
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();

      // Envelope shape: {data, error}
      expect(body.error).toBeNull();
      expect(body.data).toBeDefined();

      const data = body.data;
      expect(typeof data.authenticated).toBe("boolean");

      // Per-user panel
      expect(data.user).toBeDefined();
      expect(typeof data.user.has_blob).toBe("boolean");
      // token_prefix is either a string (if uploaded) or null
      expect(
        data.user.token_prefix === null ||
          typeof data.user.token_prefix === "string",
      ).toBeTruthy();

      // Global panel
      expect(data.global).toBeDefined();
      expect(typeof data.global.has_blob).toBe("boolean");

      // After deploy, the instance fallback should be configured (global blob
      // migrated from pre-per-user state).
      expect(data.global.has_blob).toBe(true);
    } finally {
      await context.close();
    }
  });

  test("/settings renders the Claude CLI credentials section", async ({
    browser,
  }) => {
    const { context, page } = await newSmokeContext(browser);
    try {
      await page.goto("/ace/settings");

      await expect(
        page.getByRole("heading", { name: "Settings" }),
      ).toBeVisible();

      // The new per-user section heading
      await expect(
        page.getByRole("heading", { name: "Claude CLI credentials" }),
      ).toBeVisible();

      // Both panels render, identified by their label text
      await expect(page.getByText("Your token", { exact: true })).toBeVisible();
      await expect(
        page.getByText("Instance fallback", { exact: true }),
      ).toBeVisible();
    } finally {
      await context.close();
    }
  });
});
