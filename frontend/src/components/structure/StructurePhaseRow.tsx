import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { StructurePhase } from "../../api/types.ws";
import { formatDuration, formatUsd } from "../../lib/format";
import { ParallelCluster } from "./ParallelCluster";
import { StatusIcon } from "./StatusIcon";
import { StructureSkillRow } from "./StructureSkillRow";
import { StructureToolRow } from "./StructureToolRow";

interface Props {
  phase: StructurePhase;
  defaultOpen?: boolean;
}

export function StructurePhaseRow({ phase, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const expandable = phase.children.length > 0;
  // Lifecycle phases have ordinal 1-99; pseudo phases (_orchestration=0,
  // _other=999) skip the "Phase N:" prefix.
  const isLifecyclePhase = phase.ordinal > 0 && phase.ordinal < 100;
  return (
    <>
      <div className="flex items-center gap-2 py-2 text-sm border-t">
        <button
          type="button"
          disabled={!expandable}
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex-1 flex items-center gap-1 pl-2 text-left disabled:opacity-50"
        >
          {expandable ? (
            <ChevronRight className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`} />
          ) : (
            <span className="w-4" />
          )}
          <StatusIcon status={phase.status} />
          {isLifecyclePhase ? (
            <span className="text-xs font-semibold text-muted-foreground tabular-nums">
              Phase {phase.ordinal}:
            </span>
          ) : null}
          <span className="font-medium">{phase.display}</span>
        </button>
        <span className="text-xs text-muted-foreground tabular-nums w-20 text-right">
          {formatDuration(phase.wall_time_seconds)}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums w-16 text-right">
          {formatUsd(phase.estimated_cost_usd, phase.cost_is_partial)}
        </span>
      </div>
      {open
        ? phase.children.map((child, i) => {
            if (child.kind === "tool")
              return <StructureToolRow key={child.tool_use_id} node={child} depth={1} />;
            if (child.kind === "parallel_group")
              return <ParallelCluster key={`pg-${i}`} group={child} depth={1} />;
            if (child.kind === "skill")
              return <StructureSkillRow key={`${child.name}-${i}`} node={child} depth={1} />;
            return null;
          })
        : null}
    </>
  );
}
