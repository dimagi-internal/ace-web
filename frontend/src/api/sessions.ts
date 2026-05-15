import { apiV2 } from "./client.v2";
import type { Session, SessionDetail, SessionListPage } from "./types.ws";

/**
 * sessions.ts — sessions resource API client (v2).
 *
 * v2 endpoints (workspace-scoped):
 *   GET    /api/w/{workspace_slug}/sessions         — list
 *   POST   /api/w/{workspace_slug}/sessions         — create
 *   GET    /api/w/{workspace_slug}/sessions/{slug}  — detail
 *   PATCH  /api/w/{workspace_slug}/sessions/{slug}  — update
 *   DELETE /api/w/{workspace_slug}/sessions/{slug}  — delete
 *
 * All v2 responses have content?: never so we use response.json() casts.
 */

export interface ListSessionsParams {
  q?: string;
  status?: string;
  source?: string;
  opp?: string;
  page?: number;
  pageSize?: number;
  /** Required for the v2 path. */
  workspaceSlug?: string;
}

export const listSessions = async (params: ListSessionsParams = {}): Promise<SessionListPage> => {
  const workspaceSlug = params.workspaceSlug;
  if (!workspaceSlug) throw new Error("listSessions: workspaceSlug is required");

  const query: Record<string, string | number | boolean> = {};
  // v2 uses offset/limit, not page
  if (params.page) query.offset = ((params.page - 1) * (params.pageSize ?? 20));
  if (params.pageSize) query.limit = params.pageSize;
  if (params.opp) query.opp_slug = params.opp;
  if (params.status === "archived") query.archived = true;

  const { response } = await apiV2.GET(
    "/api/w/{workspace_slug}/sessions",
    {
      params: {
        path: { workspace_slug: workspaceSlug },
        query: query as Record<string, number>,
      },
    },
  );
  if (!response.ok) throw new Error(`Failed to list sessions: ${response.status}`);
  const page = (await response.clone().json()) as SessionListPage;
  return page;
};

export const createSession = async (workspaceSlug: string): Promise<Session> => {
  const { response } = await apiV2.POST(
    "/api/w/{workspace_slug}/sessions",
    {
      params: { path: { workspace_slug: workspaceSlug } },
      body: { title: "" },
    },
  );
  if (!response.ok) throw new Error(`Failed to create session: ${response.status}`);
  return (await response.clone().json()) as Session;
};

export const getSession = async (slug: string, workspaceSlug: string): Promise<SessionDetail> => {
  const { response } = await apiV2.GET(
    "/api/w/{workspace_slug}/sessions/{slug}",
    { params: { path: { workspace_slug: workspaceSlug, slug } } },
  );
  if (!response.ok) throw new Error(`Failed to get session: ${response.status}`);
  return (await response.clone().json()) as SessionDetail;
};

export const updateSession = async (
  slug: string,
  updates: Partial<Session>,
  workspaceSlug: string,
): Promise<Session> => {
  const { response } = await apiV2.PATCH(
    "/api/w/{workspace_slug}/sessions/{slug}",
    {
      params: { path: { workspace_slug: workspaceSlug, slug } },
      body: updates as { title?: string | null; status?: ("active" | "archived" | "imported") | null },
    },
  );
  if (!response.ok) throw new Error(`Failed to update session: ${response.status}`);
  return (await response.clone().json()) as Session;
};

export const deleteSession = async (slug: string, workspaceSlug: string): Promise<void> => {
  const { response } = await apiV2.DELETE(
    "/api/w/{workspace_slug}/sessions/{slug}",
    { params: { path: { workspace_slug: workspaceSlug, slug } } },
  );
  if (!response.ok && response.status !== 204) {
    throw new Error(`Delete failed: ${response.status}`);
  }
};
