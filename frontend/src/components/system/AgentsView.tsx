import type { SystemSnapshot } from "./types";

export function AgentsView({ snapshot }: { snapshot: SystemSnapshot }) {
  return <div className="flex flex-1 overflow-hidden">Agents view — {snapshot.agents.length} agents</div>;
}
