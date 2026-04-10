import { apiFetch } from "./client";
import type { Session, SessionDetail, SessionListPage } from "./types";

export interface ListSessionsParams {
  q?: string;
  status?: string;
  source?: string;
  page?: number;
  pageSize?: number;
}

export const listSessions = (params: ListSessionsParams = {}) => {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.status) qs.set("status", params.status);
  if (params.source) qs.set("source", params.source);
  if (params.page) qs.set("page", String(params.page));
  if (params.pageSize) qs.set("page_size", String(params.pageSize));
  return apiFetch<SessionListPage>(`/api/sessions?${qs}`);
};

export const createSession = () =>
  apiFetch<Session>("/api/sessions", { method: "POST", body: "{}" });

export const getSession = (slug: string) =>
  apiFetch<SessionDetail>(`/api/sessions/${slug}`);

export const updateSession = (slug: string, updates: Partial<Session>) =>
  apiFetch<Session>(`/api/sessions/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });

export const deleteSession = async (slug: string): Promise<void> => {
  // DELETE returns 204 with no body — can't use apiFetch which expects JSON
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const resp = await fetch(`${API_PREFIX}/api/sessions/${slug}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!resp.ok) {
    throw new Error(`Delete failed: ${resp.status}`);
  }
};
