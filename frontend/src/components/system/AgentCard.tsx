import { cn } from "@/lib/utils";
import type { AgentSummary, SkillSummary } from "./types";

const AGENT_COLORS: Record<string, string> = {
  "ace-orchestrator": "text-red-400",
  "app-builder": "text-blue-400",
  "connect-setup": "text-green-400",
  "llo-manager": "text-amber-400",
  "closeout": "text-purple-400",
  "ocs-tester": "text-cyan-400",
};

const AGENT_BADGE_COLORS: Record<string, string> = {
  "ace-orchestrator": "bg-red-500/15 text-red-400",
  "app-builder": "bg-blue-500/15 text-blue-400",
  "connect-setup": "bg-green-500/15 text-green-400",
  "llo-manager": "bg-amber-500/15 text-amber-400",
  "closeout": "bg-purple-500/15 text-purple-400",
  "ocs-tester": "bg-cyan-500/15 text-cyan-400",
};

// Map agents to the skills they own (derived from phase)
const AGENT_PHASES: Record<string, string> = {
  "app-builder": "app-building",
  "connect-setup": "connect-setup",
  "llo-manager": "llo-management",
  "closeout": "closeout",
};

interface Props {
  agent: AgentSummary;
  skills: SkillSummary[];
  isSelected: boolean;
  onClick: () => void;
}

export function AgentCard({ agent, skills, isSelected, onClick }: Props) {
  const phase = AGENT_PHASES[agent.name];
  const ownedSkills = phase ? skills.filter((s) => s.phase === phase) : [];

  return (
    <div className={cn("mx-4 my-3 overflow-hidden rounded-lg border border-border bg-card", isSelected && "ring-1 ring-primary")}>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-accent"
      >
        <div>
          <div className={cn("text-sm font-semibold", AGENT_COLORS[agent.name] ?? "text-foreground")}>
            {agent.name}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">{agent.description}</div>
        </div>
        {phase && (
          <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase", AGENT_BADGE_COLORS[agent.name] ?? "")}>
            {phase.replace("-", " ")}
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
                  skill.is_gate ? "border-amber-500 text-amber-400" : skill.has_judge ? "border-purple-500 text-purple-400" : "border-border text-muted-foreground",
                )}
              >
                {skill.ordinal}
              </span>
              <div className="pt-0.5">
                <div className="text-xs font-medium text-foreground">{skill.display_name}</div>
                <div className="text-[10px] text-muted-foreground">
                  {[
                    skill.is_gate && "Gate",
                    skill.has_judge && "Judge",
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
