import { AlertTriangle } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import { cn } from "@/lib/utils";

/**
 * The collapsed row's note about how a decision's default was grounded.
 *
 * Shared by the Workbench's `DecisionsPanel` and the public run-summary
 * review surface. It lives here rather than inline in either because the
 * vocabulary (`stated` / `inferred` / `conflicting`) is a contract with
 * ACE's decisions-log schema v4: if the meaning of "conflicting" changes,
 * exactly one component should have to move.
 *
 * Only `conflicting` says anything in the collapsed row, and it says it as
 * a quiet NOTE, not a call to action (Jonathan, 2026-10-03): that ACE's
 * sources disagreed is ACE's uncertainty, not something the reviewer must
 * act on. `inferred` is the normal case for a third of the rows, so a chip
 * on each carried no signal — it is shown in the expanded detail instead
 * ("Evidence basis"), as is `stated` by its absence.
 */
export function EvidenceBadge({
  basis,
  className,
}: {
  basis: Decision["evidence_basis"];
  className?: string;
}) {
  if (basis !== "conflicting") return null;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 text-[11px] text-amber-400/90",
        className,
      )}
      title="ACE's sources disagreed on this one, and it picked a side — open the row to see both readings"
    >
      <AlertTriangle className="h-3 w-3" aria-hidden />
      ACE's sources disagreed
    </span>
  );
}
