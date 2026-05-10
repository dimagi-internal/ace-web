import { Link } from "react-router-dom";
import { CheckCircle2, Play, Workflow } from "lucide-react";

import type { RunSummary } from "@/api/types";
import { useOppRuns } from "@/hooks/useOppRuns";
import { relativeTime } from "@/lib/relativeTime";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
}

/**
 * Inline list of runs under an expanded opp card. Each row shows where
 * the run got to — current_phase + current_step + mode — pulled from a
 * quick scan of each run's state.yaml (no full snapshot load). Click a
 * row to jump to that run's workbench.
 *
 * Shares the useOppRuns hook with OppCardRunsStrip — the strip renders
 * inline on every card, this list renders only on expand. Both reading
 * from one hook means one network call per opp navigation regardless of
 * how many surfaces consume it.
 */
export function OppRunsList({ oppSlug, workspaceSlug }: Props) {
  const runs = useOppRuns(oppSlug);

  if (runs === null) {
    return (
      <div className="px-4 py-2 text-xs text-muted-foreground">
        Loading runs…
      </div>
    );
  }
  if (runs.length === 0) {
    // Flat-layout opps don't have a runs/ subfolder. The "current state"
    // for those lives at the opp root, surfaced via the existing card
    // chrome (current_phase / current_step on the OppCard itself), so
    // we don't need to render anything here.
    return null;
  }

  return (
    <div className="border-t border-border/60 bg-muted/20">
      <header className="flex items-center gap-2 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <Workflow className="h-3 w-3" />
        Runs <span className="font-normal text-muted-foreground/70">· {runs.length}</span>
      </header>
      <ul className="divide-y divide-border/40">
        {runs.map((r) => (
          <li key={r.run_id}>
            <Link
              to={`/w/${workspaceSlug}/opps/${oppSlug}?run_id=${encodeURIComponent(r.run_id)}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5 text-xs hover:bg-accent/40"
              onClick={(e) => e.stopPropagation()}
            >
              <ProgressIcon run={r} />
              <span className="shrink-0 font-mono text-[11px] text-foreground">
                {r.run_id}
              </span>
              <ProgressLabel run={r} />
              {r.mode && (
                <span className="shrink-0 rounded border border-border/70 bg-card px-1.5 py-0 text-[10px] text-muted-foreground">
                  {r.mode}
                </span>
              )}
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {r.last_actor_at
                  ? `last activity ${relativeTime(r.last_actor_at)}`
                  : "no activity recorded"}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ProgressIcon({ run }: { run: RunSummary }) {
  // Prefer the server-derived lifecycle_status when present — it inspects
  // the run_state.yaml phases map and distinguishes "init" (just kicked
  // off, all phases pending) from "complete" (cursor cleared because the
  // run actually finished). The fallback heuristic below collapses both
  // into ✓ which is wrong for fresh runs.
  if (run.lifecycle_status === "complete") {
    return (
      <CheckCircle2
        className="h-3 w-3 shrink-0 text-emerald-400"
        aria-label="run looks complete"
      />
    );
  }
  if (run.lifecycle_status === "init" || run.lifecycle_status === "running") {
    return (
      <Play
        className="h-3 w-3 shrink-0 text-muted-foreground/70"
        aria-label="run cursor"
      />
    );
  }
  // lifecycle_status missing (legacy run_state.yaml shape): fall back to
  // the older "no cursor + has activity" heuristic.
  const looksComplete = !run.current_phase && !!run.last_actor_at;
  if (looksComplete) {
    return (
      <CheckCircle2
        className="h-3 w-3 shrink-0 text-emerald-400"
        aria-label="run looks complete"
      />
    );
  }
  return (
    <Play
      className="h-3 w-3 shrink-0 text-muted-foreground/70"
      aria-label="run cursor"
    />
  );
}

function ProgressLabel({ run }: { run: RunSummary }) {
  if (run.lifecycle_status === "init") {
    return (
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        queued (no work yet)
      </span>
    );
  }
  if (!run.current_phase && !run.current_step) {
    return (
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        complete (no cursor)
      </span>
    );
  }
  const phaseLabel = run.current_phase_display ?? run.current_phase;
  const stepLabel = run.current_step_display ?? run.current_step;
  return (
    <span
      className="min-w-0 flex-1 truncate text-foreground"
      title={`current_phase: ${run.current_phase ?? "—"}\ncurrent_step: ${run.current_step ?? "—"}`}
    >
      {phaseLabel ?? "—"}
      {stepLabel && (
        <span className="text-muted-foreground"> · {stepLabel}</span>
      )}
    </span>
  );
}
