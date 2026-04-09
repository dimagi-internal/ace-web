import type { ApiEnvelope } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// Vite exposes the base path at import.meta.env.BASE_URL.
// It's '/ace/' in prod and '/' in local dev.
const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

function buildUrl(path: string): string {
  // `path` is always something like "/api/sessions" or "/api/auth/cli/start"
  // (starts with a slash). Prefix with BASE_URL so it becomes
  // "/ace/api/sessions" in prod or "/api/sessions" in dev.
  return API_PREFIX + path;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = buildUrl(path);
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(url, { ...init, headers });
  let envelope: ApiEnvelope<T>;
  try {
    envelope = await resp.json();
  } catch {
    throw new ApiError("invalid_response", `${resp.status} ${resp.statusText}`);
  }
  if (envelope.error) {
    throw new ApiError(envelope.error.code, envelope.error.message);
  }
  if (envelope.data === null) {
    throw new ApiError("empty_response", "no data in envelope");
  }
  return envelope.data;
}

// Legacy compatibility for HomePage.tsx
export const api = {
  health: () => apiFetch<{ status: string }>("/api/health"),
};
