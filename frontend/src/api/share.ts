import { apiV2 } from "./client.v2";
import { apiFetch } from "./client";
import type { ShareTokenInfo, ShareTokenListItem, SharedSession } from "./types.ws";

/**
 * share.ts — share-token API client.
 *
 * v2 coverage:
 *   - GET  /api/v2/w/{workspace_slug}/sessions/{slug}/share — list share tokens
 *
 * Legacy DRF coverage (not yet in v2 schema):
 *   - POST   /api/sessions/{slug}/share         — create share token
 *   - DELETE /api/sessions/{slug}/share/{token} — revoke share token
 *   - GET    /api/share/{token}                 — public shared session view
 */

export const createShareToken = (slug: string): Promise<ShareTokenInfo> =>
  apiFetch<ShareTokenInfo>(`/api/sessions/${slug}/share`, { method: "POST" });

export const listShareTokens = async (
  slug: string,
  workspaceSlug?: string,
): Promise<ShareTokenListItem[]> => {
  // Use v2 when workspace slug is available (workspace-scoped path).
  if (workspaceSlug) {
    const { response } = await apiV2.GET(
      "/api/v2/w/{workspace_slug}/sessions/{slug}/share",
      { params: { path: { workspace_slug: workspaceSlug, slug } } },
    );
    if (!response.ok) throw new Error(`Failed to list share tokens: ${response.status}`);
    return (await response.json()) as ShareTokenListItem[];
  }
  // Fallback to legacy path (e.g. from share popover without workspace context).
  return apiFetch<ShareTokenListItem[]>(`/api/sessions/${slug}/share`);
};

export const revokeShareToken = (slug: string, token: string): Promise<ShareTokenListItem> =>
  apiFetch<ShareTokenListItem>(`/api/sessions/${slug}/share/${token}`, {
    method: "DELETE",
  });

export const getSharedSession = (token: string): Promise<SharedSession> =>
  apiFetch<SharedSession>(`/api/share/${token}`);
