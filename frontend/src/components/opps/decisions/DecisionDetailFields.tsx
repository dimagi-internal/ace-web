import type { Decision } from "@/api/types.ws";
import { cn } from "@/lib/utils";

/**
 * One label/value pair in a decision's expanded detail grid. The grid
 * itself (`grid-cols-[120px_1fr]`) is owned by the caller so the two
 * surfaces can size their gutter differently.
 */
export function DetailRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </div>
      <div className="min-w-0">{value}</div>
    </>
  );
}

/**
 * Static option pills. The Workbench swaps this out for a clickable
 * variant via `optionsSlot`; the public review surface uses it as-is.
 */
export function StaticOptions({
  decision,
  selected,
}: {
  decision: Decision;
  selected: string;
}) {
  if (decision.options_considered.length === 0) {
    return <span className="text-muted-foreground/70">(none listed)</span>;
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {decision.options_considered.map((opt) => (
        <span
          key={opt}
          className={cn(
            "rounded border px-1.5 py-0.5",
            opt === selected
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
              : "border-border bg-muted/30 text-muted-foreground",
          )}
        >
          {opt}
        </span>
      ))}
    </span>
  );
}

/**
 * Everything a reader needs to judge one decision: what was picked, what
 * else was on the table, where it came from, how grounded it is, and the
 * reasoning on both the AI and the human side.
 *
 * Shared by the Workbench `DecisionsPanel` (which injects its editable
 * pill row through `optionsSlot` and appends its own edit controls) and
 * the public run-summary review surface (which passes nothing and gets
 * static pills). Copy-pasting a read-only variant would have guaranteed
 * the two drift on field set and wording — this is the one place a
 * decision's anatomy is described.
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
  /** Replaces the static pills — used by the editable Workbench panel. */
  optionsSlot?: React.ReactNode;
  optionsLabel?: string;
}) {
  return (
    <>
      <DetailRow
        label="AI default"
        value={<span className="font-medium text-foreground">{decision.ai_default}</span>}
      />
      {decision.override && (
        <DetailRow
          label="Override"
          value={<span className="font-medium text-sky-400">{decision.override}</span>}
        />
      )}
      <DetailRow
        label={optionsLabel}
        value={
          optionsSlot ?? <StaticOptions decision={decision} selected={effectiveValue} />
        }
      />
      {decision.source && (
        <DetailRow
          label="Source"
          value={<span className="text-muted-foreground">{decision.source}</span>}
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
              {decision.evidence_basis}
            </span>
          }
        />
      )}
      {decision.evidence_basis === "conflicting" &&
        decision.conflict_signals.length > 0 && (
          <DetailRow
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
          </span>
        }
      />
      {decision.notes && (
        <DetailRow
          label="AI reasoning"
          value={
            <span className="whitespace-pre-line text-muted-foreground">{decision.notes}</span>
          }
        />
      )}
      {effectiveReason && (
        <DetailRow
          label="Override reason"
          value={<span className="whitespace-pre-line text-sky-400/90">{effectiveReason}</span>}
        />
      )}
    </>
  );
}
