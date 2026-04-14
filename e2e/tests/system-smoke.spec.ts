import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";

/**
 * Smoke test for the System Overview tab.
 *
 * Verifies the page loads, the Pipeline view shows skills, clicking a skill
 * loads the detail pane with markdown content, and switching to the Agents
 * view shows agent cards.
 */
test.describe("System Overview tab", () => {
  test("pipeline view loads with skills", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "system-smoke@dimagi.com",
      "System Smoke",
    );

    await page.goto("/ace/system");

    // Wait for the page to load
    await expect(page.getByText("System Blueprint")).toBeVisible({
      timeout: 15_000,
    });

    // Stats bar should show skill counts
    await expect(page.getByText(/skills/).first()).toBeVisible();
    await expect(page.getByText(/agents/).first()).toBeVisible();

    // The Idea to IDD skill should be visible in the Pipeline view
    await expect(page.getByText("Idea to IDD")).toBeVisible({
      timeout: 10_000,
    });

    // Screenshot for visual reference
    await page.screenshot({
      path: "test-results/system-pipeline.png",
      fullPage: true,
    });

    await context.close();
  });

  test("clicking a skill loads the detail pane", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "system-skill@dimagi.com",
      "System Skill",
    );

    await page.goto("/ace/system");
    await expect(page.getByText("System Blueprint")).toBeVisible({
      timeout: 15_000,
    });

    // Click the Idea to IDD skill row
    await page.getByText("Idea to IDD").first().click();

    // Detail pane should show metadata and rendered markdown
    await expect(page.getByText("Metadata").first()).toBeVisible({
      timeout: 5_000,
    });

    // The SKILL.md section should have the Process heading
    await expect(page.getByText("## Process").or(page.getByRole("heading", { name: "Process" }))).toBeVisible({
      timeout: 5_000,
    });

    await page.screenshot({
      path: "test-results/system-skill-detail.png",
      fullPage: true,
    });

    await context.close();
  });

  test("agents view shows agent cards", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "system-agents@dimagi.com",
      "System Agents",
    );

    await page.goto("/ace/system");
    await expect(page.getByText("System Blueprint")).toBeVisible({
      timeout: 15_000,
    });

    // Switch to Agents view
    await page.getByRole("button", { name: "agents", exact: false }).click();

    // app-builder agent should be visible (matches multiple elements:
    // sidebar entry + card header — .first() picks whichever renders first)
    await expect(page.getByText("app-builder").first()).toBeVisible({
      timeout: 5_000,
    });

    await page.screenshot({
      path: "test-results/system-agents.png",
      fullPage: true,
    });

    await context.close();
  });
});
