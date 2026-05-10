import type { StructureParallelGroup } from "../../api/types";
import { formatDuration } from "../../lib/format";
import { StructureToolRow } from "./StructureToolRow";

interface Props {
  group: StructureParallelGroup;
  depth: number;
}

export function ParallelCluster({ group, depth }: Props) {
  return (
    <div style={{ paddingLeft: `${depth * 16}px` }}>
      <div className="border-l-2 border-blue-400 ml-2 pl-2">
        <div className="text-xs uppercase tracking-wide text-blue-600 py-1 flex items-center gap-2">
          <span>‖ parallel</span>
          <span className="text-muted-foreground tabular-nums">
            {formatDuration(group.wall_time_seconds)}
          </span>
        </div>
        {group.children.map((child) => (
          <StructureToolRow key={child.tool_use_id} node={child} depth={0} />
        ))}
      </div>
    </div>
  );
}
