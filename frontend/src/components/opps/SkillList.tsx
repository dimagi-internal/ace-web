import type { Step } from "../../api/types";
import { SkillRow } from "./SkillRow";

interface Props {
  steps: Step[];
  priorRunSteps: Step[];
  selectedSkill: string | null;
  onSelect: (skill: string) => void;
}

const PHASE_ORDER: Array<{ key: string; label: string }> = [
  { key: "app-building", label: "Phase 1 · App Building" },
  { key: "connect-setup", label: "Phase 2 · Connect Setup" },
  { key: "llo-management", label: "Phase 3 · LLO Management" },
  { key: "closeout", label: "Phase 4 · Closeout" },
];

export function SkillList({ steps, priorRunSteps, selectedSkill, onSelect }: Props) {
  const priorBySkill = new Map(priorRunSteps.map((s) => [s.skill_name, s] as const));

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        Lifecycle · {steps.length} skills
      </div>
      {PHASE_ORDER.map(({ key, label }) => {
        const phaseSteps = steps
          .filter((s) => s.phase === key)
          .sort((a, b) => a.ordinal - b.ordinal);
        if (phaseSteps.length === 0) return null;
        return (
          <section key={key} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="h-0.5 w-2 bg-zinc-600" />
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                {label} · {phaseSteps.length} {phaseSteps.length === 1 ? "step" : "steps"}
              </h3>
              <span className="h-px flex-1 bg-zinc-800" />
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
