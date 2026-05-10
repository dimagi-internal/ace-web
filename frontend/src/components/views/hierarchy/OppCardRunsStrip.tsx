import { Link } from "react-router-dom";

import type { RunSummary } from "@/api/types";
import { useOppRuns } from "@/hooks/useOppRuns";
import { relativeTime } from "@/lib/relativeTime";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Compact horizontal strip of per-run progress chips, rendered inline
 * on every opp card on /opps so a viewer sees "where each run got to"
 * at a glance without expanding.
 *
 * One chip per run, newest-first. Each chip shows the phase ordinal
 * the run reached (P1..PN) — the most legible "depth" signal at this
 * size — colored on a 4-step gradient by phase reached. Runs that
 * look complete (no current_phase + has last_actor_at) get a green ✓
 * instead of a phase number.
 *
 * Click a chip = jump to that run's workbench. Tooltip = full run_id +
 * phase + step + last activity, so the chip is informative on hover
 * without needing the expanded panel.
 *
 * Lazy-fetched via useOppRuns. Hidden on cards whose opp has no runs/
 * subfolder (flat-layout) or while the fetch is in flight.
 */
export function OppCardRunsStrip({ oppSlug, workspaceSlug }: Props) {
  const runs = useOppRuns(oppSlug);
  if (runs === null || runs.length === 0) return null;

  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-1"
      onClick={(e) => e.stopPropagation()}
    >
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/80">
        Runs
      </span>
      {runs.map((r) => (
        <RunChip
          key={r.run_id}
          run={r}
          oppSlug={oppSlug}
          workspaceSlug={workspaceSlug}
        />
      ))}
    </div>
  );
}

function RunChip({
  run,
  oppSlug,
  workspaceSlug,
}: {
  run: RunSummary;
  oppSlug: string;
  workspaceSlug: string;
}) {
  // Prefer the server-derived lifecycle_status; fall back to the older
  // "no cursor + has activity" heuristic for legacy state.yaml shapes.
  // The fallback alone misclassifies just-initialized runs (all phases
  // pending, no cursor yet) as ✓ complete — see ProgressIcon in OppRunsList.
  const ordinal = run.current_phase_ordinal ?? null;
  const justInitialized = run.lifecycle_status === "init";
  const looksComplete =
    run.lifecycle_status === "complete" ||
    (run.lifecycle_status == null && !run.current_phase && !!run.last_actor_at);

  // Tone: green for complete, muted for init, gradient by depth otherwise.
  const tone = looksComplete
    ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
    : justInitialized
    ? "border-border bg-muted/40 text-muted-foreground"
    : depthTone(ordinal);

  const label = looksComplete
    ? "✓"
    : justInitialized
    ? "▸"
    : ordinal !== null
    ? `P${ordinal}`
    : "—";

  const tooltipParts: string[] = [`Run ${run.run_id}`];
  if (looksComplete) {
    tooltipParts.push("Cursor cleared (looks complete)");
  } else if (justInitialized) {
    tooltipParts.push("Queued — kicked off, no work yet");
  } else if (ordinal !== null) {
    tooltipParts.push(`Got to phase ${ordinal}`);
  } else {
    tooltipParts.push("Phase not recorded");
  }
  if (run.current_phase_display ?? run.current_phase) {
    tooltipParts.push(
      `Phase: ${run.current_phase_display ?? run.current_phase}`,
    );
  }
  if (run.current_step_display ?? run.current_step) {
    tooltipParts.push(
      `Step: ${run.current_step_display ?? run.current_step}`,
    );
  }
  if (run.last_actor_at) {
    tooltipParts.push(`Last activity ${relativeTime(run.last_actor_at)}`);
  }
  if (run.mode) tooltipParts.push(`Mode: ${run.mode}`);

  return (
    <Link
      to={`/w/${workspaceSlug}/opps/${oppSlug}?run_id=${encodeURIComponent(run.run_id)}`}
      title={tooltipParts.join("\n")}
      className={`inline-flex h-5 min-w-[26px] items-center justify-center rounded border px-1 text-[10px] font-semibold tabular-nums transition hover:brightness-125 ${tone}`}
      onClick={(e) => e.stopPropagation()}
    >
      {label}
    </Link>
  );
}

// 4-step gradient by phase ordinal. Reds for early stops, greens for
// late stops. Numbers are ACE-plugin-specific (8 phases today) but the
// math degrades gracefully if the plugin grows phases — anything past
// 6 reads as green.
function depthTone(ordinal: number | null): string {
  if (ordinal === null) return "border-border bg-muted/40 text-muted-foreground";
  if (ordinal >= 7) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  if (ordinal >= 5) return "border-lime-500/40 bg-lime-500/10 text-lime-300";
  if (ordinal >= 3) return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return "border-rose-500/40 bg-rose-500/10 text-rose-300";
}
