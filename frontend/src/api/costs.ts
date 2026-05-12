import { apiFetch } from "./client";
import type { CostRollup } from "./types";

export async function getOppCostRollup(
  oppSlug: string,
  workspaceSlug: string,
): Promise<CostRollup> {
  return apiFetch<CostRollup>(`/api/opps/${encodeURIComponent(oppSlug)}/cost-rollup`, {
    headers: { "X-ACE-Workspace": workspaceSlug },
  });
}
