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
 * bookkeeping thinks; `CanopyChatPanel` also forces a refresh after a
 * reconnect attempt, so a revoked-but-unexpired token can't wedge the
 * socket in a permanent reconnect loop (I5).
 */

interface CachedToken {
  token: string;
  expiresAtMs: number;
}

// Refetch this long before the token's real expiry so a request kicked off
// just under the wire doesn't race expiry mid-flight.
const REFRESH_SKEW_MS = 5 * 60 * 1000;

let cached: CachedToken | null = null;

// In-flight dedup (I6): without this, several components mounting at once
// (e.g. the sidebar + the chat panel + the placement banner's fleet poll)
// each call getCanopyToken() before any of them has a cached result, firing
// N concurrent mints — and N new DelegatedToken rows server-side. Every
// caller in the same tick instead awaits the one request already underway.
let inflight: Promise<string> | null = null;

interface CanopyTokenResponse {
  token: string;
  expires_at: string;
}

async function requestToken(): Promise<CanopyTokenResponse> {
  const { response } = await apiClient.POST("/api/canopy/token", {});
  if (!response.ok) {
    throw new Error(`Failed to fetch canopy token: ${response.status}`);
  }
  return (await response.json()) as CanopyTokenResponse;
}

/** A non-parseable `expires_at` is treated as already-expired (M6) rather
 *  than caching a token whose expiry is `NaN` — `now < NaN - skew` is always
 *  `false`, so this was already forcing a refetch on every call; made
 *  explicit (and covered by a test) rather than relying on that NaN
 *  coincidence. */
function expiresAtMsOf(expiresAt: string): number {
  const ms = new Date(expiresAt).getTime();
  return Number.isNaN(ms) ? 0 : ms;
}

export async function getCanopyToken(force = false): Promise<string> {
  const now = Date.now();
  if (!force && cached && now < cached.expiresAtMs - REFRESH_SKEW_MS) {
    return cached.token;
  }
  if (!inflight) {
    inflight = requestToken()
      .then(({ token, expires_at }) => {
        cached = { token, expiresAtMs: expiresAtMsOf(expires_at) };
        return cached.token;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Sync read for callers (e.g. ws.ts's URL builder) that can't await. */
export function peekCanopyToken(): string | null {
  return cached ? cached.token : null;
}
