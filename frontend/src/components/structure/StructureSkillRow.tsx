import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { StructureSkillNode } from "../../api/types";
import { formatDuration, formatUsd } from "../../lib/format";
import { ParallelCluster } from "./ParallelCluster";
import { StatusIcon } from "./StatusIcon";
import { StructureToolRow } from "./StructureToolRow";

interface Props {
  node: StructureSkillNode;
  depth: number;
}

export function StructureSkillRow({ node, depth }: Props) {
  // Subagents collapsed by default; top-level skills expanded for at-a-glance scanning.
  const [open, setOpen] = useState(!node.is_subagent);
  const expandable = node.children.length > 0;
  return (
    <>
      <div
        className="flex items-center gap-2 py-1.5 text-sm border-t"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          disabled={!expandable}
          onClick={() => setOpen(!open)}
          className="flex-1 flex items-center gap-1 text-left disabled:opacity-50"
        >
          {expandable ? (
            <ChevronRight className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`} />
          ) : (
            <span className="w-4" />
          )}
          <StatusIcon status={node.status} />
          <span className={node.is_subagent ? "italic" : "font-medium"}>{node.display}</span>
          {node.is_subagent ? (
            <span className="text-xs text-muted-foreground">
              subagent · {node.children.length} step{node.children.length === 1 ? "" : "s"}
            </span>
          ) : null}
        </button>
        <span className="text-xs text-muted-foreground tabular-nums w-20 text-right">
          {formatDuration(node.wall_time_seconds)}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums w-16 text-right">
          {formatUsd(node.estimated_cost_usd, node.cost_is_partial)}
        </span>
      </div>
      {open
        ? node.children.map((child, i) => {
            if (child.kind === "tool")
              return <StructureToolRow key={child.tool_use_id} node={child} depth={depth + 1} />;
            if (child.kind === "parallel_group")
              return <ParallelCluster key={`pg-${i}`} group={child} depth={depth + 1} />;
            if (child.kind === "skill")
              return <StructureSkillRow key={`${child.name}-${i}`} node={child} depth={depth + 1} />;
            return null;
          })
        : null}
    </>
  );
}
