import { useEffect, useState } from "react";

import { getOppCostRollup } from "../../api/costs";
import type { CostRollup } from "../../api/types";
import { formatDuration, formatUsd } from "../cost/format";
import { CostRollupDialog } from "./CostRollupDialog";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

export function CostRollupCard({ oppSlug, workspaceSlug }: Props) {
  const [data, setData] = useState<CostRollup | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
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

  if (data === null || data.session_count === 0) return null;
  const t = data.totals;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded border px-2 py-1 text-xs hover:bg-muted"
        title="Per-phase cost & timing across all linked sessions"
      >
        {formatUsd(t.estimated_cost_usd, t.cost_is_partial)} ·{" "}
        {formatDuration(t.wall_time_seconds)}
      </button>
      <CostRollupDialog data={data} open={open} onOpenChange={setOpen} />
    </>
  );
}
