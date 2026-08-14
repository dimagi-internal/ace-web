import type { Decision } from "@/api/types.ws";
import { cn } from "@/lib/utils";

/**
 * The option pills. Static for a reader, clickable for an editor —
 * one implementation, because "which option is selected" and "which
 * option the AI picked" have to read identically on both surfaces.
 *
 * A value that isn't in the AI's `options[]` (a write-in, whether saved
 * earlier or being typed now) surfaces as its own violet pill tagged
 * `new`, so the current answer is always visible in the pill row rather
 * than only in the row header.
 */
export function OptionPills({
  decision,
  selected,
  editable = false,
  onPick,
}: {
  decision: Decision;
  selected: string;
  editable?: boolean;
  onPick?: (opt: string) => void;
}) {
  const writeIns: string[] = [];
  if (selected && !decision.options_considered.includes(selected)) {
    writeIns.push(selected);
  }

  if (decision.options_considered.length === 0 && writeIns.length === 0) {
    return <span className="text-muted-foreground/70">(none listed)</span>;
  }

  return (
    <span className="flex flex-wrap gap-1.5">
      {decision.options_considered.map((opt) => {
        const isPicked = opt === selected;
        const isAiDefault = opt === decision.ai_default;
        const base = "rounded border px-1.5 py-0.5";
        const tone = isPicked
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
          : "border-border bg-muted/30 text-muted-foreground";
        if (!editable) {
          return (
            <span key={opt} className={cn(base, tone)}>
              {opt}
              {isAiDefault && <AiTag />}
            </span>
          );
        }
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onPick?.(opt)}
            aria-pressed={isPicked}
            title={isAiDefault ? "AI default" : "Pick this option"}
            className={cn(
              base,
              tone,
              "transition hover:border-emerald-500/40 hover:text-emerald-300",
              isPicked && "ring-1 ring-emerald-400/50",
            )}
          >
            {opt}
            {isAiDefault && <AiTag />}
          </button>
        );
      })}
      {writeIns.map((opt) => (
        <span
          key={`writein:${opt}`}
          className="rounded border border-violet-500/50 bg-violet-500/15 px-1.5 py-0.5 text-violet-300"
          title="A written-in answer that wasn't among the options the AI weighed"
        >
          {opt}
          <span className="ml-1 text-[9px] uppercase tracking-wider text-violet-400/70">
            new
          </span>
        </span>
      ))}
    </span>
  );
}

function AiTag() {
  return (
    <span className="ml-1 text-[9px] uppercase tracking-wider text-muted-foreground/60">
      ai
    </span>
  );
}
