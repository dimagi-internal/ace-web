import type { Draft } from "../api/types.ws";

export const IDLE_THRESHOLD_MS = 2_000;

export function isDraftIdle(draft: Draft | null | undefined): boolean {
  if (!draft?.last_edit_at) return true;
  return Date.now() - new Date(draft.last_edit_at).getTime() > IDLE_THRESHOLD_MS;
}

/**
 * Milliseconds until the draft lock becomes idle. Returns 0 if already
 * idle. Use this to schedule a timer that forces a re-render at the
 * idle transition point.
 */
export function msUntilDraftIdle(draft: Draft | null | undefined): number {
  if (!draft?.last_edit_at) return 0;
  const elapsed = Date.now() - new Date(draft.last_edit_at).getTime();
  return Math.max(0, IDLE_THRESHOLD_MS - elapsed);
}
