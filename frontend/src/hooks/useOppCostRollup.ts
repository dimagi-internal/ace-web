import { getOppCostRollup } from "../api/costs";
import type { CostRollup } from "../api/types";
import { useApi } from "./useApi";

/**
 * Fetch the per-opp cost rollup once per (oppSlug, workspaceSlug) pair.
 *
 * Lifted out of CostRollupCard so that both the header chip AND the
 * lifecycle phase rows can render from the same payload without firing
 * the API twice. Returns ``null`` while in flight (callers can skip
 * rendering); returns the payload with ``session_count: 0`` once the
 * fetch resolves with no linked sessions (callers decide whether to
 * render an empty state).
 */
export function useOppCostRollup(
  oppSlug: string,
  workspaceSlug?: string,
): CostRollup | null {
  const { data } = useApi(
    () => getOppCostRollup(oppSlug, workspaceSlug as string),
    [oppSlug, workspaceSlug],
    { skip: !workspaceSlug },
  );
  return data;
}
