import { apiFetch } from "./client";
import type { CostBreakdown, CostRollup } from "./types";

export async function getSessionCostBreakdown(slug: string): Promise<CostBreakdown> {
  return apiFetch<CostBreakdown>(`/api/sessions/${slug}/cost-breakdown`);
}

export async function getOppCostRollup(
  oppSlug: string,
  workspaceSlug: string,
): Promise<CostRollup> {
  return apiFetch<CostRollup>(`/api/opps/${oppSlug}/cost-rollup`, {
    headers: { "X-ACE-Workspace": workspaceSlug },
  });
}
