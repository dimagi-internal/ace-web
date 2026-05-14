import { Check, ChevronRight, Loader2, X } from "lucide-react";

import type { Message } from "../../api/types.ws";
import {
  deriveToolStatus,
  toolDisplayName,
  toolPreview,
} from "./pairToolMessages";

interface Props {
  use: Message;
  result: Message | null;
  /** Controlled-open state: true to force open, false to force closed,
   *  undefined to let the user control via the native <details> toggle. */
  forceOpen?: boolean;
}

/**
 * Renders a tool_use + tool_result as a single collapsible row.
 *
 * Header line: ``{status icon} {tool name} · {preview}`` — readable when
 * collapsed so the user can scan a long stream of tool calls without
 * expanding any. Expanded view stacks the input JSON on top of the
 * result body, both monospace.
 */
export function ToolCallPair({ use, result, forceOpen }: Props) {
  const status = deriveToolStatus(use, result);
  const name = toolDisplayName(use);
  const preview = toolPreview(use, result);

  const StatusIcon =
    status.kind === "success" ? Check
    : status.kind === "error" ? X
    : Loader2;
  const iconColor =
    status.kind === "success" ? "text-emerald-600 dark:text-emerald-400"
    : status.kind === "error" ? "text-red-600 dark:text-red-400"
    : "text-muted-foreground animate-spin";

  const input = (use.content as { input?: unknown } | undefined)?.input;

  return (
    <details
      // ``open`` controls the row when forceOpen is set; otherwise
      // ``open={undefined}`` lets the native toggle take over so single
      // rows still expand/collapse on click.
      open={forceOpen}
      className="my-1 rounded border border-border bg-muted/40 text-sm"
    >
      <summary className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-muted-foreground hover:bg-muted/60 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3 w-3 shrink-0 transition-transform group-open:rotate-90 details-marker" />
        <StatusIcon className={`h-3.5 w-3.5 shrink-0 ${iconColor}`} />
        <span className="font-mono text-xs font-medium text-foreground">
          {name}
        </span>
        {preview && (
          <span className="truncate text-xs italic text-muted-foreground">
            · {preview}
          </span>
        )}
      </summary>
      <div className="space-y-2 border-t border-border/60 p-2">
        {input !== undefined && (
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              input
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-background p-2 text-xs">
              {JSON.stringify(input, null, 2)}
            </pre>
          </div>
        )}
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
            result
          </div>
          {result === null ? (
            <div className="text-xs italic text-muted-foreground">
              (running…)
            </div>
          ) : (
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-background p-2 text-xs">
              {result.plaintext}
            </pre>
          )}
        </div>
      </div>
    </details>
  );
}
