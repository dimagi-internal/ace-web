import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "url";
import path from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");

/**
 * Playwright config for the Phase 3 multi-player E2E suite.
 *
 * The webServer entry boots Django via uvicorn with
 * DJANGO_SETTINGS_MODULE=config.settings.e2e. That module uses a
 * file-backed sqlite and InMemoryChannelLayer, and the
 * config.asgi_e2e wrapper patches redis_client.get_redis to return a
 * fakeredis instance — so no Docker, no Postgres, and no Redis are
 * required. Before startup, the globalSetup hook runs migrations and
 * builds the frontend if the dist directory is missing.
 *
 * The frontend is NOT served by Vite during the test run — we use
 * the production build served by uvicorn + WhiteNoise so the tests
 * exercise the shipping path and do not hit the Vite HMR injection
 * layer (which can mask real bugs). FORCE_SCRIPT_NAME=/ace matches
 * the hardcoded Vite base path and React Router basename.
 *
 * We use uvicorn rather than `manage.py runserver` because
 * runserver does not honour SCRIPT_NAME and produces double-prefixed
 * URLs when FORCE_SCRIPT_NAME is set.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false, // multi-player tests share session state; run serially
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // single worker — tests create shared sessions
  reporter: process.env.CI ? "github" : [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  globalSetup: path.resolve(__dirname, "global-setup.ts"),

  webServer: {
    command:
      "uv run uvicorn config.asgi_e2e:application --host 127.0.0.1 --port 8000",
    cwd: repoRoot,
    url: "http://127.0.0.1:8000/ace/api/health",
    timeout: 60_000,
    reuseExistingServer: !process.env.CI,
    env: {
      DJANGO_SETTINGS_MODULE: "config.settings.e2e",
      DJANGO_SECRET_KEY: "e2e-not-a-secret",
    },
    stdout: "pipe",
    stderr: "pipe",
  },
});
