import { apiV2 } from "./client.v2";
import type { Message } from "./types.ws";

/**
 * messages.ts — message list API client (v2).
 *
 * v2 endpoint: GET /api/w/{workspace_slug}/sessions/{slug}/messages
 * The response body is paginated but content?: never in the schema.
 * Returns the items array directly (matching legacy behaviour).
 */
export const listMessages = async (
  slug: string,
  workspaceSlug: string,
): Promise<Message[]> => {
  const { data, response } = await apiV2.GET(
    "/api/w/{workspace_slug}/sessions/{slug}/messages",
    { params: { path: { workspace_slug: workspaceSlug, slug } } },
  );
  if (!response.ok) throw new Error(`Failed to list messages: ${response.status}`);
  // v2 returns a Page shape: { items, total, offset, limit }
  const page = data as unknown as { items: Message[] };
  return page.items;
};
