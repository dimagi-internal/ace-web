import { listOppRuns } from "../api/opps";
import type { RunSummary } from "../api/types.ws";
import { useApi } from "./useApi";

/**
 * Fetch the runs list for an opp once per (workspaceSlug, oppSlug) change.
 *
 * Only the expanded-card panel (``OppRunsList``) calls this. The inline
 * phase-chip strip used to call it too, but that was an N-card fan-out
 * on the Opps-list page — see #512. The strip now reads from
 * ``OppCard.runs_summary`` carried by the main /opps payload, paying
 * the server cost once instead of N times.
 *
 * The OppRunsList caller renders only on user-expand, so the fetch
 * fires at most once per opp the user actively opens. With
 * freshness overlays from #497 the per-card /runs endpoint runs real
 * Drive work on every hit, so calling it lazily-on-expand is the only
 * pattern that's still cheap.
 *
 * Returns ``null`` while in flight or on error — callers render
 * nothing in either case (the strip degrades to "no inline summary",
 * not a broken state).
 */
export function useOppRuns(workspaceSlug: string, oppSlug: string): RunSummary[] | null {
  const { data } = useApi(
    () => listOppRuns(workspaceSlug, oppSlug),
    [workspaceSlug, oppSlug],
    { skip: !workspaceSlug },
  );
  return data;
}
