import type { CostRollup } from "./types.ws";

/**
 * costs.ts — cost rollup API client.
 *
 * The opp cost-rollup endpoint (/api/opps/<slug>/cost-rollup) was a legacy
 * DRF endpoint with no v2 equivalent. Throws a descriptive error so callers
 * fail loudly. The useOppCostRollup hook already skips this when
 * workspaceSlug is falsy; callers that do pass workspaceSlug will see an
 * error in their catch handler (hook returns null on error so the UI
 * degrades gracefully).
 */
export async function getOppCostRollup(
  _oppSlug: string,
  _workspaceSlug: string,
): Promise<CostRollup> {
  throw new Error(
    "getOppCostRollup: legacy DRF endpoint removed — no v2 equivalent yet; " +
      "track this as a known feature gap (cost rollup needs a v2 backend endpoint)",
  );
}
