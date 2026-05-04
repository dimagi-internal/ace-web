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

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="text-xs font-medium text-muted-foreground">
        Lifecycle ·{" "}
        <span className="text-foreground/80">{steps.length} skills</span>
      </div>
      {sortedPhases.map((phase) => {
        const phaseSteps = steps
          .filter((s) => s.phase === phase.name)
          .sort((a, b) => a.ordinal - b.ordinal);
        if (phaseSteps.length === 0) return null;
        return (
          <section key={phase.name} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="h-0.5 w-2 bg-muted-foreground" />
              <h3 className="text-xs font-semibold text-foreground/80">
                Phase {phase.ordinal} · {phase.display_name}
                <span className="ml-1.5 font-normal text-muted-foreground">
                  · {phaseSteps.length} {phaseSteps.length === 1 ? "step" : "steps"}
                </span>
              </h3>
              <span className="h-px flex-1 bg-border" />
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
        const legacySteps = steps.filter((s) => !knownPhaseNames.has(s.phase));
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
              <div className="flex items-center gap-2">
                <span className="h-0.5 w-2 bg-amber-500/60" />
                <h3 className="text-xs font-semibold text-amber-500/80">
                  Legacy · {phaseName}
                  <span className="ml-1.5 font-normal text-amber-500/60">
                    · {phaseSteps.length}{" "}
                    {phaseSteps.length === 1 ? "step" : "steps"}
                  </span>
                </h3>
                <span className="h-px flex-1 bg-border" />
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
