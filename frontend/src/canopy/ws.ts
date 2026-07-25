import { peekCanopyToken } from "./token";

/**
 * buildCanopyWsUrl — the canopy-sessions WebSocket URL for a session.
 *
 * `base` (canopy's `CanopyStatus.base_url`) is one of two shapes:
 *   - a same-origin PATH (default `/canopy` — dev's vite proxy, or a shared
 *     ALB path in prod) with no scheme/host of its own
 *   - an absolute `http(s)://host[/path]` URL (canopy on a different host)
 *
 * `WebSocket` requires an absolute `ws(s)://` URL either way, so when `base`
 * is a bare path we borrow `window.location`'s scheme + host; when it's
 * already absolute we just swap the scheme and keep its own host + path.
 * The delegated token rides along as `?token=` (WS has no Authorization
 * header) — a missing token here means no session has been minted yet, in
 * which case the caller should not have opened the socket.
 */
export function buildCanopyWsUrl(base: string, sessionId: string): string {
  const isAbsolute = /^https?:\/\//i.test(base);

  let origin: string;
  let pathPrefix: string;

  if (isAbsolute) {
    const url = new URL(base);
    origin = `${url.protocol === "https:" ? "wss:" : "ws:"}//${url.host}`;
    pathPrefix = url.pathname.replace(/\/$/, "");
  } else {
    const isSecure = typeof window !== "undefined" && window.location.protocol === "https:";
    const host = typeof window !== "undefined" ? window.location.host : "localhost";
    origin = `${isSecure ? "wss:" : "ws:"}//${host}`;
    pathPrefix = base.replace(/\/$/, "");
  }

  const token = peekCanopyToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${origin}${pathPrefix}/ws/canopy-sessions/${encodeURIComponent(sessionId)}/${query}`;
}
