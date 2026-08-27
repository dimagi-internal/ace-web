import { useState } from "react";
import { ChevronRight, ExternalLink } from "lucide-react";

import type { RunSummary } from "@/api/types.ws";
import { RunExecutionBadge } from "@/components/opps/RunExecutionBadge";
import { relativeTime } from "@/lib/relativeTime";

/** Terminal-ish phase statuses, mapped to the four colours the track uses.
 * The plugin emits a wide vocabulary across versions ("done", "complete",
 * "pass", "skipped-by-design", "proceed-with-warn", ...), so match on
 * prefixes rather than an exhaustive list — an unrecognised status renders
 * as untouched, which is the honest default. */
function segClass(status: string | undefined): string {
  if (!status) return "bg-muted";
  const s = status.toLowerCase();
  if (s.startsWith("error") || s.startsWith("blocked") || s.startsWith("fail")) {
    return "bg-destructive";
  }
  if (s.startsWith("in_progress") || s.startsWith("partial")) return "bg-amber-500";
  if (s.startsWith("skip")) return "bg-muted-foreground/25";
  if (s === "pending" || s === "") return "bg-muted";
  return "bg-emerald-600";
}

interface Props {
  runs: RunSummary[];
  workspaceSlug: string;
  oppSlug: string;
  /** Highlighted row (the workbench's currently-selected run). */
  selectedRunId?: string | null;
  /** When given, a row click calls this instead of navigating — lets the
   * workbench switch runs in place rather than reloading the page. */
  onSelect?: (runId: string) => void;
  /** Total phases to draw when a run predates `phase_states` (older payloads
   * carry only counts). Falls back to the run's own phases_total. */
  phaseCount?: number;
  dense?: boolean;
}

/**
 * One row per run, newest-first: where it got to, the last step it
 * completed, and a way in.
 *
 * The per-phase segment track is the point. `phases_done` is a count and
 * cannot show a run that cleared 1-5, errored in 6 and completed 7 — a real
 * shape in the record. Each segment is coloured from `RunSummary.phase_states`
 * (server-derived inside the existing phase loop, so it costs nothing extra).
 *
 * Presentational only: it never fetches. The workbench passes
 * `snapshot.runs`, already loaded; the opps-list card passes the lazily
 * fetched list from `useOppRuns`.
 */
export function RunsTable({
  runs,
  workspaceSlug,
  oppSlug,
  selectedRunId,
  onSelect,
  phaseCount,
  dense = false,
}: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!runs || runs.length === 0) return null;

  const maxPhases =
    phaseCount ??
    Math.max(...runs.map((r) => r.phase_states?.length ?? r.phases_total ?? 0), 1);

  return (
    <div className="w-full">
      <div
        className={
          "grid items-center gap-3 border-b border-border px-4 text-[10px] font-medium uppercase " +
          "tracking-wider text-muted-foreground " +
          (dense ? "py-1" : "py-1.5")
        }
        style={{ gridTemplateColumns: "112px 1fr 220px 88px 20px" }}
      >
        <div>Run</div>
        <div>Phase 1 &rarr; {maxPhases}</div>
        <div>Last step completed</div>
        <div>Last activity</div>
        <div />
      </div>

      {runs.map((r) => {
        const states = r.phase_states ?? [];
        const isOpen = expanded === r.run_id;
        const isSel = selectedRunId === r.run_id;
        const href = `/w/${workspaceSlug}/opps/${encodeURIComponent(oppSlug)}?run_id=${encodeURIComponent(r.run_id)}`;

        return (
          <div key={r.run_id} className={isSel ? "bg-accent/40" : undefined}>
            <div
              className={
                "grid items-center gap-3 border-b border-border/50 px-4 text-xs " +
                "hover:bg-accent/30 " + (dense ? "py-1" : "py-1.5")
              }
              style={{ gridTemplateColumns: "112px 1fr 220px 88px 20px" }}
            >
              <a
                href={onSelect ? undefined : href}
                onClick={(e) => {
                  if (!onSelect) return;
                  e.preventDefault();
                  onSelect(r.run_id);
                }}
                className="cursor-pointer truncate font-mono text-[11px] text-foreground hover:underline"
                title={r.run_id}
              >
                {r.run_id}
              </a>

              <div
                className="grid h-[18px] gap-[1.5px]"
                style={{ gridTemplateColumns: `repeat(${maxPhases}, minmax(0, 1fr))` }}
              >
                {Array.from({ length: maxPhases }, (_, i) => {
                  const ps = states[i];
                  return (
                    <div
                      key={i}
                      className={"rounded-[1px] " + segClass(ps?.status)}
                      title={
                        ps
                          ? `${ps.ordinal} · ${ps.name} — ${ps.status}`
                          : `phase ${i + 1} — not recorded`
                      }
                    />
                  );
                })}
              </div>

              <div className="truncate font-mono text-[10px] text-muted-foreground">
                <LastStep run={r} />
              </div>

              <div className="truncate text-[10px] text-muted-foreground">
                {r.has_error_phase && (
                  <span
                    className="mr-1 font-medium text-destructive"
                    title="A phase in this run recorded an error — it is not a clean completion"
                  >
                    ⚠
                  </span>
                )}
                {r.last_actor_at ? relativeTime(r.last_actor_at) : "—"}
              </div>

              <button
                type="button"
                aria-label={isOpen ? `Collapse ${r.run_id}` : `Expand ${r.run_id}`}
                aria-expanded={isOpen}
                onClick={() => setExpanded(isOpen ? null : r.run_id)}
                className="text-muted-foreground hover:text-foreground"
              >
                <ChevronRight
                  className={"h-3.5 w-3.5 transition-transform " + (isOpen ? "rotate-90" : "")}
                />
              </button>
            </div>

            {isOpen && (
              <div className="border-b border-border/50 bg-muted/20 px-4 py-3 pl-[132px]">
                <div className="mb-2 flex flex-wrap gap-1">
                  {states.length === 0 && (
                    <span className="text-[11px] text-muted-foreground">
                      No per-phase detail recorded for this run.
                    </span>
                  )}
                  {states.map((ps) => (
                    <span
                      key={ps.ordinal}
                      className={
                        "rounded border px-1.5 py-0 font-mono text-[9.5px] " +
                        (segClass(ps.status) === "bg-emerald-600"
                          ? "border-emerald-600/50 text-emerald-700 dark:text-emerald-400"
                          : segClass(ps.status) === "bg-destructive"
                            ? "border-destructive/50 text-destructive"
                            : segClass(ps.status) === "bg-amber-500"
                              ? "border-amber-500/50 text-amber-700 dark:text-amber-400"
                              : "border-border text-muted-foreground")
                      }
                      title={ps.status}
                    >
                      {ps.ordinal} {ps.name}
                    </span>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <a
                    href={`/ace/opps/${workspaceSlug}/${encodeURIComponent(oppSlug)}/runs/${encodeURIComponent(r.run_id)}/summary`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:border-foreground/40 hover:text-foreground"
                  >
                    run summary <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                  {r.folder_id && (
                    <a
                      href={`https://drive.google.com/drive/folders/${r.folder_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:border-foreground/40 hover:text-foreground"
                    >
                      Drive run folder <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  )}
                  <a
                    href={href}
                    className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:border-foreground/40 hover:text-foreground"
                  >
                    open in workbench
                  </a>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * What the run last did — cursor, else last completed phase, else the reason
 * it has done nothing.
 *
 * The final branch is load-bearing and easy to lose in a refactor: a run
 * whose canopy turn NO RUNNER CAN CLAIM used to render identically to one
 * about to start. With no session-capable runner online that is the normal
 * day-one state, not an error, and "queued" is a lie about it.
 */
function LastStep({ run }: { run: RunSummary }) {
  // A live cursor wins: phase, then step. Showing the step alone loses the
  // phase name, which is what a reader scans for.
  const phaseLabel = run.current_phase_display ?? run.current_phase;
  const stepLabel = run.current_step_display ?? run.current_step;
  if (phaseLabel || stepLabel) {
    return (
      <span
        title={`current_phase: ${run.current_phase ?? "—"}\ncurrent_step: ${run.current_step ?? "—"}`}
      >
        <span className="text-foreground">{phaseLabel ?? stepLabel}</span>
        {phaseLabel && stepLabel && (
          <span className="text-muted-foreground/70"> · {stepLabel}</span>
        )}
      </span>
    );
  }

  const done = run.phases_done ?? 0;
  const total = run.phases_total ?? 0;
  const doneLabel = run.latest_phase_done_display ?? run.latest_phase_done;
  if (done > 0 && doneLabel) {
    return (
      <span title={`Last completed phase: ${run.latest_phase_done}`}>
        <span className="text-foreground">{doneLabel}</span>
        {total > 0 && (
          <span className="text-muted-foreground/70">
            {" "}· {done}/{total}
          </span>
        )}
      </span>
    );
  }

  if (run.execution && run.execution.state !== "not_dispatched") {
    return <RunExecutionBadge state={run.execution.state} detail={run.execution.detail} />;
  }
  return <span>queued</span>;
}
