import type { Decision } from "@/api/types.ws";
import { decisionDisplay } from "@/components/opps/decisions/decisionDisplay";
import { OptionPills } from "@/components/opps/decisions/OptionPills";
import { cn } from "@/lib/utils";

/**
 * One labelled block in a decision's expanded detail grid. Label ABOVE
 * value, so the same markup reads at phone width (one column) and fills a
 * wide screen (two or three) — the old fixed 120px label gutter was what
 * made the detail a narrow ribbon of text on a 1440px screen and cramped
 * at 390px. `wide` blocks span the whole row (the option editor, prose).
 */
export function DetailRow({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={cn("min-w-0", wide && "sm:col-span-full")}>
      <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </div>
      <div className="min-w-0 [overflow-wrap:anywhere]">{value}</div>
    </div>
  );
}

/** The grid the blocks sit in. Owned here so both surfaces lay out alike. */
export const DETAIL_GRID = "grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3";

const ENFORCEMENT_COPY: Record<string, string> = {
  enforced: "Enforced by the system",
  "by-design": "Holds by design (no check needed)",
  gap: "Not enforced — a known gap",
};

/**
 * Everything a reader needs to judge one decision: what else was on the
 * table, why ACE picked what it did, where that came from, where to check
 * it landed, and the human side of any change.
 *
 * Shared by the Workbench `DecisionsPanel` and the public run-summary
 * review surface — this is the one place a decision's anatomy is
 * described. The chosen answer itself is NOT repeated here: the collapsed
 * row already shows it in full, so the detail only names ACE's original
 * pick when something has since replaced it.
 *
 * Every field the 2026-10 contract added (`check_at`, `correct_looks_like`,
 * `scope`, `enforcement`, `audience`) is optional and simply absent from
 * the grid on a row that lacks it.
 */
export function DecisionDetailFields({
  decision,
  effectiveValue,
  effectiveReason,
  optionsSlot,
  optionsLabel = "Options",
}: {
  decision: Decision;
  /** Answer currently in force (override / staged edit / AI default). */
  effectiveValue: string;
  /** Override rationale currently in force; "" when none. */
  effectiveReason: string;
  /** Replaces the static pills — used by the editable surfaces. */
  optionsSlot?: React.ReactNode;
  optionsLabel?: string;
}) {
  const replaced = effectiveValue !== decision.ai_default;
  const shown = decisionDisplay(decision, effectiveValue);
  return (
    <>
      {/* The row headline/value may be ACE's plain wording; the technical
          reader still sees the exact question and option. */}
      {shown.rawQuestionDiffers && (
        <DetailRow
          wide
          label="Exact question"
          value={<span className="text-muted-foreground">{decision.question}</span>}
        />
      )}
      {shown.rawValueDiffers && (
        <DetailRow
          label="Exact option"
          value={<span className="font-mono text-[11px] text-foreground">{effectiveValue}</span>}
        />
      )}
      <DetailRow
        wide
        label={optionsLabel}
        value={
          optionsSlot ?? <OptionPills decision={decision} selected={effectiveValue} />
        }
      />
      {replaced && (
        <DetailRow
          label="ACE's original pick"
          value={<span className="font-medium text-foreground">{decision.ai_default}</span>}
        />
      )}
      {decision.override && decision.override !== effectiveValue && (
        <DetailRow
          label="Override"
          value={<span className="font-medium text-sky-400">{decision.override}</span>}
        />
      )}
      {decision.notes && (
        <DetailRow
          wide
          label="AI reasoning"
          value={
            <span className="whitespace-pre-line text-muted-foreground">{decision.notes}</span>
          }
        />
      )}
      {effectiveReason && (
        <DetailRow
          wide
          label="Override reason"
          value={<span className="whitespace-pre-line text-sky-400/90">{effectiveReason}</span>}
        />
      )}
      {decision.source && (
        <DetailRow
          label="Source"
          value={<span className="text-muted-foreground">{decision.source}</span>}
        />
      )}
      {decision.check_at && (
        <DetailRow
          label="Where to check it"
          value={<span className="text-muted-foreground">{decision.check_at}</span>}
        />
      )}
      {decision.correct_looks_like && (
        <DetailRow
          label="What right looks like"
          value={<span className="text-muted-foreground">{decision.correct_looks_like}</span>}
        />
      )}
      {decision.scope && (
        <DetailRow
          label="Applies per"
          value={<span className="text-muted-foreground">{decision.scope}</span>}
        />
      )}
      {decision.enforcement && (
        <DetailRow
          label="Enforcement"
          value={
            <span
              className={cn(
                decision.enforcement === "gap" ? "text-amber-400" : "text-muted-foreground",
              )}
            >
              {ENFORCEMENT_COPY[decision.enforcement] ?? decision.enforcement}
            </span>
          }
        />
      )}
      {decision.evidence_basis !== "stated" && (
        <DetailRow
          label="Evidence basis"
          value={
            <span
              className={cn(
                "font-medium",
                decision.evidence_basis === "conflicting"
                  ? "text-amber-400"
                  : "text-muted-foreground",
              )}
            >
              {decision.evidence_basis === "conflicting"
                ? "conflicting — ACE's sources disagreed"
                : decision.evidence_basis === "inferred"
                  ? "inferred — beyond what a source states"
                  : decision.evidence_basis}
            </span>
          }
        />
      )}
      {decision.evidence_basis === "conflicting" &&
        decision.conflict_signals.length > 0 && (
          <DetailRow
            wide
            label="Conflicting source signals"
            value={
              <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                {decision.conflict_signals.map((signal, i) => (
                  <li key={i}>{signal}</li>
                ))}
              </ul>
            }
          />
        )}
      <DetailRow
        label="Raised by"
        value={
          <span className="font-mono text-[10px] text-muted-foreground/80">
            {decision.skill}
            <span className="text-muted-foreground/50"> · {decision.id}</span>
          </span>
        }
      />
    </>
  );
}
