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
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Lifecycle · {steps.length} skills
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
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Phase {phase.ordinal} · {phase.display_name} · {phaseSteps.length}{" "}
                {phaseSteps.length === 1 ? "step" : "steps"}
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
    </div>
  );
}
