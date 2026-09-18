import { buildSessionWsUrl } from "canopy-client";

import { peekCanopyToken } from "./token";

/**
 * The canopy-sessions WebSocket URL for a session.
 *
 * URL construction is `canopy-client`'s `buildSessionWsUrl`, extracted from
 * this file. The only ace-specific part left is reading the token out of ace's
 * own store — which is why the package takes it as an argument rather than
 * reaching for a global, and is what makes it testable without one.
 *
 * A missing token means no session has been minted yet, in which case the
 * caller should not have opened the socket. Left as a tokenless URL rather than
 * thrown: the connect then fails loudly at the server, instead of turning a
 * race into an exception in a render path.
 */
export function buildCanopyWsUrl(base: string, sessionId: string): string {
  return buildSessionWsUrl(base, sessionId, peekCanopyToken());
}
