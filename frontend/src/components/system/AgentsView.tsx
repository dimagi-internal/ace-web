import { useState } from "react";

import type { SystemSnapshot } from "./types";
import { AgentSidebar } from "./AgentSidebar";
import { AgentCard } from "./AgentCard";
import { AgentDetailPane } from "./AgentDetailPane";
import { EmptyState } from "../opps/LoadingStates";

interface Props {
  snapshot: SystemSnapshot;
}

export function AgentsView({ snapshot }: Props) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const agents = selectedAgent
    ? snapshot.agents.filter((a) => a.name === selectedAgent)
    : snapshot.agents;

  const selected = selectedAgent ? snapshot.agents.find((a) => a.name === selectedAgent) ?? null : null;

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="w-[200px] shrink-0 overflow-y-auto border-r border-border">
        <AgentSidebar agents={snapshot.agents} selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} />
      </aside>
      <main className="flex-1 overflow-y-auto">
        {agents.map((agent) => (
          <AgentCard
            key={agent.name}
            agent={agent}
            skills={snapshot.skills}
            isSelected={selectedAgent === agent.name}
            onClick={() => setSelectedAgent(agent.name === selectedAgent ? null : agent.name)}
          />
        ))}
      </main>
      <section className="w-[420px] shrink-0 overflow-y-auto border-l border-border">
        {selected ? (
          <AgentDetailPane agent={selected} skills={snapshot.skills} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState title="Select an agent" description="Click an agent to see its details." />
          </div>
        )}
      </section>
    </div>
  );
}
