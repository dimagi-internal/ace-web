import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { CostSkill } from "../../api/types.ws";
import { CostInvocationRow } from "./CostInvocationRow";
import { formatDuration, formatTokens, formatUsd, totalTokens } from "../../lib/format";

interface Props {
  skill: CostSkill;
}

export function CostSkillRow({ skill }: Props) {
  const [open, setOpen] = useState(false);
  const expandable = skill.invocation_count > 1;
  const cacheTotal =
    skill.tokens.cache_read_tokens + skill.tokens.cache_creation_tokens + skill.tokens.input_tokens;
  const hit = cacheTotal ? skill.tokens.cache_read_tokens / cacheTotal : 0;
  return (
    <>
      <tr className="text-sm">
        <td className="pl-8 py-1.5">
          <button
            type="button"
            disabled={!expandable}
            onClick={() => setOpen(!open)}
            className="flex items-center gap-1 disabled:opacity-50"
          >
            {expandable ? (
              <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
            ) : (
              <span className="w-3" />
            )}
            <span>{skill.skill_display ?? skill.skill_name}</span>
            {expandable ? (
              <span className="text-xs text-muted-foreground">×{skill.invocation_count}</span>
            ) : null}
          </button>
        </td>
        <td className="py-1.5">{formatDuration(skill.wall_time_seconds)}</td>
        <td className="py-1.5">{formatUsd(skill.estimated_cost_usd, skill.cost_is_partial)}</td>
        <td
          className="py-1.5 tabular-nums"
          title={`${skill.tokens.input_tokens.toLocaleString()} input · ${skill.tokens.output_tokens.toLocaleString()} output · ${skill.tokens.cache_creation_tokens.toLocaleString()} cache write · ${skill.tokens.cache_read_tokens.toLocaleString()} cache read`}
        >
          {formatTokens(totalTokens(skill.tokens))}
        </td>
        <td className="py-1.5">{Math.round(hit * 100)}%</td>
      </tr>
      {open
        ? skill.invocations.map((inv, i) => (
            <CostInvocationRow key={inv.start_ts ?? i} invocation={inv} index={i} />
          ))
        : null}
    </>
  );
}
