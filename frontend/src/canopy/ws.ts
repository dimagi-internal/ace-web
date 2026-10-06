import { buildSessionWsUrl, buildSessionWsUrlWithTicket } from "canopy-client";

import { canopyRest } from "./client";
import { canopyPrincipal, getCanopyToken, peekCanopyToken } from "./token";

/**
 * The canopy-sessions WebSocket URL for a session.
 *
 * URL construction is `canopy-client`'s. The only ace-specific part left is
 * reading the token out of ace's own store.
 *
 * Prefer `fetchCanopyWsUrl`: this one puts the TOKEN on the URL, and URLs are
 * written to access logs. Kept for any caller that cannot await.
 */
export function buildCanopyWsUrl(base: string, sessionId: string): string {
  return buildSessionWsUrl(base, sessionId, peekCanopyToken());
}

/**
 * The socket URL with a one-time ticket on it instead of the token.
 *
 * The token is traded for the ticket over REST, where it rides a header; the
 * ticket works for one socket, for 30 seconds, so one found in a log is already
 * spent. Call it for EVERY connection, reconnects included. A contact trades on
 * the contact surface, a user on the embed one — canopy decided which at mint.
 */
export async function fetchCanopyWsUrl(
  base: string,
  sessionId: string,
  forceRefresh = false,
): Promise<string> {
  await getCanopyToken(forceRefresh);
  const path = canopyPrincipal() === "contact" ? "/api/contact/ws-ticket" : "/api/embed/ws-ticket";
  const { ticket } = await canopyRest(base).json<{ ticket: string }>(path, { method: "POST" });
  return buildSessionWsUrlWithTicket(base, sessionId, ticket);
}
