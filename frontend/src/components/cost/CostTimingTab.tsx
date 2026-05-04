// frontend/src/components/cost/CostTimingTab.tsx
import { useEffect, useState } from "react";

import { getSessionCostBreakdown } from "../../api/costs";
import type { CostBreakdown } from "../../api/types";
import { CostPhaseRow } from "./CostPhaseRow";
import { formatCacheHitRatio, formatDuration, formatTokens, formatUsd, totalTokens } from "./format";

interface Props {
  slug: string;
}

export function CostTimingTab({ slug }: Props) {
  const [data, setData] = useState<CostBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getSessionCostBreakdown(slug)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (error) return <div className="text-sm text-destructive">Failed to load: {error}</div>;
  if (data === null) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (data.schema_version === 0 || data.totals === null) {
    return (
      <div className="text-sm text-muted-foreground space-y-2 p-4">
        <p>No cost data for this session.</p>
        <p>
          Re-upload via <code>/ace:upload-transcript</code> to populate timing
          and token breakdowns.
        </p>
      </div>
    );
  }

  const t = data.totals;
  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap gap-4 text-sm">
        <div>
          <div className="text-muted-foreground text-xs uppercase">Wall time</div>
          <div className="text-lg font-medium">{formatDuration(t.wall_time_seconds)}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-xs uppercase">Cost</div>
          <div className="text-lg font-medium">{formatUsd(t.estimated_cost_usd, t.cost_is_partial)}</div>
        </div>
        <div title={`${t.input_tokens.toLocaleString()} input · ${t.output_tokens.toLocaleString()} output · ${t.cache_creation_tokens.toLocaleString()} cache write · ${t.cache_read_tokens.toLocaleString()} cache read`}>
          <div className="text-muted-foreground text-xs uppercase">Tokens</div>
          <div className="text-lg font-medium tabular-nums">{formatTokens(totalTokens(t))}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-xs uppercase">Cache hit</div>
          <div className="text-lg font-medium">{formatCacheHitRatio(t.cache_hit_ratio)}</div>
        </div>
      </div>
      <table className="w-full text-left">
        <thead className="text-xs uppercase text-muted-foreground">
          <tr>
            <th className="pl-2 py-2">Phase / skill</th>
            <th className="py-2">Wall</th>
            <th className="py-2">Cost</th>
            <th className="py-2">Tokens</th>
            <th className="py-2">Cache %</th>
          </tr>
        </thead>
        <tbody>
          {data.phases.map((p) => (
            <CostPhaseRow key={p.phase_name} phase={p} />
          ))}
        </tbody>
      </table>
      {t.cost_is_partial ? (
        <p className="text-xs text-muted-foreground">
          * Partial cost — some turns used unpriced models.
        </p>
      ) : null}
    </div>
  );
}
