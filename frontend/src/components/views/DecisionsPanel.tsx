import { useMemo, useState } from "react";
import { HelpCircle } from "lucide-react";

import type { Decision, SavedDecisionOverride } from "@/api/types.ws";
import { DecisionAnswerEditor } from "@/components/opps/decisions/DecisionAnswerEditor";
import { DecisionHistory } from "@/components/opps/decisions/DecisionHistory";
import { DecisionRow as SharedDecisionRow } from "@/components/opps/decisions/DecisionRow";
import { DecisionSection } from "@/components/opps/decisions/DecisionSection";
import { SupersededVersions } from "@/components/opps/decisions/SupersededVersions";

import type { EditOp } from "./decisions/decisionsReducer";
import { splitSuperseded } from "./decisions/supersession";

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
  // Superseded rows are history, not choices: split them out over the WHOLE
  // log (a correction can point across phases), then keep this phase's live
  // rows — each carrying the versions it replaced — and its retired rows.
  const { phaseRows, earlierBy, retired } = useMemo(() => {
    const split = splitSuperseded(decisions);
    return {
      phaseRows: split.live
        .filter((d) => d.phase === phase)
        .map((d, i) => ({ d, i }))
        .sort((a, b) => {
          const r = STATUS_RANK[a.d.status] - STATUS_RANK[b.d.status];
          return r !== 0 ? r : a.i - b.i;
        })
        .map((x) => x.d),
      earlierBy: split.earlierBy,
      retired: split.retired.filter((d) => d.phase === phase),
    };
  }, [decisions, phase]);

  if (phaseRows.length === 0 && retired.length === 0) return null;

  const overridden = phaseRows.filter((d) => d.status === "overridden").length;

  return (
    <DecisionsPanelInner
      phaseRows={phaseRows}
      earlierBy={earlierBy}
      retired={retired}
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
  earlierBy,
  retired,
  overridden,
  editBuffer,
  savedOverrides,
  onEdit,
  onRevert,
}: {
  phaseRows: Decision[];
  earlierBy: Map<string, Decision[]>;
  retired: Decision[];
  overridden: number;
  editBuffer?: readonly EditOp[];
  savedOverrides?: Record<string, SavedDecisionOverride>;
  onEdit?: (row_id: string, new_answer: string, override_reasoning?: string) => void;
  onRevert?: (row_id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <DecisionSection
      open={expanded}
      onToggle={() => setExpanded((v) => !v)}
      className="mt-3"
      lead={
        <>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
            <HelpCircle className="h-3 w-3" />
            Decisions
          </span>
          <span className="text-xs font-medium text-foreground">{phaseRows.length}</span>
        </>
      }
      chips={
        overridden > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-sky-400">
            {overridden} overridden
          </span>
        )
      }
    >
      {phaseRows.map((d) => (
        <li key={d.id}>
          <DecisionRow
            decision={d}
            earlier={earlierBy.get(d.id) ?? []}
            editBuffer={editBuffer}
            savedOverride={savedOverrides?.[d.id]}
            onEdit={onEdit}
            onRevert={onRevert}
          />
        </li>
      ))}
      {retired.length > 0 && (
        <li>
          <SupersededVersions
            earlier={retired}
            label={`${retired.length} retired ${retired.length === 1 ? "decision" : "decisions"} (no longer in force)`}
          />
        </li>
      )}
    </DecisionSection>
  );
}

function DecisionRow({
  decision,
  earlier,
  editBuffer,
  savedOverride,
  onEdit,
  onRevert,
}: {
  decision: Decision;
  /** Rows this run replaced with this one, nearest first. */
  earlier: readonly Decision[];
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
  const canEdit = !!onEdit;

  return (
    <SharedDecisionRow
      decision={decision}
      effectiveValue={effectiveValue}
      effectiveReason={effectiveReason}
      open={rowOpen}
      onToggle={() => setRowOpen((v) => !v)}
      pending={isEdited}
      optionsLabel={canEdit ? "Pick option" : "Options"}
      badges={
        isEdited || earlier.length > 0 ? (
          <>
            {earlier.length > 0 && (
              <span
                className="shrink-0 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground"
                title="This run replaced an earlier version of this decision — open the row to see it"
              >
                revised
              </span>
            )}
            {isEdited && (
              <span
                className="shrink-0 rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[10px] font-semibold text-violet-400"
                aria-label="this row has a pending edit"
              >
                edited{pendingEdit?.editor_name ? ` by ${pendingEdit.editor_name}` : ""}
              </span>
            )}
          </>
        ) : undefined
      }
      optionsSlot={
        canEdit ? (
          // The SAME editor the public run summary renders — see its
          // module docstring. `immediate` because a member is
          // authenticated, so there is never a name to collect first.
          <DecisionAnswerEditor
            decision={decision}
            effectiveValue={effectiveValue}
            effectiveReason={effectiveReason}
            commitMode="immediate"
            voice="console"
            dense
            onCommit={(value, reasoning) =>
              onEdit?.(decision.id, value, reasoning || undefined)
            }
            onRevert={onRevert ? () => onRevert(decision.id) : undefined}
            // A pending BUFFER edit is what Revert undoes here; a saved
            // override is undone through the history block.
            revertable={isEdited}
          />
        ) : undefined
      }
    >
      {savedOverride && (
        <DecisionHistory
          current={savedOverride}
          history={savedOverride.history ?? []}
          onRestore={
            onEdit
              ? (value, reasoning) => onEdit(decision.id, value, reasoning || undefined)
              : undefined
          }
        />
      )}
      <SupersededVersions live={decision} earlier={earlier} />
    </SharedDecisionRow>
  );
}
