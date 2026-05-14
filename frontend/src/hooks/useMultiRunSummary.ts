import { getMultiRunSummary } from "../api/opps";
import type { MultiRunSummary } from "../api/types.ws";
import { useApi } from "./useApi";

/**
 * Fetch the per-run aggregates for an opp once per (oppSlug) change.
 *
 * Powers the run-history strip (color-by-pass/fail dots next to the
 * run selector) and the per-skill score sparkline (a row-level mini
 * trend across the most recent runs). Both consumers are best-effort —
 * we tolerate a null payload so the surfaces just degrade to "no
 * cross-run signal" rather than blocking the workbench from rendering
 * if the multi-run summary is slow or unavailable.
 *
 * Limit defaults to 8 runs (the API caps at 20). 8 fits a small dot
 * strip in the header without crowding it.
 */
export function useMultiRunSummary(
  oppSlug: string,
  limit = 8,
): MultiRunSummary | null {
  const { data } = useApi(
    () => getMultiRunSummary(oppSlug, { limit }),
    [oppSlug, limit],
  );
  return data;
}
