import { apiFetch } from "./client";
import type { PersonalToken, PersonalTokenCreated } from "./types";

export const listTokens = () =>
  apiFetch<PersonalToken[]>("/api/auth/tokens");

export const createToken = (label: string) =>
  apiFetch<PersonalTokenCreated>("/api/auth/tokens", {
    method: "POST",
    body: JSON.stringify({ label }),
  });

function getCsrfToken(): string {
  const cookies = document.cookie.split(";");
  for (const raw of cookies) {
    const [rawName, ...rawValue] = raw.trim().split("=");
    if (rawName === "csrftoken_ace" || rawName === "csrftoken") {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return "";
}

export const revokeToken = async (id: number): Promise<void> => {
  // DELETE returns 204 with no body — can't use apiFetch which expects JSON.
  // Must include X-CSRFToken since DRF's SessionAuthentication enforces CSRF
  // for all unsafe methods.
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const resp = await fetch(`${API_PREFIX}/api/auth/tokens/${id}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRFToken": getCsrfToken() },
  });
  if (!resp.ok) {
    throw new Error(`Revoke failed: ${resp.status}`);
  }
};
