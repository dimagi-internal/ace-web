import type { Page } from "@playwright/test";

import { postJson } from "./auth";

type Envelope<T> = { data: T | null; error: { code: string; message: string } | null };

interface SessionData {
  slug: string;
  title: string;
  status: string;
}

export interface MessageRow {
  id: number;
  turn_index: number;
  role: "user" | "assistant" | "tool_use" | "tool_result";
  plaintext: string;
  status: "pending" | "streaming" | "complete" | "error";
  error_detail?: string | null;
}

/**
 * Create a new session via the REST API. Returns the slug.
 * Requires the page to be authenticated.
 */
export async function createSession(page: Page, title: string): Promise<string> {
  const envelope = await postJson<Envelope<SessionData>>(
    page,
    "/ace/api/sessions",
    { title },
  );
  if (envelope.error) {
    throw new Error(
      `createSession envelope error: ${JSON.stringify(envelope.error)}`,
    );
  }
  if (!envelope.data) {
    throw new Error("createSession returned no data");
  }
  return envelope.data.slug;
}

/**
 * Add a participant to a session by email. Requires the page to be
 * authenticated as the session owner. The target user must already
 * have logged in at least once (the backend looks them up by email
 * and 404s if they don't exist).
 */
export async function addParticipant(
  page: Page,
  slug: string,
  email: string,
): Promise<void> {
  await postJson<Envelope<unknown>>(
    page,
    `/ace/api/sessions/${slug}/participants`,
    { email },
  );
}

/**
 * Fetch the ordered list of persisted messages for a session via
 * the read-only REST endpoint. Used by the E2E tests to assert on
 * server-side state when the current frontend hook does not
 * reliably mirror streamed messages into React state (see the NOTE
 * in ``tests/multiplayer.spec.ts``).
 */
export async function listMessages(
  page: Page,
  slug: string,
): Promise<MessageRow[]> {
  const response = await page.request.get(`/ace/api/sessions/${slug}/messages`);
  if (!response.ok()) {
    throw new Error(
      `listMessages failed: ${response.status()} ${await response.text()}`,
    );
  }
  const envelope = (await response.json()) as Envelope<MessageRow[]>;
  if (envelope.error) {
    throw new Error(
      `listMessages envelope error: ${JSON.stringify(envelope.error)}`,
    );
  }
  return envelope.data ?? [];
}
