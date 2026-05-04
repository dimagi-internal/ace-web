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

  // Stay invisible while the API call is in flight (don't render a
  // placeholder, which would jump-cut to the real value on load and
  // jitter the header layout). Once the API returns, render even the
  // empty state — that way users know cost data WILL appear once chats
  // accumulate, instead of wondering why the chip is missing on this
  // opp but present on another.
  if (data === null) return null;
  if (data.session_count === 0) {
    return (
      <span
        className="rounded border border-border px-2 py-1 text-xs text-muted-foreground/60"
        title="No chats with cost data linked to this opp yet. Costs accumulate as ACE runs."
      >
        $— · —
      </span>
    );
  }
  const t = data.totals;
  const sessionLabel = data.session_count === 1 ? "1 chat" : `${data.session_count} chats`;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        title={`Estimated Anthropic API cost + wall time across ${sessionLabel} linked to this opp. Click for per-phase breakdown.`}
      >
        {formatUsd(t.estimated_cost_usd, t.cost_is_partial)}{" "}
        <span className="text-muted-foreground/70">est</span> ·{" "}
        {formatDuration(t.wall_time_seconds)}
      </button>
      <CostRollupDialog data={data} open={open} onOpenChange={setOpen} />
    </>
  );
}
