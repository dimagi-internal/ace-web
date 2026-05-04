import { useState } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import type { OppCard, Run, RunSummary } from "../../api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CostRollupCard } from "./CostRollupCard";
import { DeleteOppDialog } from "./DeleteOppDialog";
import { RunSelector } from "./RunSelector";
import { ScorecardPanel } from "./ScorecardPanel";
import { TagEditor } from "./TagEditor";

interface Props {
  opp: OppCard;
  run: Run;
  runs: RunSummary[];
  selectedRunId: string | null;
  onRunChange: (runId: string) => void;
  onRefresh: () => void;
  workspaceSlug?: string;
}

export function WorkbenchHeader({ opp, run, runs, selectedRunId, onRunChange, onRefresh, workspaceSlug }: Props) {
  const navigate = useNavigate();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await Promise.resolve(onRefresh());
      toast.success("Refreshed from Drive");
    } finally {
      // Brief artificial floor so the spinner is visible even when the
      // request returns instantly — without it the user can't tell the
      // refresh actually happened.
      setTimeout(() => setRefreshing(false), 400);
    }
  };

  return (
    <>
      <div className="flex items-center gap-3 border-b border-border bg-card px-4 py-2 text-sm">
        {/* Title block: identity first, slug as a secondary line. The
            opp slug used to be invisible in the header — sharing URLs
            required scrolling back to the opps list. */}
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-semibold text-foreground">
            {opp.display_name || opp.slug}
          </span>
          {opp.display_name && opp.display_name !== opp.slug && (
            <span className="truncate text-[10px] text-muted-foreground" title={opp.slug}>
              {opp.slug}
            </span>
          )}
        </div>

        {/* Status chips group: phase, mode, run selector, tags. All
            informational — no destructive or primary actions in this
            cluster. */}
        <div className="flex flex-wrap items-center gap-2">
          <RunSelector runs={runs} selectedRunId={selectedRunId} onChange={onRunChange} />
          {run.current_phase && (
            <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              Phase · {run.current_phase}
            </span>
          )}
          {/* "review" is the only mode that requires user attention
              (gates pause for approval). Make it visually prominent so
              a reviewer landing on the workbench gets the signal. The
              other modes (default, auto, dry-run, sandbox) are passive
              status info and stay muted. */}
          <span
            className={
              "rounded px-2 py-0.5 text-xs " +
              (run.mode === "review"
                ? "border border-amber-500/40 bg-amber-500/10 text-amber-500"
                : "bg-muted text-muted-foreground")
            }
            title={`Run mode: ${run.mode} (${modeExplanation(run.mode)})`}
          >
            {run.mode}
          </span>
          <TagEditor slug={opp.slug} initialTags={opp.tags ?? []} />
          {workspaceSlug ? (
            <CostRollupCard oppSlug={opp.slug} workspaceSlug={workspaceSlug} />
          ) : null}
          <ScorecardPanel slug={opp.slug} />
        </div>

        {/* Action group: ghost refresh (recovery, not primary), then a
            visual divider, then the destructive Delete. The previous
            layout had refresh as the only filled-primary in the header —
            it pulled the eye to a low-priority action and sat flush
            against the trash icon, which was a mis-click hazard. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing}
            title="Re-read this opp's data from Google Drive"
          >
            <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", refreshing && "animate-spin")} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
          <span aria-hidden className="h-5 w-px bg-border" />
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setDeleteOpen(true)}
            aria-label="Delete opp"
            title="Delete this opp"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <DeleteOppDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        slug={opp.slug}
        displayName={opp.display_name}
        onDeleted={() => navigate("/opps")}
      />
    </>
  );
}

function modeExplanation(mode: string): string {
  if (mode === "auto") return "ACE runs every step without pausing for review";
  if (mode === "review") return "ACE pauses at gates for human approval";
  if (mode === "default") return "Standard run mode";
  if (mode === "dry-run") return "ACE simulates without writing changes";
  if (mode === "sandbox") return "Isolated test run";
  return mode;
}
