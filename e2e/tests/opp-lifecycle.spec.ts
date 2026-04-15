import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";

test.describe("Opp lifecycle", () => {
  test("create opp via wizard, land on workbench with seeded chat", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "opp-lifecycle@dimagi.com",
      "Lifecycle Test",
    );

    // Need a Drive folder + service account configured for opp creation.
    // The e2e environment may or may not have this — skip cleanly if not.
    // Detect by hitting the opp list and checking for a 200 response.
    const listResp = await page.request.get("/ace/api/opps/");
    if (listResp.status() !== 200) {
      test.skip(true, "ACE Drive not configured in e2e environment");
    }

    // 1. Navigate to the opp list
    await page.goto("/ace/opps");

    // 2. Open the wizard
    await page.getByRole("button", { name: /New Opp/ }).click();

    // 3. Fill form
    const uniqueSlug = `e2e-lifecycle-${Date.now()}`;
    await page.getByPlaceholder("malaria-pilot-2026").fill(uniqueSlug);
    await page.getByPlaceholder("Malaria Pilot 2026").fill("E2E Lifecycle");
    await page.getByPlaceholder(/Describe the intervention/).fill("E2E test idea body.");

    // 4. Submit
    await page.getByRole("button", { name: "Create opp" }).click();

    // 5. Verify the workbench loaded
    await expect(page).toHaveURL(new RegExp(`/ace/opps/${uniqueSlug}`));

    // 6. Verify the seeded user message appears in the chat panel.
    // The seeded user message contains "/ace:step idea-to-pdd for <slug>".
    await expect(
      page.locator(`text=/idea-to-pdd.*${uniqueSlug}/i`).first(),
    ).toBeVisible({ timeout: 15_000 });

    await context.close();
  });
});
