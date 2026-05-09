import { useEffect, useState } from "react";

import { getOppCostRollup } from "../api/costs";
import type { CostRollup } from "../api/types";

/**
 * Fetch the per-opp cost rollup once per (oppSlug, workspaceSlug) pair.
 *
 * Lifted out of CostRollupCard so that both the header chip AND the
 * lifecycle phase rows can render from the same payload without firing
 * the API twice. Returns ``data: null`` while in flight (callers can
 * skip rendering); returns ``data`` with ``session_count: 0`` once the
 * fetch resolves with no linked sessions (callers decide whether to
 * render an empty state).
 */
export function useOppCostRollup(
  oppSlug: string,
  workspaceSlug?: string,
): CostRollup | null {
  const [data, setData] = useState<CostRollup | null>(null);

  useEffect(() => {
    if (!workspaceSlug) {
      setData(null);
      return;
    }
    let cancelled = false;
    getOppCostRollup(oppSlug, workspaceSlug)
      .then((d) => !cancelled && setData(d))
      .catch(() => {
        if (!cancelled) setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [oppSlug, workspaceSlug]);

  return data;
}
