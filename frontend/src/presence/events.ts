/**
 * Signal: "the user just changed their presence visibility preference; the
 * presence socket should reconnect and re-enter under the new preference
 * right now, instead of waiting for its next navigation."
 *
 * Ported from canopy-web's `presence/frontend/src/presence/events.ts`
 * (reviewed + mutation-tested there) — keep this design intact.
 *
 * Same-tab: a plain `window` CustomEvent, dispatched synchronously. This is
 * a one-shot fire-and-forget signal, not shared state, so a full context
 * provider linking SettingsPage and TopNav would be overkill.
 *
 * Cross-tab: `BroadcastChannel`, best-effort. Without this, a second open
 * tab — which never ran `togglePresence` itself, so never dispatches the
 * `window` event in ITS OWN document — would keep showing the user in
 * whatever roster it's currently in until that tab happens to navigate on
 * its own. That's a real privacy gap: opting out is supposed to mean OUT,
 * not "out in the tab I happened to click it in." Feature-detected so
 * environments without `BroadcastChannel` (very old browsers, some
 * sandboxed webviews) keep exactly the same-tab-only behavior this module
 * already had.
 *
 * `BroadcastChannel` delivers to every OTHER open channel object on this
 * name — including a second channel object opened by THIS SAME tab (a
 * `subscribeToPresencePreferenceChanged` call elsewhere in this document).
 * Left alone, that would double-fire the origin tab's own subscribers: once
 * synchronously via the `window` event, once (asynchronously, on a real
 * task — not just a microtask) via its own broadcast echoing back.
 * `TAB_ID` tags every broadcast with an id unique to this page load, and
 * `subscribeToPresencePreferenceChanged` ignores a broadcast carrying its
 * own tab's id — the `window` event already covers that case.
 */
export const PRESENCE_PREFERENCE_CHANGED_EVENT = "ace:presence-preference-changed";
const BROADCAST_CHANNEL_NAME = "ace:presence-preference";

const TAB_ID =
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;

function hasBroadcastChannel(): boolean {
  return typeof BroadcastChannel !== "undefined";
}

/** Call after a successful preference PATCH. */
export function notifyPresencePreferenceChanged(): void {
  window.dispatchEvent(new Event(PRESENCE_PREFERENCE_CHANGED_EVENT));
  if (!hasBroadcastChannel()) return;
  // Open, post, close: a one-shot outbound message needs no persistent
  // channel object of its own.
  const channel = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
  channel.postMessage(TAB_ID);
  channel.close();
}

/**
 * Subscribe to the signal from `notifyPresencePreferenceChanged` — fires for
 * the same-tab dispatch (the tab where the toggle was clicked, via the
 * `window` event) and, when `BroadcastChannel` is supported, every OTHER
 * open tab too (never a second time for this tab's own broadcast — see
 * module docstring). Returns an unsubscribe function.
 */
export function subscribeToPresencePreferenceChanged(onChanged: () => void): () => void {
  window.addEventListener(PRESENCE_PREFERENCE_CHANGED_EVENT, onChanged);
  const channel = hasBroadcastChannel() ? new BroadcastChannel(BROADCAST_CHANNEL_NAME) : null;
  if (channel) {
    channel.onmessage = (e: MessageEvent) => {
      if (e.data === TAB_ID) return; // our own broadcast; the window event above already fired
      onChanged();
    };
  }
  return () => {
    window.removeEventListener(PRESENCE_PREFERENCE_CHANGED_EVENT, onChanged);
    channel?.close();
  };
}
