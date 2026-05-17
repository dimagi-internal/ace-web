import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { StructureDirectTurnNode } from "../../api/types.ws";
import { formatUsd } from "../../lib/format";

interface Props {
  node: StructureDirectTurnNode;
  depth: number;
}

function shortModel(model: string | null): string {
  if (!model) return "—";
  // claude-sonnet-4-6 → sonnet-4.6, claude-opus-4-7 → opus-4.7
  const m = /^claude-(opus|sonnet|haiku)-(\d+)-(\d+)/.exec(model);
  if (m) return `${m[1]}-${m[2]}.${m[3]}`;
  return model;
}

export function StructureDirectTurnRow({ node, depth }: Props) {
  const [open, setOpen] = useState(false);
  const time = node.started_at ? new Date(node.started_at).toLocaleTimeString() : "—";
  const expandable = Boolean(node.text_preview);
  const totalTokens =
    node.tokens.input_tokens +
    node.tokens.output_tokens +
    node.tokens.cache_creation_tokens +
    node.tokens.cache_read_tokens;
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
          className="flex-1 min-w-0 flex items-center gap-2 text-left disabled:cursor-default"
          title={node.text_preview ?? undefined}
        >
          {expandable ? (
            <ChevronRight
              className={`h-3 w-3 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
            />
          ) : (
            <span className="w-3" />
          )}
          <span className="text-xs text-muted-foreground tabular-nums w-20 shrink-0">{time}</span>
          <span
            className="font-medium w-32 shrink-0 truncate text-muted-foreground italic"
            title={node.model ?? undefined}
          >
            {shortModel(node.model)}
          </span>
          <span className="truncate text-muted-foreground flex-1 min-w-0">
            {node.text_preview ?? "(no text)"}
          </span>
        </button>
        <span className="text-xs text-muted-foreground tabular-nums w-20 text-right shrink-0">
          {totalTokens.toLocaleString()} tok
        </span>
        <span className="text-xs text-muted-foreground tabular-nums w-16 text-right shrink-0">
          {formatUsd(node.estimated_cost_usd, node.cost_is_partial)}
        </span>
      </div>
      {open && node.text_preview ? (
        <pre
          className="text-xs text-muted-foreground bg-muted/40 rounded px-2 py-1 my-1 whitespace-pre-wrap break-words"
          style={{ marginLeft: `${depth * 16 + 32}px`, marginRight: "8px" }}
        >
          {node.text_preview}
        </pre>
      ) : null}
    </>
  );
}
