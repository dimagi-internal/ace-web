import { apiV2 } from "./client.v2";
import { apiFetch } from "./client";
import type { Message } from "./types.ws";

/**
 * messages.ts — message list API client.
 *
 * v2 endpoint: GET /api/w/{workspace_slug}/sessions/{slug}/messages
 * The response body is paginated but content?: never in the schema.
 * Returns the items array directly (matching legacy behaviour).
 *
 * Falls back to the legacy path when `workspaceSlug` is not provided.
 */
export const listMessages = async (
  slug: string,
  workspaceSlug?: string,
): Promise<Message[]> => {
  if (workspaceSlug) {
    const { response } = await apiV2.GET(
      "/api/w/{workspace_slug}/sessions/{slug}/messages",
      { params: { path: { workspace_slug: workspaceSlug, slug } } },
    );
    if (!response.ok) throw new Error(`Failed to list messages: ${response.status}`);
    // v2 returns a Page shape: { items, total, offset, limit }
    const page = (await response.json()) as { items: Message[] };
    return page.items;
  }
  // Legacy fallback — used by callers that don't pass workspaceSlug yet.
  return apiFetch<Message[]>(`/api/sessions/${slug}/messages`);
};
