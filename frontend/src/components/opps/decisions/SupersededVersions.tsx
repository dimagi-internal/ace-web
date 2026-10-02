import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import { cn } from "@/lib/utils";

/**
 * Earlier versions of a decision row — rows the run itself replaced.
 *
 * A row carrying `superseded_by` is history (an in-run correction, or a row a
 * fork retired): it is not a live choice, so it never renders as a row of its
 * own. It stays reachable here, folded under the row that replaced it and
 * collapsed by default, in the same block anatomy as `DecisionHistory` (which
 * is the history of human EDITS to a row; this is the history of the run's own
 * rewrites of it).
 *
 * Read-only on purpose: to bring an old answer back, pick it on the live row —
 * that goes through the same attributed edit path as any other change.
 */
export function SupersededVersions({
  live,
  earlier,
  label,
}: {
  /** The row these versions led to; omitted for retired rows with no successor. */
  live?: Decision;
  earlier: readonly Decision[];
  /** Overrides the toggle copy, e.g. for a phase's retired rows. */
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  if (earlier.length === 0) return null;
  const noun = earlier.length === 1 ? "version" : "versions";
  return (
    <div className="mt-3 rounded border border-border/70 bg-muted/20 px-3 py-2 text-[12px]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-muted-foreground underline-offset-4 hover:underline"
      >
        <ChevronRight size={12} className={cn("transition-transform", open && "rotate-90")} />
        {label ?? `${earlier.length} earlier ${noun} in this run`}
      </button>
      {open && (
        <ul className="mt-2 space-y-2 border-t border-border/60 pt-2">
          {earlier.map((d) => (
            <li key={d.id} className="flex flex-col gap-0.5">
              {(!live || d.question !== live.question) && (
                <span className="text-muted-foreground">{d.question}</span>
              )}
              <span className="font-medium text-foreground line-through decoration-muted-foreground/50">
                {d.override || d.ai_default || "—"}
              </span>
              {d.notes && (
                <span className="whitespace-pre-line text-muted-foreground/80">{d.notes}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
