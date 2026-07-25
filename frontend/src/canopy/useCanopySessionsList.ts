import { useCallback, useEffect, useState } from "react";

import { SESSIONS_UPDATED_EVENT } from "../hooks/useRecentSessions";
import { listCanopySessions, type CanopySessionSummary } from "./api";

/**
 * A small list-fetching hook for canopy sessions, shared by every surface
 * that lists them (the chat sidebar, the canopy chat route's title, the
 * Workbench chat pane's linked-chats list) — mirrors `useRecentSessions`'s
 * shape for the legacy session list.
 *
 * Refetches on the same `SESSIONS_UPDATED_EVENT` bus the legacy list uses
 * (dispatched by `notifySessionsUpdated`, including from
 * `CanopyChatPanel`'s `session.title_updated` handler) rather than a
 * bespoke canopy-only channel, so a rename/title-update on either session
 * type refreshes every list that's currently mounted.
 *
 * `base` is `null` while canopy chat is disabled/not-yet-loaded — the hook
 * simply returns an empty, non-fetching list in that case.
 */
export function useCanopySessionsList(
  base: string | null,
  filters: { opp_slug?: string; opp_run_id?: string } = {},
): { sessions: CanopySessionSummary[]; refresh: () => void } {
  const [sessions, setSessions] = useState<CanopySessionSummary[]>([]);
  const oppSlug = filters.opp_slug;
  const oppRunId = filters.opp_run_id;

  const refresh = useCallback(() => {
    if (!base) {
      setSessions([]);
      return;
    }
    listCanopySessions(base, { opp_slug: oppSlug, opp_run_id: oppRunId })
      .then(setSessions)
      .catch(() => {
        /* non-fatal: list just stays empty/stale */
      });
  }, [base, oppSlug, oppRunId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    window.addEventListener(SESSIONS_UPDATED_EVENT, refresh);
    return () => window.removeEventListener(SESSIONS_UPDATED_EVENT, refresh);
  }, [refresh]);

  return { sessions, refresh };
}
