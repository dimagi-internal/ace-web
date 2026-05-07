import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight, AlertTriangle } from "lucide-react";

import { getMultiRunSummary } from "@/api/opps";
import type { MultiRunSummary } from "@/api/types";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
  selectedRunId: string;
}

/**
 * Phase-stack view: 8 cards (one per phase) with skill counts, mean
 * judge score, sparkline of run-over-run trend, and a pending-gates
 * badge. Each card expands into the per-skill row list (compact form
 * of the workbench).
 *
 * Replaces the "34 skills in one linear flat list" complaint with
 * 8 chunks, each summarized.
 */
export function PhaseView({ oppSlug, workspaceSlug, selectedRunId }: Props) {
  const navigate = useNavigate();
  const [data, setData] = useState<MultiRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    getMultiRunSummary(oppSlug, { limit: 8 })
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)));
  }, [oppSlug]);

  const phases = useMemo(() => {
    if (!data) return [];
    const phaseMap = new Map<
      string,
      {
        name: string;
        display: string;
        ordinal: number;
        skills: typeof data.skill_index;
      }
    >();
    for (const s of data.skill_index) {
      const existing = phaseMap.get(s.phase);
      if (existing) {
        existing.skills.push(s);
      } else {
        phaseMap.set(s.phase, {
          name: s.phase,
          display: s.phase_display,
          ordinal: s.phase_ordinal,
          skills: [s],
        });
      }
    }
    return Array.from(phaseMap.values()).sort((a, b) => a.ordinal - b.ordinal);
  }, [data]);

  const selectedRun =
    data?.per_run.find((r) => r.run_id === selectedRunId) ?? data?.per_run[0];

  if (error) {
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load multi-run summary: {error}
      </div>
    );
  }
  if (!data || !selectedRun) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }

  return (
    <div className="overflow-y-auto px-6 py-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {phases.map((phase) => {
          const stats = selectedRun.phase_scores[phase.name] ?? {
            mean_score: null,
            complete: 0,
            total: phase.skills.length,
          };
          const trend = data.per_run
            .slice()
            .reverse()
            .map((r) => r.phase_scores[phase.name]?.mean_score ?? null);
          const pendingCount = phase.skills.filter(
            (s) => selectedRun.skill_status[s.skill_name] === "gate-pending",
          ).length;
          const isExpanded = expanded === phase.name;

          return (
            <div
              key={phase.name}
              className="rounded-lg border border-border bg-card p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Phase {phase.ordinal}
                  </div>
                  <div className="truncate text-sm font-semibold text-foreground">
                    {phase.display}
                  </div>
                </div>
                {pendingCount > 0 && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full
                      border border-amber-500/40 bg-amber-500/10 px-2 py-0.5
                      text-[10px] text-amber-500"
                    title={`${pendingCount} gate${pendingCount === 1 ? "" : "s"} awaiting review`}
                  >
                    <AlertTriangle className="h-3 w-3" />
                    {pendingCount}
                  </span>
                )}
              </div>

              <div className="mt-3 flex items-baseline justify-between">
                <div className="text-2xl font-semibold tabular-nums text-foreground">
                  {stats.mean_score !== null
                    ? Math.round(stats.mean_score)
                    : "—"}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    /100
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {stats.complete}/{stats.total} done
                </div>
              </div>

              <div className="mt-3">
                <Sparkline values={trend} />
              </div>

              <button
                type="button"
                onClick={() => setExpanded(isExpanded ? null : phase.name)}
                className="mt-3 flex w-full items-center justify-between
                  rounded border border-border/60 px-2 py-1 text-xs
                  text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <span>
                  {isExpanded ? "Hide" : "Show"} {phase.skills.length} skill
                  {phase.skills.length === 1 ? "" : "s"}
                </span>
                <ChevronRight
                  className={
                    "h-3 w-3 transition-transform " +
                    (isExpanded ? "rotate-90" : "")
                  }
                />
              </button>

              {isExpanded && (
                <ul className="mt-2 divide-y divide-border/50">
                  {phase.skills.map((s) => {
                    const score = selectedRun.skill_scores[s.skill_name];
                    const status = selectedRun.skill_status[s.skill_name];
                    return (
                      <li key={s.skill_name}>
                        <button
                          type="button"
                          onClick={() =>
                            navigate(
                              `/w/${workspaceSlug}/opps/${oppSlug}/runs/${selectedRun.run_id}/steps/${s.skill_name}`,
                            )
                          }
                          className="flex w-full items-center justify-between
                            gap-2 px-1 py-1.5 text-left text-xs
                            hover:bg-accent"
                        >
                          <span className="truncate text-foreground">
                            {s.display_name}
                          </span>
                          <span className="flex shrink-0 items-center gap-2 text-muted-foreground">
                            <StatusGlyph status={status} />
                            <span className="w-7 text-right tabular-nums">
                              {score !== null && score !== undefined
                                ? Math.round(score)
                                : "—"}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Sparkline({ values }: { values: (number | null)[] }) {
  // Inline SVG; small (full width × 24h). Null values plot as gaps.
  const width = 100;
  const height = 24;
  const valid = values.filter((v): v is number => v !== null);
  if (valid.length < 2) {
    return (
      <div className="text-[10px] text-muted-foreground/70">
        Run trend: {valid.length === 1 ? `${Math.round(valid[0])}` : "—"}
      </div>
    );
  }
  const max = 100;
  const min = 0;
  const stepX = width / (values.length - 1);
  const points = values
    .map((v, i) => {
      if (v === null) return null;
      const x = i * stepX;
      const y = height - ((v - min) / (max - min)) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter((p): p is string => p !== null)
    .join(" ");
  const last = valid[valid.length - 1];
  const first = valid[0];
  const delta = last - first;
  const tone =
    delta > 1
      ? "text-emerald-500"
      : delta < -1
        ? "text-rose-500"
        : "text-muted-foreground";
  return (
    <div className="flex items-center gap-2">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="text-primary/70"
      >
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
          points={points}
        />
      </svg>
      <span className={`text-[10px] tabular-nums ${tone}`}>
        {delta > 0 ? "↑" : delta < 0 ? "↓" : "·"}{" "}
        {delta === 0 ? "0" : Math.round(delta) > 0 ? `+${Math.round(delta)}` : Math.round(delta)}
      </span>
    </div>
  );
}

function StatusGlyph({ status }: { status: string }) {
  if (status === "complete") return <span className="text-emerald-500">●</span>;
  if (status === "gate-pending") return <span className="text-amber-500">⚠</span>;
  if (status === "gate-rejected") return <span className="text-rose-500">✗</span>;
  if (status === "judge-fail") return <span className="text-rose-500">✗</span>;
  if (status === "running") return <span className="text-blue-400">▶</span>;
  return <span className="text-muted-foreground/40">○</span>;
}
