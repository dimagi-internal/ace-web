import type { StructureToolNode } from "../../api/types";
import { formatDuration } from "../../lib/format";
import { StatusIcon } from "./StatusIcon";

interface Props {
  node: StructureToolNode;
  depth: number;
}

export function StructureToolRow({ node, depth }: Props) {
  const time = node.started_at ? new Date(node.started_at).toLocaleTimeString() : "—";
  return (
    <div
      className="flex items-center gap-2 py-1 text-sm"
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <StatusIcon status={node.status} />
      <span className="text-xs text-muted-foreground tabular-nums w-20">{time}</span>
      <span className="font-medium w-16">{node.tool_name}</span>
      <span className="truncate text-muted-foreground flex-1">{node.label}</span>
      <span className="text-xs text-muted-foreground tabular-nums">
        {formatDuration(node.wall_time_seconds)}
      </span>
    </div>
  );
}
