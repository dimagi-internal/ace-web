import type { ApiEnvelope } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(path, { ...init, headers });
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

// Backwards-compatible legacy API: kept so existing consumers (HomePage etc.)
// continue to work. Prefer `apiFetch` for new code.
export const api = {
  health: () => apiFetch<{ status: string }>("/api/health"),
};
