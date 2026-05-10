import { useState } from "react";

import type { CostRollup } from "../../api/types";
import { formatDuration, formatUsd } from "../cost/format";
import { CostRollupDialog } from "./CostRollupDialog";

interface Props {
  /**
   * Caller-fetched cost rollup. ``null`` while in flight (component renders
   * nothing); object with ``session_count: 0`` after the fetch resolves
   * with no linked sessions — we render nothing in that case too. Passing
   * the data in (rather than fetching here) lets the lifecycle phase
   * chips share the same fetch via ``useOppCostRollup``.
   */
  data: CostRollup | null;
}

export function CostRollupCard({ data }: Props) {
  const [open, setOpen] = useState(false);

  // Hide entirely while loading OR when no chats with cost data are linked
  // to this opp. The previous "$— · —" placeholder read as a broken state
  // — opps without ingested transcripts are the common case in dev/local
  // and looking at the header it's not obvious the chip is "data pending"
  // vs "data busted." Better to surface nothing and let the user discover
  // the cost view once data is available.
  if (data === null || data.session_count === 0) return null;

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
