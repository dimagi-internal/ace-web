import { apiV2 } from "./client.v2";
import type { ShareTokenInfo, ShareTokenListItem, SharedSession } from "./types.ws";

/**
 * share.ts — share-token API client (v2 only).
 *
 * All endpoints are now served by the v2 Ninja router:
 *   - GET    /api/v2/w/{workspace_slug}/sessions/{slug}/share         — list share tokens
 *   - POST   /api/v2/w/{workspace_slug}/sessions/{slug}/share         — create share token
 *   - DELETE /api/v2/w/{workspace_slug}/sessions/{slug}/share/{token} — revoke share token
 *   - GET    /api/v2/share/{token}                                    — public shared session
 */

export const createShareToken = async (
  slug: string,
  workspaceSlug: string,
): Promise<ShareTokenInfo> => {
  const { response } = await apiV2.POST(
    "/api/v2/w/{workspace_slug}/sessions/{slug}/share" as never,
    { params: { path: { workspace_slug: workspaceSlug, slug } } } as never,
  );
  if (!response.ok) throw new Error(`Failed to create share token: ${response.status}`);
  return (await response.json()) as ShareTokenInfo;
};

export const listShareTokens = async (
  slug: string,
  workspaceSlug: string,
): Promise<ShareTokenListItem[]> => {
  const { response } = await apiV2.GET(
    "/api/v2/w/{workspace_slug}/sessions/{slug}/share",
    { params: { path: { workspace_slug: workspaceSlug, slug } } },
  );
  if (!response.ok) throw new Error(`Failed to list share tokens: ${response.status}`);
  return (await response.json()) as ShareTokenListItem[];
};

export const revokeShareToken = async (
  slug: string,
  token: string,
  workspaceSlug: string,
): Promise<ShareTokenListItem> => {
  const { response } = await apiV2.DELETE(
    "/api/v2/w/{workspace_slug}/sessions/{slug}/share/{token_key}" as never,
    { params: { path: { workspace_slug: workspaceSlug, slug, token_key: token } } } as never,
  );
  if (!response.ok) throw new Error(`Failed to revoke share token: ${response.status}`);
  return (await response.json()) as ShareTokenListItem;
};

export const getSharedSession = async (token: string): Promise<SharedSession> => {
  const { response } = await apiV2.GET("/api/v2/share/{token}" as never, {
    params: { path: { token } },
  } as never);
  if (!response.ok) throw new Error(`Failed to load shared session: ${response.status}`);
  return (await response.json()) as SharedSession;
};
