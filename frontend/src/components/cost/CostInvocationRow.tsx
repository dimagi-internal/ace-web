import type { CostInvocation } from "../../api/types";
import { formatDuration, formatTokens, formatUsd, totalTokens } from "./format";

interface Props {
  invocation: CostInvocation;
  index: number;
}

export function CostInvocationRow({ invocation, index }: Props) {
  const start = invocation.start_ts
    ? new Date(invocation.start_ts).toLocaleTimeString()
    : "—";
  return (
    <tr className="text-xs text-muted-foreground">
      <td className="pl-12 py-1">
        run {index + 1} · {start}
        {invocation.incomplete ? " (interrupted)" : ""}
      </td>
      <td className="py-1">{formatDuration(invocation.wall_time_seconds)}</td>
      <td className="py-1">{formatUsd(invocation.estimated_cost_usd, invocation.cost_is_partial)}</td>
      <td
        className="py-1 tabular-nums"
        title={`${invocation.tokens.input_tokens.toLocaleString()} input · ${invocation.tokens.output_tokens.toLocaleString()} output · ${invocation.tokens.cache_creation_tokens.toLocaleString()} cache write · ${invocation.tokens.cache_read_tokens.toLocaleString()} cache read`}
      >
        {formatTokens(totalTokens(invocation.tokens))}
      </td>
      <td className="py-1">—</td>
    </tr>
  );
}
