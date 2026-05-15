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
        // v2 returns RFC 7807 application/problem+json with `type` URI and
        // `title`. Legacy DRF used `detail`. Match both for safety.
        const body = (await response.clone().json()) as {
          type?: string;
          title?: string;
          detail?: string;
        };
        const isAuthError =
          // v2 problem+json
          body.type?.includes("/problems/auth") ||
          body.type?.includes("/problems/forbidden") ||
          body.title === "Authentication required" ||
          // Legacy DRF detail strings (kept for any non-v2 caller)
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

// Paths in generated.ts already start with "/api/..." (NinjaAPI emits them
// that way because the API is mounted at "/api/"). So the client baseUrl is
// just the Vite BASE_URL — no extra "/api" segment, otherwise every URL
// becomes /ace/api/api/<path>.
const _client = createClient<paths>({
  baseUrl: baseUrl.replace(/\/$/, ""),
  credentials: "include",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});

// Wrap each HTTP method so we can inject parseAs: "stream" globally.
// Without this, openapi-fetch consumes the response body to populate
// the `data` field — which makes our callers' pattern of
// `const { response } = ...; await response.clone().json()` blow up with
// "Response body is already used". `parseAs: "stream"` tells openapi-fetch
// to leave the body alone so callers can read it themselves.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function withStream<F extends (...args: any[]) => any>(fn: F): F {
  return ((path: unknown, opts?: Record<string, unknown>) =>
    fn(path, { ...(opts ?? {}), parseAs: "stream" })) as F;
}

export const apiV2 = {
  GET: withStream(_client.GET),
  POST: withStream(_client.POST),
  PUT: withStream(_client.PUT),
  PATCH: withStream(_client.PATCH),
  DELETE: withStream(_client.DELETE),
  HEAD: withStream(_client.HEAD),
  OPTIONS: withStream(_client.OPTIONS),
  TRACE: withStream(_client.TRACE),
  use: _client.use.bind(_client),
  eject: _client.eject.bind(_client),
};

apiV2.use(headersMiddleware);
apiV2.use(authRedirectMiddleware);
