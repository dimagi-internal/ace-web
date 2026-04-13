import type { SystemSnapshot } from "./types";

export function PipelineView({ snapshot }: { snapshot: SystemSnapshot }) {
  return <div className="flex flex-1 overflow-hidden">Pipeline view — {snapshot.skills.length} skills</div>;
}
