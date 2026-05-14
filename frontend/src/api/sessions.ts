import { apiV2 } from "./client.v2";
import { apiFetch } from "./client";
import type { Session, SessionDetail, SessionListPage } from "./types.ws";

/**
 * sessions.ts — sessions resource API client.
 *
 * v2 endpoints (workspace-scoped):
 *   GET    /api/w/{workspace_slug}/sessions         — list
 *   POST   /api/w/{workspace_slug}/sessions         — create
 *   GET    /api/w/{workspace_slug}/sessions/{slug}  — detail
 *   PATCH  /api/w/{workspace_slug}/sessions/{slug}  — update
 *   DELETE /api/w/{workspace_slug}/sessions/{slug}  — delete
 *
 * All v2 responses have content?: never so we use response.json() casts.
 * Falls back to legacy DRF endpoints when workspaceSlug is not provided.
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
  if (params.workspaceSlug) {
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
          path: { workspace_slug: params.workspaceSlug },
          query: query as Record<string, number>,
        },
      },
    );
    if (!response.ok) throw new Error(`Failed to list sessions: ${response.status}`);
    const page = (await response.json()) as SessionListPage;
    return page;
  }

  // Legacy fallback
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.status) qs.set("status", params.status);
  if (params.source) qs.set("source", params.source);
  if (params.opp) qs.set("opp", params.opp);
  if (params.page) qs.set("page", String(params.page));
  if (params.pageSize) qs.set("page_size", String(params.pageSize));
  return apiFetch<SessionListPage>(`/api/sessions?${qs}`);
};

export const createSession = async (workspaceSlug?: string): Promise<Session> => {
  if (workspaceSlug) {
    const { response } = await apiV2.POST(
      "/api/w/{workspace_slug}/sessions",
      {
        params: { path: { workspace_slug: workspaceSlug } },
        body: { title: "" },
      },
    );
    if (!response.ok) throw new Error(`Failed to create session: ${response.status}`);
    return (await response.json()) as Session;
  }
  return apiFetch<Session>("/api/sessions", { method: "POST", body: "{}" });
};

export const getSession = async (slug: string, workspaceSlug?: string): Promise<SessionDetail> => {
  if (workspaceSlug) {
    const { response } = await apiV2.GET(
      "/api/w/{workspace_slug}/sessions/{slug}",
      { params: { path: { workspace_slug: workspaceSlug, slug } } },
    );
    if (!response.ok) throw new Error(`Failed to get session: ${response.status}`);
    return (await response.json()) as SessionDetail;
  }
  return apiFetch<SessionDetail>(`/api/sessions/${slug}`);
};

export const updateSession = async (
  slug: string,
  updates: Partial<Session>,
  workspaceSlug?: string,
): Promise<Session> => {
  if (workspaceSlug) {
    const { response } = await apiV2.PATCH(
      "/api/w/{workspace_slug}/sessions/{slug}",
      {
        params: { path: { workspace_slug: workspaceSlug, slug } },
        body: updates as { title?: string | null; status?: ("active" | "archived" | "imported") | null },
      },
    );
    if (!response.ok) throw new Error(`Failed to update session: ${response.status}`);
    return (await response.json()) as Session;
  }
  return apiFetch<Session>(`/api/sessions/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
};

export const deleteSession = async (slug: string, workspaceSlug?: string): Promise<void> => {
  if (workspaceSlug) {
    const { response } = await apiV2.DELETE(
      "/api/w/{workspace_slug}/sessions/{slug}",
      { params: { path: { workspace_slug: workspaceSlug, slug } } },
    );
    if (!response.ok && response.status !== 204) {
      throw new Error(`Delete failed: ${response.status}`);
    }
    return;
  }

  // Legacy fallback — inline CSRF handling for non-v2 path
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const cookies = document.cookie.split(";");
  let csrfToken = "";
  for (const raw of cookies) {
    const [name, ...value] = raw.trim().split("=");
    if (name === "csrftoken_ace" || name === "csrftoken") {
      csrfToken = decodeURIComponent(value.join("="));
      break;
    }
  }
  const resp = await fetch(`${API_PREFIX}/api/sessions/${slug}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: csrfToken ? { "X-CSRFToken": csrfToken } : undefined,
  });
  if (!resp.ok) {
    throw new Error(`Delete failed: ${resp.status}`);
  }
};
