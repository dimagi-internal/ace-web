import type { MultiRunSummary } from "../api/types.ws";

/**
 * Multi-run summary has no v2 equivalent yet.
 *
 * Returns null (degraded gracefully) so the run-history strip and
 * per-skill sparklines don't crash the Workbench — they already
 * handle null by rendering nothing. Track the missing backend endpoint
 * in the follow-up PR for multi-run compare.
 */
export function useMultiRunSummary(
  _oppSlug: string,
  _limit = 8,
): MultiRunSummary | null {
  // Intentionally returns null; no v2 endpoint yet.
  return null;
}
