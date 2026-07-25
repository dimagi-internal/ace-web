import { apiClient } from "../api/apiClient";

/**
 * token.ts — the browser's cached delegated canopy token.
 *
 * ace-web's own `POST /api/canopy/token` (session-authed, cookie + CSRF —
 * see `apiClient`) exchanges ace's registered app credential for a
 * short-lived per-user bearer token the browser then presents directly to
 * canopy-web (`Authorization: Bearer <token>` — see api.ts, `?token=` on the
 * WS — see ws.ts). Minting a fresh one on every REST call would be wasteful
 * and slow, so it's cached here until shortly before it expires.
 *
 * `force` bypasses the cache outright — the retry-once-on-401 path in
 * api.ts calls `getCanopyToken(true)` when canopy-web itself rejects the
 * token (e.g. revoked early, clock skew), regardless of what our own TTL
 * bookkeeping thinks.
 */

interface CachedToken {
  token: string;
  expiresAtMs: number;
}

// Refetch this long before the token's real expiry so a request kicked off
// just under the wire doesn't race expiry mid-flight.
const REFRESH_SKEW_MS = 5 * 60 * 1000;

let cached: CachedToken | null = null;

interface CanopyTokenResponse {
  token: string;
  expires_at: string;
}

async function requestToken(): Promise<CanopyTokenResponse> {
  // Not present in generated.ts yet (apps.canopy hasn't had `gen:api` run
  // against it) — same `as never` escape hatch auth.ts's promoteCliAuthToGlobal
  // uses for an untyped-but-real ace endpoint.
  const { response } = await apiClient.POST("/api/canopy/token" as never, {} as never);
  if (!response.ok) {
    throw new Error(`Failed to fetch canopy token: ${response.status}`);
  }
  return (await response.json()) as CanopyTokenResponse;
}

export async function getCanopyToken(force = false): Promise<string> {
  const now = Date.now();
  if (!force && cached && now < cached.expiresAtMs - REFRESH_SKEW_MS) {
    return cached.token;
  }
  const { token, expires_at } = await requestToken();
  cached = { token, expiresAtMs: new Date(expires_at).getTime() };
  return cached.token;
}

/** Sync read for callers (e.g. ws.ts's URL builder) that can't await. */
export function peekCanopyToken(): string | null {
  return cached ? cached.token : null;
}
