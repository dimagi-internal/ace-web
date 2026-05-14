import { apiFetch } from "./client";
import type { CostRollup } from "./types.ws";

/**
 * costs.ts — cost rollup API client.
 *
 * The opp cost-rollup endpoint (/api/opps/<slug>/cost-rollup) is a legacy DRF
 * endpoint not yet migrated to v2. We keep using the legacy client here and
 * import `CostRollup` from types.ws instead of the deleted types.ts.
 */
export async function getOppCostRollup(
  oppSlug: string,
  workspaceSlug: string,
): Promise<CostRollup> {
  return apiFetch<CostRollup>(`/api/opps/${encodeURIComponent(oppSlug)}/cost-rollup`, {
    headers: { "X-ACE-Workspace": workspaceSlug },
  });
}
