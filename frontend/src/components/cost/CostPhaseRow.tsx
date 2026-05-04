import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { CostPhase } from "../../api/types";
import { CostSkillRow } from "./CostSkillRow";
import { formatDuration, formatTokens, formatUsd } from "./format";

interface Props {
  phase: CostPhase;
  defaultOpen?: boolean;
}

export function CostPhaseRow({ phase, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const expandable = phase.skills.length > 0;
  const cacheTotal =
    phase.tokens.cache_read_tokens + phase.tokens.cache_creation_tokens + phase.tokens.input_tokens;
  const hit = cacheTotal ? phase.tokens.cache_read_tokens / cacheTotal : 0;
  // Lifecycle phases have ordinal 1+ (Phase 1: Design Review, ...). Pseudo-
  // phases like _orchestration (0) and _other (999) skip the prefix.
  const isLifecyclePhase = phase.phase_ordinal > 0 && phase.phase_ordinal < 100;
  return (
    <>
      <tr className="border-t">
        <td className="pl-2 py-2">
          <button
            type="button"
            disabled={!expandable}
            onClick={() => setOpen(!open)}
            className="flex items-center gap-1 font-medium disabled:opacity-70"
          >
            {expandable ? (
              <ChevronRight className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`} />
            ) : (
              <span className="w-4" />
            )}
            {isLifecyclePhase ? (
              <span className="text-xs font-semibold text-muted-foreground tabular-nums">
                Phase {phase.phase_ordinal}:
              </span>
            ) : null}
            <span>{phase.phase_display}</span>
          </button>
        </td>
        <td className="py-2">{formatDuration(phase.wall_time_seconds)}</td>
        <td className="py-2">{formatUsd(phase.estimated_cost_usd, phase.cost_is_partial)}</td>
        <td className="py-2">{formatTokens(phase.tokens.output_tokens)}</td>
        <td className="py-2">{Math.round(hit * 100)}%</td>
      </tr>
      {open ? phase.skills.map((s) => <CostSkillRow key={s.skill_name} skill={s} />) : null}
    </>
  );
}
