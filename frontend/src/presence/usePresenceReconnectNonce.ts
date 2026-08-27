import { useEffect, useState } from "react";

import { subscribeToPresencePreferenceChanged } from "./events";

/**
 * A counter that bumps every time this tab is told the user's presence
 * preference changed — same-tab (the Settings toggle) or cross-tab (another
 * open tab's toggle, via `BroadcastChannel`; see events.ts).
 *
 * Ported from canopy-web's `presence/frontend/src/presence/
 * usePresenceReconnectNonce.ts`. TopNav keys its presence-badge subtree on
 * this value (`<PresenceHeaderBadge key={presenceReconnectNonce} />`):
 * bumping it forces React to unmount the old subtree — closing its
 * WebSocket in `usePresence`'s cleanup — and mount a fresh one, which
 * reconnects and sends a brand-new `presence.enter` under the just-saved
 * preference. The `PresenceConsumer` only re-reads visibility on
 * `presence.enter`, so without this an opted-out user would stay visible in
 * every tab already open on a page until each one happened to navigate.
 *
 * Split out of TopNav so this — the riskiest, least-obviously-correct piece
 * of the toggle — is unit-testable on its own (see
 * usePresenceReconnectNonce.test.ts) without mounting the whole nav.
 */
export function usePresenceReconnectNonce(): number {
  const [nonce, setNonce] = useState(0);
  useEffect(() => subscribeToPresencePreferenceChanged(() => setNonce((n) => n + 1)), []);
  return nonce;
}
