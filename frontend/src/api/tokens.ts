import { apiFetch } from "./client";
import type { PersonalToken, PersonalTokenCreated } from "./types";

export const listTokens = () =>
  apiFetch<PersonalToken[]>("/api/auth/tokens");

export const createToken = (label: string) =>
  apiFetch<PersonalTokenCreated>("/api/auth/tokens", {
    method: "POST",
    body: JSON.stringify({ label }),
  });

export const revokeToken = async (id: number): Promise<void> => {
  // DELETE returns 204 with no body — can't use apiFetch which expects JSON
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const resp = await fetch(`${API_PREFIX}/api/auth/tokens/${id}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!resp.ok) {
    throw new Error(`Revoke failed: ${resp.status}`);
  }
};
