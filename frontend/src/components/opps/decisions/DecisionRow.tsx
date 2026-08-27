import { ChevronRight } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import { DecisionDetailFields } from "@/components/opps/decisions/DecisionDetailFields";
import { EvidenceBadge } from "@/components/opps/decisions/EvidenceBadge";
import { cn } from "@/lib/utils";

/**
 * ONE decision row — the collapsed line and the expanded detail — shared
 * by the Workbench's `DecisionsPanel` and the public run summary's
 * review surface.
 *
 * The Workbench is the reference implementation for reading and changing
 * decisions (Jonathan, 2026-08-14: *"the workbench is what I remember and
 * what I want to replicate for the decisions"*), so the public surface
 * renders THIS, rather than a lookalike that reads differently: the same
 * row anatomy, the same status-chip derivation, the same overridden tint,
 * the same detail grid and type scale.
 *
 * Callers supply what genuinely differs:
 *
 * - `optionsSlot` — the editor (or static pills), wired to that surface's
 *   write path;
 * - `badges` — extra chips in the header (the Workbench's staged-edit
 *   marker, the summary's comment count and attribution);
 * - `children` — extra blocks under the detail grid (history, discussion).
 *
 * Open state is CONTROLLED. The summary needs to open a specific row from
 * its "worth your eye" jump list; a row that owned its own state could
 * not be opened from outside.
 */
export function DecisionRow({
  decision,
  effectiveValue,
  effectiveReason,
  open,
  onToggle,
  optionsSlot,
  optionsLabel,
  badges,
  anchorId,
  pending = false,
  children,
}: {
  decision: Decision;
  /** Answer currently in force (human override / staged edit / AI default). */
  effectiveValue: string;
  /** Override rationale currently in force; "" when none. */
  effectiveReason: string;
  open: boolean;
  onToggle: () => void;
  optionsSlot?: React.ReactNode;
  optionsLabel?: string;
  badges?: React.ReactNode;
  /** DOM id, so a caller can scroll a specific row into view. */
  anchorId?: string;
  /** Staged in a buffer but not durable yet — the Workbench's case. */
  pending?: boolean;
  children?: React.ReactNode;
}) {
  // "Overridden" = the effective answer differs from the AI default,
  // whether committed on the run, saved to Drive, or staged. Colors the
  // row so a human's choices read at a glance against the ai-default
  // majority.
  const isOverridden = effectiveValue !== decision.ai_default;

  // Status chip: derived from the EFFECTIVE state, not a passthrough of
  // `decision.status` — otherwise the chip keeps reading ai-default while
  // a pick already highlights a different pill.
  const effectiveIsAiDefault = !isOverridden && !effectiveReason;
  const chipLabel = effectiveIsAiDefault
    ? "ai-default"
    : pending
      ? "overridden · pending"
      : "overridden";
  const tone = effectiveIsAiDefault
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
    : pending
      ? "border-violet-500/40 bg-violet-500/10 text-violet-400"
      : "border-sky-500/40 bg-sky-500/10 text-sky-400";

  const rowTint = isOverridden
    ? pending
      ? "border-l-2 border-violet-500/60 bg-sky-500/15"
      : "bg-sky-500/15"
    : "";

  return (
    <div id={anchorId} className={cn("scroll-mt-24", rowTint)}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-2 text-left text-xs hover:bg-accent/40"
      >
        {/* Width discipline. Every one of these truncates, and `truncate`
            resolves a flex item's `min-width:auto` to 0 — so in a narrow
            column (the summary's max-w-3xl, vs the Workbench's full-width
            pane) the QUESTION, the one thing a reader is here for, is the
            item that collapses to nothing. The id is capped, the answer
            yields, and the question keeps a floor. */}
        <span
          className="max-w-[8rem] shrink-0 truncate font-mono text-[10px] text-muted-foreground/70"
          title={decision.id}
        >
          {decision.id}
        </span>
        <span
          className="min-w-[10rem] flex-1 truncate text-foreground"
          title={decision.question}
        >
          {decision.question}
        </span>
        <span className="hidden shrink truncate text-[11px] text-muted-foreground sm:block sm:max-w-[260px]">
          → <span className="font-medium text-foreground">{effectiveValue}</span>
        </span>
        {badges}
        <EvidenceBadge basis={decision.evidence_basis} />
        <span
          className={cn(
            "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            tone,
          )}
        >
          {chipLabel}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {open && (
        <div className="animate-in fade-in slide-in-from-top-1 border-t border-border/40 bg-background/30 px-4 pb-3 pt-3 text-[11px] duration-150">
          <div className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-2">
            <DecisionDetailFields
              decision={decision}
              effectiveValue={effectiveValue}
              effectiveReason={effectiveReason}
              optionsLabel={optionsLabel}
              optionsSlot={optionsSlot}
            />
          </div>
          {children}
        </div>
      )}
    </div>
  );
}
