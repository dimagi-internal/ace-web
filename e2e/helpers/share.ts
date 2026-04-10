import type { Page } from "@playwright/test";

import { getCsrfToken } from "./auth";

type Envelope<T> = {
  data: T | null;
  error: { code: string; message: string } | null;
};

interface ShareTokenData {
  token: string;
  url: string;
  created_at: string;
}

/**
 * Create a share token for a session via the REST API.
 * Requires the page to be authenticated as a session owner or editor.
 */
export async function createShareToken(
  page: Page,
  slug: string,
): Promise<ShareTokenData> {
  const csrf = await getCsrfToken(page.context());
  const resp = await page.request.post(`/ace/api/sessions/${slug}/share`, {
    headers: { "X-CSRFToken": csrf },
  });
  if (!resp.ok()) {
    throw new Error(
      `createShareToken failed: ${resp.status()} ${await resp.text()}`,
    );
  }
  const envelope = (await resp.json()) as Envelope<ShareTokenData>;
  if (envelope.error) {
    throw new Error(
      `createShareToken error: ${JSON.stringify(envelope.error)}`,
    );
  }
  return envelope.data!;
}

/**
 * Revoke a share token via the REST API.
 */
export async function revokeShareToken(
  page: Page,
  slug: string,
  token: string,
): Promise<void> {
  const csrf = await getCsrfToken(page.context());
  const resp = await page.request.delete(
    `/ace/api/sessions/${slug}/share/${token}`,
    { headers: { "X-CSRFToken": csrf } },
  );
  if (!resp.ok()) {
    throw new Error(
      `revokeShareToken failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}
