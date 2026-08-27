import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { uploadJsonlFixture } from "../helpers/upload";

/**
 * Upload-flow E2E tests.
 *
 * Exercises the JSONL ingest path from the sessions page:
 *   1. Uploading a JSONL file shows a toast with the message count and the
 *      session appears in the sessions list with an "upload" source badge.
 *
 * Each test uses a distinct email address so user state never leaks between
 * tests (users persist for the lifetime of the SQLite e2e DB, which is reset
 * between runs by global-setup.ts).
 *
 * Retired (see the chat-retirement PR): "imported session renders messages"
 * and "imported session send box is disabled" both drove into the
 * interactive `/chat/:slug` page (deleted `ChatPanel`/`MessageList`) and the
 * latter asserted on the deleted `SendBox.tsx`'s "Imported session" banner —
 * neither survives. An uploaded session's row now links to
 * `/chat/:slug/structure` (`SessionStructurePage` → `StructureTab`), a
 * DIFFERENT view (a phase/skill/tool breakdown tree computed by
 * `apps/ingest/structure_aggregator.py`, not a chat transcript) — it doesn't
 * render the fixture's raw message plaintext, so the old assertions don't
 * have a like-for-like replacement here. That surviving read path (GET
 * .../structure) is covered at the backend/unit level by
 * `apps/sessions/tests/test_api.py::test_structure_*`, which this PR left
 * unmodified; there is currently no browser-level E2E coverage of
 * `SessionStructurePage` rendering real structure-tree content for an
 * uploaded transcript. Flagged as a real (if narrow) coverage gap.
 */
test.describe("Upload flow", () => {
  test("upload JSONL file from sessions page", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser,
      "upload-badge@dimagi.com",
      "Upload Badge",
    );

    await page.goto("/ace/sessions");

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
});
