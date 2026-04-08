import { apiFetch } from "./client";
import type { Session, SessionDetail } from "./types";

export const listSessions = (limit = 20, status?: string) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  return apiFetch<Session[]>(`/api/sessions?${params}`);
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
