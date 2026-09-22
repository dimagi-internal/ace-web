import { useEffect, useRef } from "react";

import {
  CanopyPageStateRejected,
  declareCanopyPageState,
  type CanopyPageState,
} from "./api";
import { canopyPrincipal } from "./token";

/**
 * Keep canopy told what this surface is currently showing.
 *
 * Before this, an ace-web chat learned about its opp exactly once: the
 * `opp_slug`/`opp_run_id`/`opp_step_skill` stamped into `metadata` at session
 * create. That is frozen the moment the session exists, so changing the run
 * selector or clicking a different step left the agent reasoning about the
 * screen the chat was OPENED on — and by turn three it was confidently
 * discussing a step the reader had left. canopy fixed this upstream on
 * 2026-09-16 with a declared page state the agent re-reads whenever it needs
 * to (its own `current_page` MCP tool), plus a copy folded into the first
 * message so turn one does not depend on the MCP connection having landed.
 *
 * This is the ace-web half of that. It is REST on the session — the same
 * delegated token every other canopy call here already uses — so it needs no
 * iframe, no widget, and no change to `CanopyChatPanel`.
 *
 * ## Three things this hook has to get right
 *
 * **It must never break the chat.** A page-state PUT is an enhancement; a
 * failed one means the agent knows less, not that the conversation is broken.
 * Every error is swallowed after a `console.warn`, exactly as
 * `useCanopySessionsList` treats a failed list.
 *
 * **It must not re-send on every render.** The caller builds a fresh object
 * each render, so identity comparison would PUT forever. Comparison is on the
 * serialised value.
 *
 * **It must not let an older view win.** Selections change faster than a round
 * trip: click step A then step B and two PUTs race, and canopy replaces
 * wholesale, so whichever the SERVER applies last is what the agent reads. If
 * that is A, the bug this hook exists to fix is back, now with extra steps. So
 * only one request is ever in flight; the newest desired state is held and
 * sent when it drains, and intermediate states are dropped rather than queued
 * (nobody needs the agent to know about a step that was on screen for 80ms).
 */
export function useCanopyPageState(
  base: string | null,
  sessionId: string | null,
  state: CanopyPageState | null,
): void {
  // The newest state we WANT canopy to hold, and whether a PUT is in flight.
  // Refs rather than state: none of this should cause a render.
  const desired = useRef<string | null>(null);
  const sent = useRef<string | null>(null);
  const inFlight = useRef(false);
  // Identifies the session the `sent` bookkeeping belongs to, so switching
  // chats cannot make a fresh session look already-declared.
  const sentFor = useRef<string | null>(null);

  // The effect depends on this, not on `state`: the caller builds a fresh
  // object every render, so an identity dependency would re-run forever.
  const serialised = state ? JSON.stringify(state) : null;

  useEffect(() => {
    if (!base || !sessionId || !serialised) return;
    // Page state is a user's surface; the contact routes carry no
    // `page-state`. Declaring it would 404 on every selection change and, as a
    // 404 reads as transient here, retry forever. A contact's agent simply
    // hears what they type instead of what they are looking at.
    if (canopyPrincipal() === "contact") return;

    if (sentFor.current !== sessionId) {
      sentFor.current = sessionId;
      sent.current = null;
    }

    desired.current = serialised;

    const drain = async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        // Re-read `desired` each pass: it may have moved on while the previous
        // request was in flight, and the last write is the one that should win.
        while (desired.current !== null && desired.current !== sent.current) {
          const payload = desired.current;
          try {
            await declareCanopyPageState(base, sessionId, JSON.parse(payload));
            sent.current = payload;
          } catch (err) {
            if (err instanceof CanopyPageStateRejected) {
              // Canopy will refuse this payload every time — most likely
              // `too_large`, meaning the page sent rows where it should have
              // sent ids. Retrying is pointless and looping on it would spin,
              // so record it as sent and stop.
              console.warn("canopy refused this page state; not retrying", err);
              sent.current = payload;
            } else {
              // Transient (offline, 5xx). Leave `sent` alone so the next
              // selection change tries again, but stop this drain.
              console.warn("could not declare canopy page state", err);
              return;
            }
          }
        }
      } finally {
        inFlight.current = false;
      }
    };

    void drain();
  }, [base, sessionId, serialised]);
}
