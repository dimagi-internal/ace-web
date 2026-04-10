import { execSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");

/**
 * Global setup runs once before all tests.
 * - Wipes the e2e sqlite file so we start fresh.
 * - Runs Django migrations against the e2e sqlite file.
 * - Builds the frontend if the dist directory is missing. The E2E
 *   settings serve the built dist via WhiteNoise + STATICFILES_DIRS
 *   under /ace/assets/, so a missing build would result in 404s on
 *   every asset.
 */
export default async function globalSetup() {
  const dbPath = path.join(repoRoot, "e2e-test.sqlite3");
  if (fs.existsSync(dbPath)) {
    fs.unlinkSync(dbPath);
  }

  const env = {
    ...process.env,
    DJANGO_SETTINGS_MODULE: "config.settings.e2e",
    DJANGO_SECRET_KEY: "e2e-not-a-secret",
  };

  console.log("[e2e] Running migrations...");
  execSync("uv run python manage.py migrate --noinput", {
    cwd: repoRoot,
    env,
    stdio: "inherit",
  });

  const distIndex = path.join(repoRoot, "frontend", "dist", "index.html");
  if (!fs.existsSync(distIndex)) {
    console.log("[e2e] Frontend build missing — running bun run build...");
    execSync("bun run build", {
      cwd: path.join(repoRoot, "frontend"),
      stdio: "inherit",
    });
  }
}
