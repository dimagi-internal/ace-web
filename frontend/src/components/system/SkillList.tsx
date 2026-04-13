import type { SkillSummary } from "./types";
import { SkillRow } from "./SkillRow";

const PHASE_LABELS: Record<string, string> = {
  "app-building": "App Building",
  "connect-setup": "Connect Setup",
  "llo-management": "LLO Management",
  "closeout": "Closeout",
};

const PHASE_DOT_COLORS: Record<string, string> = {
  "app-building": "bg-blue-500",
  "connect-setup": "bg-green-500",
  "llo-management": "bg-amber-500",
  "closeout": "bg-purple-500",
};

interface Props {
  skills: SkillSummary[];
  selectedSkill: string | null;
  onSelectSkill: (name: string) => void;
}

export function SkillList({ skills, selectedSkill, onSelectSkill }: Props) {
  // Group by phase, preserving ordinal order within each phase.
  // Utility skills (phase=null) go in a separate "Utility" group at the end.
  const phases = [...new Set(skills.filter((s) => s.phase).map((s) => s.phase!))];
  const utilitySkills = skills.filter((s) => s.phase === null);

  return (
    <div className="overflow-y-auto">
      {phases.map((phase) => {
        const phaseSkills = skills.filter((s) => s.phase === phase);
        if (phaseSkills.length === 0) return null;
        return (
          <div key={phase}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-background px-4 py-2">
              <span className={`h-2 w-2 rounded-full ${PHASE_DOT_COLORS[phase] ?? "bg-muted-foreground"}`} />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {PHASE_LABELS[phase] ?? phase}
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
