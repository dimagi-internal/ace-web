import type { PhaseInfo, SkillSummary } from "./types";
import { SkillRow } from "./SkillRow";
import { phaseColor } from "./PipelineSidebar";

interface Props {
  skills: SkillSummary[];
  phases: PhaseInfo[];
  selectedSkill: string | null;
  onSelectSkill: (name: string) => void;
}

export function SkillList({ skills, phases, selectedSkill, onSelectSkill }: Props) {
  // Render phases in their declared (ordinal) order, then utility skills
  // (phase=null) in a separate group at the end.
  const utilitySkills = skills.filter((s) => s.phase === null);

  return (
    <div className="overflow-y-auto">
      {phases.map((phase) => {
        const phaseSkills = skills.filter((s) => s.phase === phase.name);
        if (phaseSkills.length === 0) return null;
        return (
          <div key={phase.name}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-background px-4 py-2">
              <span className={`h-2 w-2 rounded-full ${phaseColor(phase.ordinal)}`} />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {phase.display_name}
              </span>
              <span className="flex-1 border-t border-border" />
            </div>
            {phaseSkills.map((skill) => (
              <SkillRow
                key={skill.name}
                skill={skill}
                isSelected={selectedSkill === skill.name}
                onClick={() => onSelectSkill(skill.name)}
              />
            ))}
          </div>
        );
      })}
      {utilitySkills.length > 0 && (
        <div>
          <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-background px-4 py-2">
            <span className="h-2 w-2 rounded-full bg-muted-foreground" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Utility Skills
            </span>
            <span className="flex-1 border-t border-border" />
          </div>
          {utilitySkills.map((skill) => (
            <SkillRow
              key={skill.name}
              skill={skill}
              isSelected={selectedSkill === skill.name}
              onClick={() => onSelectSkill(skill.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
