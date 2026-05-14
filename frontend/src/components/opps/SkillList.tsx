import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { HelpCircle, Search, X } from "lucide-react";

import type {
  CostRollup,
  CostRollupPhase,
  PhaseInfo,
  Step,
} from "../../api/types.ws";
import { formatDuration, formatTokens, formatUsd, totalTokens } from "../../lib/format";
import { SkillRow } from "./SkillRow";

interface Props {
  steps: Step[];
  priorRunSteps: Step[];
  phases: PhaseInfo[];
  selectedSkill: string | null;
  onSelect: (skill: string) => void;
  /**
   * Per-phase cost + wall time rollup. ``null`` while the parent's fetch
   * is in flight or when the opp has no ingested transcripts (in either
   * case we just don't render the chip — see CostRollupCard for the
   * "hide on empty" rationale we're matching here).
   */
  costRollup?: CostRollup | null;
}

export function SkillList({
  steps,
  priorRunSteps,
  phases,
  selectedSkill,
  onSelect,
  costRollup,
}: Props) {
  const priorBySkill = new Map(priorRunSteps.map((s) => [s.skill_name, s] as const));
  const sortedPhases = [...phases].sort((a, b) => a.ordinal - b.ordinal);
  const costByPhase = useMemo(() => {
    const m = new Map<string, CostRollupPhase>();
    for (const p of costRollup?.phases ?? []) m.set(p.phase_name, p);
    return m;
  }, [costRollup]);
  // Persist filter via URL ``?lifecycle_filter=…`` so refreshing the page
  // (e.g. after a deploy) preserves the user's narrowing. Cleared by the
  // X button or by emptying the input — empty value drops the param.
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = searchParams.get("lifecycle_filter") ?? "";
  const setFilter = (next: string) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next) params.set("lifecycle_filter", next);
        else params.delete("lifecycle_filter");
        return params;
      },
      { replace: true },
    );
  };

  // Filter steps by display_name OR skill_name OR phase display_name.
  // Empty filter means everything passes.
  const filteredSteps = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return steps;
    return steps.filter((s) =>
      (s.display_name || "").toLowerCase().includes(needle) ||
      s.skill_name.toLowerCase().includes(needle) ||
      (s.phase_display || "").toLowerCase().includes(needle),
    );
  }, [steps, filter]);

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span>
            Lifecycle ·{" "}
            <span className="text-foreground/80">
              {filter
                ? `${filteredSteps.length} of ${steps.length}`
                : `${steps.length} skills`}
            </span>
          </span>
          <StatusLegend />
        </div>
        <div className="relative w-40">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter skills…"
            aria-label="Filter lifecycle steps by name or phase"
            className="w-full rounded border border-input bg-card px-7 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
          />
          {filter && (
            <button
              type="button"
              onClick={() => setFilter("")}
              aria-label="Clear filter"
              title="Clear filter"
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
      {filter && filteredSteps.length === 0 && (
        <div className="rounded border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          No skills match "<span className="font-medium text-foreground">{filter}</span>".
        </div>
      )}
      {sortedPhases.map((phase) => {
        const phaseSteps = filteredSteps
          .filter((s) => s.phase === phase.name)
          .sort((a, b) => a.ordinal - b.ordinal);
        if (phaseSteps.length === 0) return null;
        const progress = computePhaseProgress(phaseSteps);
        const phaseCost = costByPhase.get(phase.name);
        return (
          <section key={phase.name} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-semibold text-foreground/80">
                Phase {phase.ordinal} · {phase.display_name}
                <span className="ml-1.5 font-normal text-muted-foreground">
                  · {phaseSteps.length} {phaseSteps.length === 1 ? "step" : "steps"}
                </span>
              </h3>
              <PhaseProgressChip progress={progress} />
              {phaseCost && <PhaseCostChip cost={phaseCost} />}
              <span aria-hidden className="h-px flex-1 bg-border" />
            </div>
            <div className="flex flex-col gap-0.5">
              {phaseSteps.map((step) => (
                <SkillRow
                  key={step.skill_name}
                  step={step}
                  priorRunStep={priorBySkill.get(step.skill_name) ?? null}
                  isSelected={step.skill_name === selectedSkill}
                  onClick={() => onSelect(step.skill_name)}
                />
              ))}
            </div>
          </section>
        );
      })}
      {(() => {
        // Steps whose phase is not in the live plugin phase list render here,
        // grouped by raw phase name, so older Drive data still appears in the
        // workbench instead of silently disappearing.
        const knownPhaseNames = new Set(phases.map((p) => p.name));
        const legacySteps = filteredSteps.filter((s) => !knownPhaseNames.has(s.phase));
        if (legacySteps.length === 0) return null;

        const grouped = new Map<string, Step[]>();
        for (const s of legacySteps) {
          const existing = grouped.get(s.phase);
          if (existing) {
            existing.push(s);
          } else {
            grouped.set(s.phase, [s]);
          }
        }

        return Array.from(grouped.entries()).map(([phaseName, phaseSteps]) => {
          phaseSteps.sort((a, b) => a.ordinal - b.ordinal);
          return (
            <section key={`legacy-${phaseName}`} className="flex flex-col gap-1 opacity-75">
              <div className="flex items-baseline gap-2">
                <h3 className="text-xs font-semibold text-amber-500/80">
                  Legacy · {phaseName}
                  <span className="ml-1.5 font-normal text-amber-500/60">
                    · {phaseSteps.length}{" "}
                    {phaseSteps.length === 1 ? "step" : "steps"}
                  </span>
                </h3>
                <span aria-hidden className="h-px flex-1 bg-border" />
              </div>
              <div className="flex flex-col gap-0.5">
                {phaseSteps.map((step) => (
                  <SkillRow
                    key={step.skill_name}
                    step={step}
                    priorRunStep={priorBySkill.get(step.skill_name) ?? null}
                    isSelected={step.skill_name === selectedSkill}
                    onClick={() => onSelect(step.skill_name)}
                  />
                ))}
              </div>
            </section>
          );
        });
      })()}
    </div>
  );
}

interface PhaseProgress {
  total: number;
  complete: number;
  pending: number;
  failed: number;        // judge-fail | qa-failed | error
  meanScore: number | null;
}

function computePhaseProgress(steps: Step[]): PhaseProgress {
  let complete = 0;
  let pending = 0;
  let failed = 0;
  const scores: number[] = [];
  for (const s of steps) {
    if (s.status === "complete") complete += 1;
    else if (s.status === "pending" || s.status === "skipped") pending += 1;
    else if (s.status === "judge-fail" || s.status === "qa-failed" || s.status === "error") {
      failed += 1;
    }
    const pct = s.judge?.score_pct;
    if (pct !== null && pct !== undefined) scores.push(pct);
  }
  const meanScore =
    scores.length > 0
      ? scores.reduce((a, b) => a + b, 0) / scores.length
      : null;
  return { total: steps.length, complete, pending, failed, meanScore };
}

function PhaseProgressChip({ progress }: { progress: PhaseProgress }) {
  const { complete, pending, failed, total, meanScore } = progress;
  // Tone-by-state: failures dominate (red), partial-complete reads as
  // amber, fully-complete is green, all-pending is muted. The chip's
  // job is "where is this phase" answerable in 200ms — not a rich
  // breakdown, that's what the rows below are for.
  const tone =
    failed > 0
      ? "border-rose-500/40 bg-rose-500/10 text-rose-400"
      : complete === total
        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
        : complete > 0
          ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
          : "border-border bg-muted/40 text-muted-foreground";
  const titleParts = [
    `${complete} complete`,
    `${pending} not started`,
    failed > 0 && `${failed} failed`,
    meanScore !== null && `mean ${Math.round(meanScore)}/100`,
  ].filter(Boolean);
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[10px] font-medium tabular-nums ${tone}`}
      title={titleParts.join(" · ")}
    >
      {complete}/{total}
      {meanScore !== null && (
        <span className="ml-1 text-foreground/70">· {Math.round(meanScore)}</span>
      )}
    </span>
  );
}

function PhaseCostChip({ cost }: { cost: CostRollupPhase }) {
  const tokens = totalTokens(cost.tokens);
  return (
    <span
      className="rounded border border-border/70 bg-card px-1.5 py-0.5 text-[10px] text-muted-foreground tabular-nums"
      title={
        `Cost & timing across this phase's chats:\n` +
        `${formatDuration(cost.wall_time_seconds)} wall · ` +
        `${formatTokens(tokens)} tokens · ` +
        `${formatUsd(cost.estimated_cost_usd, cost.cost_is_partial)}` +
        (cost.session_slugs.length > 0
          ? `\n${cost.session_slugs.length} chat${cost.session_slugs.length === 1 ? "" : "s"}`
          : "")
      }
    >
      {formatDuration(cost.wall_time_seconds)} ·{" "}
      {formatTokens(tokens)}t ·{" "}
      {formatUsd(cost.estimated_cost_usd, cost.cost_is_partial)}
    </span>
  );
}

function StatusLegend() {
  return (
    <span
      tabIndex={0}
      title={[
        "Lifecycle status icons:",
        "  ✓  complete (artifacts present)",
        "  ○  not started",
        "  ▶  running",
        "  ✗  judge failed (artifacts there but judge said no)",
        "  ⚠  qa-failed (structural QA blocked eval)",
        "  ✗  error (load failure)",
        "  —  skipped",
      ].join("\n")}
      className="cursor-help rounded p-0.5 text-muted-foreground/60 hover:text-muted-foreground"
      aria-label="Status icon legend"
    >
      <HelpCircle className="h-3 w-3" />
    </span>
  );
}
