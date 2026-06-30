import { useEffect, useMemo, useState } from "react";
import { HelpCircle, RefreshCw, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import type {
  CostRollup,
  Decision,
  OppCard,
  Run,
  RunSummary,
} from "../../api/types.ws";
import { Button } from "canopy-ui/ui";
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
  /**
   * Jump to the Phases view tab. Used by the open-decisions chip so a
   * reviewer who lands on the Workbench tab can one-click into the place
   * where they actually triage decisions. Optional — when omitted, the
   * chip falls back to a tooltip with the same info.
   */
  onJumpToPhases?: () => void;
  /**
   * Called after a run is trashed via the RunSelector's per-row trash
   * icon. Distinct from ``onRefresh`` because the page also needs to
   * clear the ``?run_id=`` URL param when the active run gets deleted —
   * otherwise the next snapshot fetch 404s on the now-gone run.
   */
  onRunDeleted?: (runId: string) => void;
  /**
   * Caller-fetched cost rollup. Lifted from inside CostRollupCard so the
   * lifecycle phase rows can share the same fetch via ``useOppCostRollup``
   * — see OppWorkbenchPage.
   */
  costRollup: CostRollup | null;
  workspaceSlug: string;
}

export function WorkbenchHeader({
  opp,
  run,
  runs,
  selectedRunId,
  onRunChange,
  onRefresh,
  onJumpToPhases,
  onRunDeleted,
  costRollup,
  workspaceSlug,
}: Props) {
  const navigate = useNavigate();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number>(() => Date.now());
  const [staleTick, setStaleTick] = useState(0);

  // Open + overridden are the actionable rows. Applied is the "default
  // was kept" pile — high count is fine. Build a breakdown for the chip
  // tooltip so a hover tells you which phases need attention without a
  // tab-switch.
  const decisionsSummary = useMemo(() => summarizeDecisions(run.decisions ?? []), [run.decisions]);

  // Bump every 30s so the relative "X ago" label stays current without
  // having to wait for an explicit re-render. setInterval is safe here
  // because the component lives at the top of the workbench tree.
  useEffect(() => {
    const id = setInterval(() => setStaleTick((t) => t + 1), 30000);
    return () => clearInterval(id);
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await Promise.resolve(onRefresh());
      setLastRefreshedAt(Date.now());
      toast.success("Refreshed from Drive");
    } catch (err) {
      // Surface refresh failures (Drive timeout, auth lapse, etc.) so
      // the user knows the data on screen is stale, not fresh. Without
      // this they'd think the spinner stopped → assume success.
      toast.error("Refresh failed", {
        description:
          (err as Error)?.message ||
          "Couldn't reach Drive. Try again in a moment.",
      });
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
          <RunSelector
            workspaceSlug={workspaceSlug}
            oppSlug={opp.slug}
            runs={runs}
            selectedRunId={selectedRunId}
            onChange={onRunChange}
            onRunDeleted={onRunDeleted}
          />
          {run.current_phase && (
            <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              Phase · {run.current_phase}
            </span>
          )}
          {/* Only show the mode pill for "review" — that's the only mode
              that requires user attention (the plugin pauses for human
              review at decision points). "default" / "auto" / "dry-run"
              / "sandbox" are passive status info that just adds noise. */}
          {run.mode === "review" && (
            <span
              className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-500"
              title={`Run mode: review (${modeExplanation(run.mode)})`}
            >
              review
            </span>
          )}
          {decisionsSummary.overridden > 0 && (
            <button
              type="button"
              onClick={onJumpToPhases}
              disabled={!onJumpToPhases}
              title={decisionsSummary.tooltip}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-xs font-medium text-sky-400",
                onJumpToPhases ? "transition hover:bg-sky-500/20" : "cursor-default",
              )}
              aria-label={overriddenDecisionsLabel(decisionsSummary.overridden)}
            >
              <HelpCircle className="h-3 w-3" />
              {overriddenDecisionsLabel(decisionsSummary.overridden)}
            </button>
          )}
          <TagEditor workspaceSlug={workspaceSlug} slug={opp.slug} initialTags={opp.tags ?? []} />
          <CostRollupCard data={costRollup} />
          <ScorecardPanel workspaceSlug={workspaceSlug} slug={opp.slug} />
        </div>

        {/* Action group: ghost refresh (recovery, not primary), then a
            visual divider, then the destructive Delete. The previous
            layout had refresh as the only filled-primary in the header —
            it pulled the eye to a low-priority action and sat flush
            against the trash icon, which was a mis-click hazard. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {/* staleTick re-reads here to keep the relative label current */}
          <span
            className="text-[10px] text-muted-foreground/70"
            title={`Last refreshed: ${new Date(lastRefreshedAt).toLocaleString()}`}
          >
            {/* Reference staleTick so React re-renders this span on tick. */}
            <span aria-hidden className="hidden">{staleTick}</span>
            {refreshing ? "refreshing…" : `updated ${secondsAgoLabel(lastRefreshedAt)}`}
          </span>
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
        workspaceSlug={workspaceSlug}
        slug={opp.slug}
        displayName={opp.display_name}
        onDeleted={() => navigate(`/w/${workspaceSlug}/opps`)}
      />
    </>
  );
}

/**
 * Visible + ARIA label for the "open decisions" chip in the workbench header.
 *
 * Caller guarantees `count > 0` (the chip isn't rendered for 0), but the
 * function still handles 0 cleanly so a unit test can pin the full range.
 * Pluralizes via simple ternary — Intl.PluralRules would be overkill for
 * the only-English UI and a dependency we don't pull in elsewhere here.
 *
 * Previously rendered "{n} open" as the visible label with a separate
 * "{n} open decisions — jump to Phases" ARIA label, which (1) hid the
 * noun from sighted users (issue #486) and (2) repeated an interaction
 * hint already implied by the chip being a button.
 */
export function overriddenDecisionsLabel(count: number): string {
  return `${count} overridden ${count === 1 ? "decision" : "decisions"}`;
}

function secondsAgoLabel(when: number): string {
  const s = Math.max(0, Math.floor((Date.now() - when) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

interface DecisionsSummary {
  aiDefault: number;
  overridden: number;
  tooltip: string;
}

function summarizeDecisions(decisions: Decision[]): DecisionsSummary {
  let aiDefault = 0;
  let overridden = 0;
  for (const d of decisions) {
    if (d.status === "overridden") {
      overridden += 1;
    } else {
      aiDefault += 1;
    }
  }
  const summary = [
    `${aiDefault} ai-default`,
    overridden > 0 && `${overridden} overridden`,
  ]
    .filter(Boolean)
    .join(" · ");
  const tooltip = `Decisions — ${summary}\nClick to jump to Phases.`;
  return { aiDefault, overridden, tooltip };
}

function modeExplanation(mode: string): string {
  if (mode === "auto") return "ACE runs every step without pausing for review";
  if (mode === "review") return "ACE pauses at decision points for human review";
  if (mode === "default") return "Standard run mode";
  if (mode === "dry-run") return "ACE simulates without writing changes";
  if (mode === "sandbox") return "Isolated test run";
  return mode;
}
