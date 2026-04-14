import { cn } from "@/lib/utils";
import type { AgentSummary, PhaseInfo } from "./types";
import { phaseColor } from "./PipelineSidebar";

interface Props {
  agents: AgentSummary[];
  phases: PhaseInfo[];
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
}

export function AgentSidebar({ agents, phases, selectedAgent, onSelectAgent }: Props) {
  // Color an agent by the phase it owns (matches phase-dot colors in the
  // Pipeline view). Agents without a phase (orchestrator, utility) get a
  // muted dot.
  const colorFor = (agentName: string) => {
    const phase = phases.find((p) => p.agent === agentName);
    return phase ? phaseColor(phase.ordinal) : "bg-muted-foreground";
  };

  return (
    <div className="flex flex-col gap-1 p-2">
      <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Agents
      </div>
      <button
        type="button"
        onClick={() => onSelectAgent(null)}
        className={cn(
          "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs",
          selectedAgent === null
            ? "bg-primary/10 text-foreground"
            : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )}
      >
        <span className="flex-1">All Agents</span>
        <span className="text-[10px] text-muted-foreground">{agents.length}</span>
      </button>
      {agents.map((agent) => (
        <button
          key={agent.name}
          type="button"
          onClick={() => onSelectAgent(agent.name)}
          className={cn(
            "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs",
            selectedAgent === agent.name
              ? "bg-primary/10 text-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-foreground",
          )}
        >
          <span className={cn("h-2 w-2 shrink-0 rounded-full", colorFor(agent.name))} />
          <span className="flex-1 truncate">{agent.name}</span>
        </button>
      ))}
    </div>
  );
}
