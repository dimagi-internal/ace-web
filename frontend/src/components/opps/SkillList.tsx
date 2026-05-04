import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, X } from "lucide-react";

import type { PhaseInfo, Step } from "../../api/types";
import { SkillRow } from "./SkillRow";

interface Props {
  steps: Step[];
  priorRunSteps: Step[];
  phases: PhaseInfo[];
  selectedSkill: string | null;
  onSelect: (skill: string) => void;
}

export function SkillList({
  steps,
  priorRunSteps,
  phases,
  selectedSkill,
  onSelect,
}: Props) {
  const priorBySkill = new Map(priorRunSteps.map((s) => [s.skill_name, s] as const));
  const sortedPhases = [...phases].sort((a, b) => a.ordinal - b.ordinal);
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
        <div className="text-xs font-medium text-muted-foreground">
          Lifecycle ·{" "}
          <span className="text-foreground/80">
            {filter
              ? `${filteredSteps.length} of ${steps.length}`
              : `${steps.length} skills`}
          </span>
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
        return (
          <section key={phase.name} className="flex flex-col gap-1">
            <div className="flex items-baseline gap-2">
              <h3 className="text-xs font-semibold text-foreground/80">
                Phase {phase.ordinal} · {phase.display_name}
                <span className="ml-1.5 font-normal text-muted-foreground">
                  · {phaseSteps.length} {phaseSteps.length === 1 ? "step" : "steps"}
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
