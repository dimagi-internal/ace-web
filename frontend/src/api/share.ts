import { apiFetch } from "./client";
import type {
  ShareTokenInfo,
  ShareTokenListItem,
  SharedSession,
} from "./types";

export const createShareToken = (slug: string) =>
  apiFetch<ShareTokenInfo>(`/api/sessions/${slug}/share`, { method: "POST" });

export const listShareTokens = (slug: string) =>
  apiFetch<ShareTokenListItem[]>(`/api/sessions/${slug}/share`);

export const revokeShareToken = (slug: string, token: string) =>
  apiFetch<ShareTokenListItem>(`/api/sessions/${slug}/share/${token}`, {
    method: "DELETE",
  });

export const getSharedSession = (token: string) =>
  apiFetch<SharedSession>(`/api/share/${token}`);
