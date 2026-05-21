import { cn } from "@/lib/utils";
import type { AgentSummary, PhaseInfo, SkillSummary } from "./types";
import { phaseColor } from "./PipelineSidebar";

interface Props {
  agent: AgentSummary;
  skills: SkillSummary[];
  phases: PhaseInfo[];
  isSelected: boolean;
  onClick: () => void;
}

// Convert `bg-blue-500` → `text-blue-400` for agent name color.
function bgToText(bg: string): string {
  return bg.replace("bg-", "text-").replace("-500", "-400");
}

// Convert `bg-blue-500` → `bg-blue-500/15 text-blue-400` for phase badge.
function bgToBadge(bg: string): string {
  const text = bgToText(bg);
  return `${bg}/15 ${text}`;
}

export function AgentCard({ agent, skills, phases, isSelected, onClick }: Props) {
  const ownedPhase = phases.find((p) => p.agent === agent.name);
  const ownedSkills = ownedPhase ? skills.filter((s) => s.phase === ownedPhase.name) : [];
  const phaseBg = ownedPhase ? phaseColor(ownedPhase.ordinal) : "bg-muted-foreground";
  const nameColor = bgToText(phaseBg);
  const badgeClass = bgToBadge(phaseBg);

  return (
    <div className={cn("mx-4 my-3 overflow-hidden rounded-lg border border-border bg-card", isSelected && "ring-1 ring-primary")}>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-accent"
      >
        <div>
          <div className={cn("text-sm font-semibold", ownedPhase ? nameColor : "text-foreground")}>
            {agent.name}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">{agent.description}</div>
        </div>
        {ownedPhase && (
          <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase", badgeClass)}>
            {ownedPhase.display_name}
          </span>
        )}
      </button>
      {ownedSkills.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          {ownedSkills.map((skill, idx) => (
            <div key={skill.name} className="flex items-start gap-3 pb-3 last:pb-0 relative">
              {idx < ownedSkills.length - 1 && (
                <div className="absolute left-[11px] top-7 bottom-0 w-px bg-border" />
              )}
              <span
                className={cn(
                  "relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold",
                  skill.has_judge
                    ? "border-purple-500 text-purple-400"
                    : skill.is_recurring
                      ? "border-cyan-500 text-cyan-400"
                      : "border-border text-muted-foreground",
                )}
              >
                {skill.ordinal}
              </span>
              <div className="pt-0.5">
                <div className="text-xs font-medium text-foreground">{skill.display_name}</div>
                <div className="text-[10px] text-muted-foreground">
                  {[
                    skill.has_judge && "Eval",
                    skill.is_recurring && "Recurring",
                  ].filter(Boolean).join(" · ") || ""}
                </div>
                {skill.primary_output && (
                  <span className="mt-1 inline-block rounded bg-status-ok/10 px-1.5 py-0.5 font-mono text-[10px] text-status-ok">
                    {skill.primary_output}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
