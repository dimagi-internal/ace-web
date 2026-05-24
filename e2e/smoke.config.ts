import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "url";
import path from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Smoke-test config — runs against a LIVE deployment (labs by default).
 *
 * Distinct from the default playwright.config.ts which boots a local
 * uvicorn + sqlite for hermetic Phase 3 multi-player tests. This
 * config:
 *   - does NOT start a webServer
 *   - points at ACE_SMOKE_BASE_URL (default: https://labs.connect.dimagi.com)
 *   - authenticates via Bearer PAT (ACE_WEB_PAT_TOKEN) traded for a
 *     session cookie at /ace/api/auth/pat-to-session. Mint the PAT
 *     via /ace:ace-web-pat-mint.
 *
 * Run with:
 *   ACE_WEB_PAT_TOKEN=<pat> bun run smoke
 * Or via npm:
 *   ACE_WEB_PAT_TOKEN=<pat> npx playwright test -c smoke.config.ts
 */
const baseURL =
  process.env.ACE_SMOKE_BASE_URL || "https://labs.connect.dimagi.com";

export default defineConfig({
  testDir: path.resolve(__dirname, "smoke"),
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "github" : [["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
