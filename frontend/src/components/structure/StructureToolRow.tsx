import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { StructureToolNode } from "../../api/types.ws";
import { formatDuration, formatUsd } from "../../lib/format";
import { StatusIcon } from "./StatusIcon";

interface Props {
  node: StructureToolNode;
  depth: number;
}

export function StructureToolRow({ node, depth }: Props) {
  const [open, setOpen] = useState(false);
  const time = node.started_at ? new Date(node.started_at).toLocaleTimeString() : "—";
  const expandable = Boolean(node.content_preview);
  return (
    <>
      <div
        className="flex items-center gap-2 py-1 text-sm"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          disabled={!expandable}
          onClick={() => setOpen(!open)}
          aria-expanded={expandable ? open : undefined}
          className="flex-1 flex items-center gap-2 text-left disabled:cursor-default"
          title={node.content_preview ?? undefined}
        >
          {expandable ? (
            <ChevronRight
              className={`h-3 w-3 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
            />
          ) : (
            <span className="w-3" />
          )}
          <StatusIcon status={node.status} />
          <span className="text-xs text-muted-foreground tabular-nums w-20 shrink-0">{time}</span>
          <span className="font-medium w-32 shrink-0 truncate" title={node.tool_name}>
            {node.tool_name}
          </span>
          <span className="truncate text-muted-foreground flex-1 min-w-0">{node.label}</span>
        </button>
        <span className="text-xs text-muted-foreground tabular-nums w-20 text-right shrink-0">
          {formatDuration(node.wall_time_seconds)}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums w-16 text-right shrink-0">
          {node.estimated_cost_usd > 0 || node.cost_is_partial
            ? formatUsd(node.estimated_cost_usd, node.cost_is_partial)
            : ""}
        </span>
      </div>
      {open && node.content_preview ? (
        <pre
          className="text-xs text-muted-foreground bg-muted/40 rounded px-2 py-1 my-1 whitespace-pre-wrap break-words"
          style={{ marginLeft: `${depth * 16 + 32}px`, marginRight: "8px" }}
        >
          {node.content_preview}
        </pre>
      ) : null}
    </>
  );
}
