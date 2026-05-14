import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./generated";

const baseUrl = import.meta.env.BASE_URL || "/";

// ---------------------------------------------------------------------------
// Helpers shared with legacy client.ts
// ---------------------------------------------------------------------------

function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const cookies = document.cookie.split(";");
  for (const raw of cookies) {
    const [rawName, ...rawValue] = raw.trim().split("=");
    if (rawName === "csrftoken_ace" || rawName === "csrftoken") {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return "";
}

function getActiveWorkspaceSlug(): string | null {
  if (typeof window === "undefined") return null;
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  let path = window.location.pathname;
  if (path.startsWith(API_PREFIX) && API_PREFIX) {
    path = path.slice(API_PREFIX.length);
  }
  const match = path.match(/^\/w\/([^/]+)/);
  return match ? match[1] : null;
}

// ---------------------------------------------------------------------------
// Middleware: CSRF token + workspace header
// ---------------------------------------------------------------------------

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const headersMiddleware: Middleware = {
  async onRequest({ request }) {
    const method = request.method.toUpperCase();
    if (UNSAFE_METHODS.has(method)) {
      const token = getCsrfToken();
      if (token) request.headers.set("X-CSRFToken", token);
    }
    if (!request.headers.has("X-ACE-Workspace")) {
      const slug = getActiveWorkspaceSlug();
      if (slug) request.headers.set("X-ACE-Workspace", slug);
    }
    return request;
  },
};

// ---------------------------------------------------------------------------
// Auth-error redirect middleware
// ---------------------------------------------------------------------------

const authRedirectMiddleware: Middleware = {
  async onResponse({ response }) {
    if (response.status === 401 || response.status === 403) {
      try {
        const body = (await response.clone().json()) as { detail?: string };
        const isAuthError =
          body.detail?.includes("credentials were not provided") ||
          body.detail?.includes("CSRF") ||
          body.detail?.includes("not authenticated") ||
          body.detail?.includes("Authentication required");
        if (isAuthError) {
          const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
          const loginUrl = `${API_PREFIX}/auth/login/?next=${encodeURIComponent(window.location.pathname)}`;
          window.location.href = loginUrl;
          // Return a never-resolving clone so downstream code never runs
          return new Response(null, { status: 401 });
        }
      } catch {
        // ignore JSON parse errors
      }
    }
    return response;
  },
};

export const apiV2 = createClient<paths>({
  baseUrl: `${baseUrl.replace(/\/$/, "")}/api/v2`,
  credentials: "include",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});

apiV2.use(headersMiddleware);
apiV2.use(authRedirectMiddleware);
