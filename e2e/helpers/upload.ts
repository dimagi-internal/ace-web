import type { Page } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURES_DIR = path.resolve(__dirname, "..", "fixtures");

/**
 * Upload a JSONL fixture file via the sessions page's hidden file input.
 * The page must be on /ace/sessions and authenticated.
 */
export async function uploadJsonlFixture(
  page: Page,
  filename: string = "sample-session.jsonl",
): Promise<void> {
  const filePath = path.join(FIXTURES_DIR, filename);
  const fileInput = page.locator('input[type="file"][accept=".jsonl"]');
  await fileInput.setInputFiles(filePath);
}
