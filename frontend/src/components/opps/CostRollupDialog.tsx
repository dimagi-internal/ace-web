import type { CostRollup } from "../../api/types";
import { CostPhaseRow } from "../cost/CostPhaseRow";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

interface Props {
  data: CostRollup | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CostRollupDialog({ data, open, onOpenChange }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Cost &amp; timing — opportunity rollup</DialogTitle>
        </DialogHeader>
        {data === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : data.session_count === 0 ? (
          <p className="text-sm text-muted-foreground">
            No sessions linked to this opportunity yet.
          </p>
        ) : (
          <div className="space-y-3">
            {data.sessions_without_breakdown > 0 ? (
              <div className="rounded border border-amber-500/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs">
                {data.sessions_without_breakdown} session
                {data.sessions_without_breakdown === 1 ? "" : "s"} haven't been
                re-uploaded since cost tracking shipped — totals may
                understate.
              </div>
            ) : null}
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="pl-2 py-2">Phase</th>
                  <th className="py-2">Wall</th>
                  <th className="py-2">Cost</th>
                  <th className="py-2">Output tokens</th>
                  <th className="py-2">Cache %</th>
                </tr>
              </thead>
              <tbody>
                {data.phases.map((p) => (
                  // CostPhaseRow accepts a CostPhase shape; CostRollupPhase
                  // is structurally identical except it has session_slugs and
                  // no `skills`. Adapt by passing a `skills: []` view; the
                  // dialog rolls up sessions, not skill detail.
                  <CostPhaseRow
                    key={p.phase_name}
                    phase={{ ...p, skills: [] }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
