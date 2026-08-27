import { Workflow } from "lucide-react";

import { RunsTable } from "@/components/opps/RunsTable";
import { useOppRuns } from "@/hooks/useOppRuns";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Inline list of runs under an expanded opp card.
 *
 * Presentation is `RunsTable`, shared with the workbench's Runs tab — the
 * two had drifted into separate row markup for the same data. This file
 * keeps only what is specific to the card context: the lazy fetch and the
 * empty-state rule.
 *
 * Renders only on user-expand and fetches via ``useOppRuns`` lazily, so the
 * cost is paid per-expanded-opp rather than per-rendered-card. The
 * always-rendered phase-chip strip reads ``OppCard.runs_summary`` from the
 * main payload instead, to avoid an N-card fan-out (#512).
 */
export function OppRunsList({ oppSlug, workspaceSlug }: Props) {
  const runs = useOppRuns(workspaceSlug, oppSlug);

  if (runs === null) {
    return (
      <div className="px-4 py-2 text-xs text-muted-foreground">
        Loading runs…
      </div>
    );
  }
  // Flat-layout opps have no runs/ subfolder; their "current state" lives at
  // the opp root and is already on the card chrome, so render nothing.
  if (runs.length === 0) return null;

  return (
    <div
      className="border-t border-border/60 bg-muted/20"
      onClick={(e) => e.stopPropagation()}
    >
      <header className="flex items-center gap-2 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <Workflow className="h-3 w-3" />
        Runs <span className="font-normal text-muted-foreground/70">· {runs.length}</span>
      </header>
      <RunsTable
        runs={runs}
        workspaceSlug={workspaceSlug}
        oppSlug={oppSlug}
        dense
      />
    </div>
  );
}
