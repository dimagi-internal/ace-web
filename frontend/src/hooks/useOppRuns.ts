import { listOppRuns } from "../api/opps";
import type { RunSummary } from "../api/types.ws";
import { useApi } from "./useApi";

/**
 * Fetch the runs list for an opp once per (oppSlug) change. Used by
 * both the inline summary strip on the /opps card AND the expanded
 * runs panel below it. Two consumers per card mount, but the browser
 * dedupes the request and the server's Drive cache makes it cheap.
 *
 * Returns ``null`` while in flight or on error — callers render
 * nothing in either case (the strip degrades to "no inline summary",
 * not a broken state).
 */
export function useOppRuns(oppSlug: string): RunSummary[] | null {
  const { data } = useApi(() => listOppRuns(oppSlug), [oppSlug]);
  return data;
}
