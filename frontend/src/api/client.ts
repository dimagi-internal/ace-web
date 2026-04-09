import { DriveReconnectRequired, type ApiEnvelope } from "./types";

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

/**
 * Lower-level fetch helper used by the opps API client.
 * Identical to apiFetch but surfaces drive-token-missing 401 responses as
 * DriveReconnectRequired so the DriveReconnectGuard error boundary can catch
 * them and redirect the user to re-authorise Google Drive access.
 */
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = buildUrl(`/api${path}`);
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
  if (resp.status === 401 && envelope.error?.code === "drive-token-missing") {
    const data = envelope.data as { reconnect_url: string } | null;
    const reconnectUrl = data?.reconnect_url ?? "/auth/drive/start";
    throw new DriveReconnectRequired(reconnectUrl);
  }
  if (envelope.error) {
    throw new ApiError(envelope.error.code, envelope.error.message);
  }
  if (envelope.data === null) {
    throw new ApiError("empty_response", "no data in envelope");
  }
  return envelope.data;
}
