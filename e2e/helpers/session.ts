import type { Page } from "@playwright/test";

import { postJson } from "./auth";

type Envelope<T> = { data: T | null; error: { code: string; message: string } | null };

interface SessionData {
  slug: string;
  title: string;
  status: string;
}

/**
 * Create a new session via the REST API. Returns the slug.
 * Requires the page to be authenticated.
 *
 * Still used by sessions.spec.ts (the /ace/sessions CRUD surface, which
 * remains live — it's how uploaded/imported and programmatically-created
 * ACE-run sessions are browsed, read-only, now that interactive chat is
 * canopy-hosted). `addParticipant`/`listMessages`, which used to live
 * here, were removed with their only callers (multiplayer.spec.ts,
 * chat-lifecycle.spec.ts) — see the PR that retired ace-web's own
 * interactive chat UI in favor of canopy-hosted chat.
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
