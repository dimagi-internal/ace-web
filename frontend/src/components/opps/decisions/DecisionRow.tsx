import { ChevronRight } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import {
  DETAIL_GRID,
  DecisionDetailFields,
} from "@/components/opps/decisions/DecisionDetailFields";
import {
  answerChannelLabel,
  asksAnswer,
  asksConfirmation,
  decisionDisplay,
  isDeferred,
  neededByShort,
  ownerLabel,
} from "@/components/opps/decisions/decisionDisplay";
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
 * renders THIS, rather than a lookalike that reads differently.
 *
 * ## The collapsed row says what was decided, in full (2026-10-03)
 *
 * It used to be `monospace id | ellipsized question | → ellipsized answer
 * | INFERRED | AI-DEFAULT | ⌄`, so learning anything meant expanding every
 * row — and expanding one left its own header truncated, so the full
 * question and answer never appeared at all (Jonathan's review). Now:
 *
 * - the question and the answer in force WRAP, never truncate — on a wide
 *   screen they sit side by side, at phone width they stack;
 * - `plain`, when ACE wrote one, sits under the answer as the one-line
 *   plain-language summary;
 * - the id is demoted to the detail ("Raised by");
 * - chips appear only when they say something: no chip for the
 *   always-present `ai-default` state, `inferred` moved to the detail,
 *   and `conflicting` is a quiet note rather than a badge.
 *
 * Callers supply what genuinely differs:
 *
 * - `optionsSlot` — the editor (or static pills), wired to that surface's
 *   write path;
 * - `badges` — extra chips (the Workbench's staged-edit marker, the
 *   summary's comment count and attribution);
 * - `children` — extra blocks under the detail grid (history, discussion).
 *
 * Open state is CONTROLLED, so a caller can open a specific row from
 * outside (the summary's confirm cards do).
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
  statusChip = true,
  muted = false,
  showAskIds = true,
  askMarkers = true,
  compactDetail = false,
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
  /**
   * Draw the `overridden` chip. The summary turns it off: its own
   * "changed by <name>" badge says the same thing, with a name.
   */
  statusChip?: boolean;
  /** History (a superseded row): drawn quieter, never tinted as a choice. */
  muted?: boolean;
  /**
   * Show ACE's own ids in the ask line (a solicitation question id). Off for
   * an outside reader, to whom they mean nothing.
   */
  showAskIds?: boolean;
  /**
   * Draw the "Confirm before launch" / "Answer before …" / "Not needed yet"
   * markers. Off where the row already sits under a group of that name, so
   * the label is not repeated on every row.
   */
  askMarkers?: boolean;
  /** Fold the provenance blocks of the detail behind one disclosure. */
  compactDetail?: boolean;
  children?: React.ReactNode;
}) {
  // "Overridden" = the effective answer differs from the AI default,
  // whether committed on the run, saved to Drive, or staged.
  const isOverridden = effectiveValue !== decision.ai_default;

  // Derived from the EFFECTIVE state, not a passthrough of
  // `decision.status`. The AI default (no override, no reason) gets NO chip:
  // it is the normal case, so a chip on every row carried no signal.
  const chip = !isOverridden && !effectiveReason
    ? null
    : pending
      ? { label: "overridden · pending", tone: "border-violet-500/40 bg-violet-500/10 text-violet-400" }
      : { label: "overridden", tone: "border-sky-500/40 bg-sky-500/10 text-sky-400" };

  const rowTint =
    isOverridden && !muted
      ? pending
        ? "border-l-2 border-violet-500/60 bg-sky-500/15"
        : "bg-sky-500/15"
      : "";

  const shown = decisionDisplay(decision, effectiveValue);
  const asks = asksConfirmation(decision);
  const answers = asksAnswer(decision);
  const deferred = isDeferred(decision);
  // Who answers and where — said plainly on every ask (ACE spec 2026-10-04).
  const owner = (asks || answers || deferred) ? ownerLabel(decision.owner) : "";
  const channel =
    asks || answers ? answerChannelLabel(decision.answer_channel, showAskIds) : "";
  const check = [decision.check_at, decision.correct_looks_like]
    .map((x) => x?.trim())
    .filter(Boolean);

  return (
    <div id={anchorId} className={cn("scroll-mt-24", rowTint, muted && "opacity-75")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-1 px-4 py-2.5 text-left hover:bg-accent/40 md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)_auto]"
      >
        <span
          className={cn(
            "text-[13px] leading-snug [overflow-wrap:anywhere]",
            muted ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {shown.headline}
        </span>
        <span className="col-start-1 row-start-2 flex min-w-0 flex-col gap-1 md:col-start-2 md:row-start-1">
          {/* No value line when the plain headline already states the
              answer (see `decisionDisplay`); the exact option is in the
              detail. */}
          {!shown.valueInHeadline && (
            <span className="text-[13px] leading-snug [overflow-wrap:anywhere]">
              <span aria-hidden className="mr-1 text-muted-foreground/60">
                →
              </span>
              <span
                className={cn(
                  "font-medium",
                  muted
                    ? "text-muted-foreground line-through decoration-muted-foreground/40"
                    : "text-foreground",
                )}
              >
                {shown.value || "—"}
              </span>
            </span>
          )}
          {shown.summary && (
            <span className="text-[12px] leading-snug text-muted-foreground [overflow-wrap:anywhere]">
              {shown.summary}
            </span>
          )}
          {(asks || answers) && decision.confirm_reason?.trim() && (
            <span className="text-[12px] leading-snug text-muted-foreground [overflow-wrap:anywhere]">
              <span className="text-foreground">{answers ? "Why it matters: " : "Why confirm: "}</span>
              {decision.confirm_reason.trim()}
            </span>
          )}
          {deferred && decision.revisit_when?.trim() && (
            <span className="text-[12px] leading-snug text-muted-foreground [overflow-wrap:anywhere]">
              <span className="text-foreground">Revisit when: </span>
              {decision.revisit_when.trim()}
            </span>
          )}
          {(owner || channel) && (
            <span className="text-[12px] leading-snug text-muted-foreground [overflow-wrap:anywhere]">
              {owner && (
                <>
                  <span className="text-foreground">Who answers: </span>
                  {owner}
                </>
              )}
              {owner && channel && <span aria-hidden> · </span>}
              {channel && (
                <>
                  <span className="text-foreground">Where: </span>
                  {channel}
                </>
              )}
            </span>
          )}
          {check.length > 0 && (
            <span className="text-[11px] leading-snug text-muted-foreground/80 [overflow-wrap:anywhere]">
              <span className="text-muted-foreground">Check: </span>
              {check.join(" — ")}
            </span>
          )}
          {((askMarkers && (asks || answers || deferred)) || badges || decision.evidence_basis === "conflicting" || (statusChip && chip)) && (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              {askMarkers && answers && (
                <span
                  className="shrink-0 rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-rose-400"
                  title="There is no working answer yet; it is needed by this point"
                >
                  Answer {neededByShort(decision.needed_by)}
                </span>
              )}
              {askMarkers && deferred && (
                <span
                  className="shrink-0 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
                  title="Not needed for this pilot"
                >
                  Not needed yet
                </span>
              )}
              {askMarkers && asks && (
                <span
                  className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400"
                  title="ACE recommends a person confirm this before launch"
                >
                  Confirm before launch
                </span>
              )}
              {badges}
              <EvidenceBadge basis={decision.evidence_basis} />
              {statusChip && chip && (
                <span
                  className={cn(
                    "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                    chip.tone,
                  )}
                >
                  {chip.label}
                </span>
              )}
            </span>
          )}
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "col-start-2 row-start-1 mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform md:col-start-3",
            open ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {open && (
        <div className="animate-in fade-in slide-in-from-top-1 border-t border-border/40 bg-background/30 px-4 pb-3 pt-3 text-[12px] duration-150">
          <div className={DETAIL_GRID}>
            <DecisionDetailFields
              decision={decision}
              effectiveValue={effectiveValue}
              effectiveReason={effectiveReason}
              optionsLabel={optionsLabel}
              optionsSlot={optionsSlot}
              compact={compactDetail}
            />
          </div>
          {children}
        </div>
      )}
    </div>
  );
}
