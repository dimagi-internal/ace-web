import { AlertTriangle } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import { cn } from "@/lib/utils";

/**
 * The `evidence_basis` chip — how well-grounded a decision's default is.
 *
 * Shared by the Workbench's `DecisionsPanel` and the public run-summary
 * review surface. It lives here rather than inline in either because the
 * vocabulary (`stated` / `inferred` / `conflicting`) is a contract with
 * ACE's decisions-log schema v4: if the meaning of "conflicting" changes,
 * exactly one component should have to move.
 *
 * `stated` renders nothing — the un-badged row is the normal case, and a
 * badge on every row would carry no signal.
 */
export function EvidenceBadge({
  basis,
  className,
}: {
  basis: Decision["evidence_basis"];
  className?: string;
}) {
  if (basis === "conflicting") {
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center gap-1 rounded border border-amber-500/50 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400",
          className,
        )}
        title="The sources disagreed — this default resolved a contested fork"
      >
        <AlertTriangle className="h-3 w-3" />
        conflicting
      </span>
    );
  }
  if (basis === "inferred") {
    return (
      <span
        className={cn(
          "shrink-0 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
          className,
        )}
        title="Extrapolated beyond what the source directly states"
      >
        inferred
      </span>
    );
  }
  return null;
}
