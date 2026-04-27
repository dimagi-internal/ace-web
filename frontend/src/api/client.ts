import { type ApiEnvelope } from "./types";

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

/**
 * Read the CSRF token from the browser's cookies. Django's CsrfViewMiddleware
 * (and DRF's SessionAuthentication) require unsafe-method requests to carry
 * this as the X-CSRFToken header.
 *
 * ace-web's prod deployment uses a tenant-specific cookie name
 * (`csrftoken_ace`, set in connectlabs.py) to avoid colliding with other
 * tenants on labs.connect.dimagi.com. Local dev uses the Django default
 * (`csrftoken`). Check the tenant-specific name first, fall back to the
 * default, return empty string if neither is present (an empty header is
 * harmless for safe methods).
 */
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

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Extract the active workspace slug from the URL path. The router
 * mounts workspace-scoped routes under `/w/:workspaceSlug/...`; this
 * helper parses the location pathname and returns the slug if present.
 *
 * apiFetch injects this as the `X-ACE-Workspace` header so backend
 * read endpoints know which workspace to scope to without every API
 * call needing an explicit slug argument.
 */
function getActiveWorkspaceSlug(): string | null {
  if (typeof window === "undefined") return null;
  // Path looks like /ace/w/<slug>/... in prod, /w/<slug>/... in dev.
  // Strip the basename if present, then check for /w/<slug>/.
  let path = window.location.pathname;
  if (path.startsWith(API_PREFIX) && API_PREFIX) {
    path = path.slice(API_PREFIX.length);
  }
  const match = path.match(/^\/w\/([^/]+)/);
  return match ? match[1] : null;
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
  const method = (init.method ?? "GET").toUpperCase();
  if (UNSAFE_METHODS.has(method) && !headers.has("X-CSRFToken")) {
    const token = getCsrfToken();
    if (token) {
      headers.set("X-CSRFToken", token);
    }
  }
  if (!headers.has("X-ACE-Workspace")) {
    const slug = getActiveWorkspaceSlug();
    if (slug) headers.set("X-ACE-Workspace", slug);
  }
  const resp = await fetch(url, { ...init, headers });

  // Expired/invalid session → redirect to login instead of showing
  // a cryptic error. The SPA catch-all has login_required, but API
  // calls bypass that and return 401/403 with a DRF detail message.
  if (resp.status === 401 || resp.status === 403) {
    const body = await resp.json().catch(() => ({})) as { detail?: string };
    const isAuthError =
      body.detail?.includes("credentials were not provided") ||
      body.detail?.includes("CSRF") ||
      body.detail?.includes("not authenticated");
    if (isAuthError) {
      const loginUrl = `${API_PREFIX}/auth/login/?next=${encodeURIComponent(window.location.pathname)}`;
      window.location.href = loginUrl;
      // Never resolves — the redirect takes us away
      return new Promise<T>(() => {});
    }
  }

  // 204 No Content — success with empty body. Callers that expect no data
  // (e.g. DELETE endpoints) type T as void/undefined.
  if (resp.status === 204) {
    return undefined as T;
  }

  let envelope: ApiEnvelope<T>;
  try {
    envelope = await resp.json();
  } catch {
    throw new ApiError("invalid_response", `${resp.status} ${resp.statusText}`);
  }
  // Handle non-envelope responses (e.g. DRF permission errors)
  if (!resp.ok && (!envelope || typeof envelope !== "object")) {
    throw new ApiError(
      `http_${resp.status}`,
      `${resp.status} ${resp.statusText}`,
    );
  }
  if (envelope && envelope.error) {
    throw new ApiError(envelope.error.code, envelope.error.message);
  }
  if (!envelope || !("data" in envelope)) {
    const detail =
      (envelope as unknown as { detail?: string })?.detail ??
      `${resp.status} ${resp.statusText}`;
    throw new ApiError(`http_${resp.status}`, detail);
  }
  if (envelope.data === null || envelope.data === undefined) {
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
 * Thin wrapper around apiFetch that prefixes the path with /api so
 * opps.ts call sites can use "/opps/..." instead of "/api/opps/...".
 */
export function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return apiFetch<T>(`/api${path}`, init);
}
