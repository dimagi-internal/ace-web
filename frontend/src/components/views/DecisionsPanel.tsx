import { useMemo, useState } from "react";
import { ChevronRight, HelpCircle } from "lucide-react";

import type { Decision, SavedDecisionOverride } from "@/api/types.ws";
import { DecisionAnswerEditor } from "@/components/opps/decisions/DecisionAnswerEditor";
import {
  DecisionDetailFields,
} from "@/components/opps/decisions/DecisionDetailFields";
import { DecisionHistory } from "@/components/opps/decisions/DecisionHistory";
import { EvidenceBadge } from "@/components/opps/decisions/EvidenceBadge";
import { cn } from "@/lib/utils";

import type { EditOp } from "./decisions/decisionsReducer";

interface Props {
  /** The phase whose decisions we want to show — match `Decision.phase`. */
  phase: string;
  /** All decisions on the run — we filter to this phase. */
  decisions: Decision[];
  /**
   * Local edit buffer (per-row staged answer overrides). Pass alongside
   * `onEdit` + `onRevert` to enable inline edit affordance. When any of the
   * three are omitted, the panel renders read-only (legacy behavior).
   */
  editBuffer?: readonly EditOp[];
  /**
   * Durable overrides from `<opp>/inputs/decision-overrides.yaml`, keyed
   * by row id. Per-row precedence: pending buffer edit > saved override >
   * committed run override > AI default.
   */
  savedOverrides?: Record<string, SavedDecisionOverride>;
  /**
   * Commit an override for a row. `new_answer` may be a new option not in
   * `decision.options_considered` — the write path appends it to options
   * before setting override. `override_reasoning` is optional free text.
   */
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}

/**
 * Per-phase rollup of the decisions log.
 *
 * Each row is a load-bearing question + the AI default + alternatives
 * considered + a status (ai-default | overridden). Rows carry a
 * ``phase`` tag so we can group them per phase here.
 */
const STATUS_RANK: Record<Decision["status"], number> = {
  overridden: 0,
  "ai-default": 1,
};

export function DecisionsPanel({
  phase,
  decisions,
  editBuffer,
  savedOverrides,
  onEdit,
  onRevert,
}: Props) {
  const phaseRows = useMemo(
    () =>
      decisions
        .filter((d) => d.phase === phase)
        .map((d, i) => ({ d, i }))
        .sort((a, b) => {
          const r = STATUS_RANK[a.d.status] - STATUS_RANK[b.d.status];
          return r !== 0 ? r : a.i - b.i;
        })
        .map((x) => x.d),
    [decisions, phase],
  );

  if (phaseRows.length === 0) return null;

  const overridden = phaseRows.filter((d) => d.status === "overridden").length;

  return (
    <DecisionsPanelInner
      phaseRows={phaseRows}
      overridden={overridden}
      editBuffer={editBuffer}
      savedOverrides={savedOverrides}
      onEdit={onEdit}
      onRevert={onRevert}
    />
  );
}

function DecisionsPanelInner({
  phaseRows,
  overridden,
  editBuffer,
  savedOverrides,
  onEdit,
  onRevert,
}: {
  phaseRows: Decision[];
  overridden: number;
  editBuffer?: readonly EditOp[];
  savedOverrides?: Record<string, SavedDecisionOverride>;
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="mt-3 rounded-lg border border-border bg-card/30">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center gap-2.5 px-4 py-2.5 text-left",
          expanded ? "border-b border-border/70" : "",
        )}
      >
        <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
          <HelpCircle className="h-3 w-3" />
          Decisions
        </span>
        <span className="text-xs font-medium text-foreground">{phaseRows.length}</span>
        <span className="ml-auto flex items-center gap-2 text-[11px]">
          {overridden > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-sky-400">
              {overridden} overridden
            </span>
          )}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            expanded ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {expanded && (
        <ul className="divide-y divide-border/60">
          {phaseRows.map((d) => (
            <li key={d.id}>
              <DecisionRow
                decision={d}
                editBuffer={editBuffer}
                savedOverride={savedOverrides?.[d.id]}
                onEdit={onEdit}
                onRevert={onRevert}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function DecisionRow({
  decision,
  editBuffer,
  savedOverride,
  onEdit,
  onRevert,
}: {
  decision: Decision;
  editBuffer?: readonly EditOp[];
  savedOverride?: SavedDecisionOverride;
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [rowOpen, setRowOpen] = useState(false);

  const pendingEdit = editBuffer?.find((e) => e.row_id === decision.id);
  const committedAnswer = decision.override || decision.ai_default;
  // Precedence: pending buffer edit > saved override (durable file in
  // inputs/) > committed run override > AI default.
  const effectiveValue =
    pendingEdit?.new_answer ?? savedOverride?.override ?? committedAnswer;
  const effectiveReason =
    pendingEdit?.override_reasoning ??
    (savedOverride ? (savedOverride.reasoning ?? "") : (decision.override_reasoning ?? ""));
  const isEdited = !!pendingEdit;
  // "Overridden" = effective answer differs from AI default (whether from a
  // committed override on the run, or a pending edit). Colors the row
  // background so it reads at a glance against the ai-default majority.
  const isOverridden = effectiveValue !== decision.ai_default;
  const canEdit = !!onEdit;

  // Status chip: three-state derivation from the EFFECTIVE state, not a
  // passthrough of `decision.status` — otherwise the chip keeps reading
  // ai-default while a staged pick already highlights a different pill.
  //   ai-default (emerald)          — effective value equals ai_default, no reasoning
  //   overridden (sky)              — committed on the run (or saved to Drive)
  //   overridden · pending (violet) — staged in the shared buffer only
  const effectiveIsAiDefault =
    effectiveValue === decision.ai_default && !effectiveReason;
  const chipLabel = effectiveIsAiDefault
    ? "ai-default"
    : isEdited
      ? "overridden · pending"
      : "overridden";
  const tone = effectiveIsAiDefault
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
    : isEdited
      ? "border-violet-500/40 bg-violet-500/10 text-violet-400"
      : "border-sky-500/40 bg-sky-500/10 text-sky-400";

  // Row-level color flip: visible sky-tint on overridden rows (committed
  // or pending) so the user can scan a long list and spot the humans'
  // choices vs the AI-default majority. Pending-edit rows additionally
  // get a violet left-border to call out "not yet committed".
  const rowTint = isOverridden
    ? isEdited
      ? "border-l-2 border-violet-500/60 bg-sky-500/15"
      : "bg-sky-500/15"
    : "";

  return (
    <div className={rowTint}>
      <button
        type="button"
        onClick={() => setRowOpen((v) => !v)}
        aria-expanded={rowOpen}
        className="flex w-full items-center gap-3 px-4 py-2 text-left text-xs hover:bg-accent/40"
      >
        <span className="font-mono text-[10px] text-muted-foreground/70">{decision.id}</span>
        <span className="flex-1 truncate text-foreground">{decision.question}</span>
        <span className="hidden truncate text-[11px] text-muted-foreground sm:block sm:max-w-[260px]">
          → <span className="font-medium text-foreground">{effectiveValue}</span>
        </span>
        {isEdited && (
          <span
            className="shrink-0 rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[10px] font-semibold text-violet-400"
            aria-label="this row has a pending edit"
          >
            edited{pendingEdit?.editor_name ? ` by ${pendingEdit.editor_name}` : ""}
          </span>
        )}
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
            rowOpen ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {rowOpen && (
        <div className="animate-in fade-in slide-in-from-top-1 border-t border-border/40 bg-background/30 px-4 pb-3 pt-3 text-[11px] duration-150">
          <div className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-2">
            <DecisionDetailFields
              decision={decision}
              effectiveValue={effectiveValue}
              effectiveReason={effectiveReason}
              optionsLabel={canEdit ? "Pick option" : "Options"}
              optionsSlot={
                canEdit ? (
                  // The SAME editor the public run summary renders — see
                  // its module docstring. `immediate` because the
                  // Workbench stages into the shared multi-player buffer
                  // and a member saves to Drive explicitly, so nothing a
                  // pill click does is durable yet.
                  <DecisionAnswerEditor
                    decision={decision}
                    effectiveValue={effectiveValue}
                    effectiveReason={effectiveReason}
                    commitMode="immediate"
                    dense
                    onCommit={(value, reasoning) =>
                      onEdit?.(decision.id, value, reasoning || undefined)
                    }
                    onRevert={onRevert ? () => onRevert(decision.id) : undefined}
                    // A pending BUFFER edit is what Revert undoes here; a
                    // saved override is undone through the history block.
                    revertable={isEdited}
                  />
                ) : undefined
              }
            />
          </div>
          {savedOverride && (
            <DecisionHistory
              current={savedOverride}
              history={savedOverride.history ?? []}
              onRestore={
                onEdit
                  ? (value, reasoning) =>
                      onEdit(decision.id, value, reasoning || undefined)
                  : undefined
              }
            />
          )}
        </div>
      )}
    </div>
  );
}
