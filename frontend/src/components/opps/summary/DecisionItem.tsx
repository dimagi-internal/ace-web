import { useState } from "react";
import { MessageSquare } from "lucide-react";

import type {
  DecisionReaction,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionHistory } from "@/components/opps/decisions/DecisionHistory";
import { DecisionRow } from "@/components/opps/decisions/DecisionRow";
import {
  DecisionReactions,
  type ReactionSubmit,
} from "@/components/opps/summary/DecisionReactions";
import { AnswerChoice } from "@/components/opps/summary/AnswerChoice";
import { CannotWrite } from "@/components/opps/summary/SignInToEdit";

export interface DecisionEditSubmit {
  value: string;
  reasoning?: string;
  /** A CONFIRMATION of `value` (the answer in force), not a change. */
  confirm?: boolean;
}

/**
 * One decision row on the run summary: the question, the answer in force,
 * and — for a signed-in workspace member — Confirm, the editor that
 * changes it, and the discussion under it.
 *
 * ONE row design everywhere (Jonathan, 2026-10-03): this is the shared
 * `DecisionRow` the Workbench renders, at the Workbench's type scale. A
 * row ACE recommends confirming before launch is the SAME row — the
 * shared row draws its "Confirm before launch" marker and `confirm_reason`
 * from `review_ask` — not a separate card.
 *
 * Who may write is decided server-side (401 / 403 for anyone but a
 * member); `canWrite` only decides what this row OFFERS. A non-member reads
 * the row, its options and its discussion, and gets "Sign in to edit" in
 * place of the controls. There is no anonymous identity any more, so a
 * pick commits as it happens, exactly as in the Workbench.
 *
 * Confirm records "keep the answer in force" distinctly from a change
 * (`confirm: true` → `confirmed: true` on the override row).
 */
export function DecisionItem({
  decision,
  open,
  onToggle,
  reactions,
  edit,
  canWrite,
  readOnlyMember = false,
  onReact,
  onEdit,
  tags,
  lineageSlot,
}: {
  decision: ReviewDecision;
  open: boolean;
  onToggle: () => void;
  reactions: DecisionReaction[];
  edit?: PublicDecisionEdit;
  /** May confirm, change and comment (`decisions.write`: editor and above). */
  canWrite: boolean;
  /** Signed in as a member whose role may not write (a `viewer`). */
  readOnlyMember?: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
  /** Extra header chips from the caller (e.g. "internal"). */
  tags?: React.ReactNode;
  /** The decision's history across runs, drawn in the expanded detail. */
  lineageSlot?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Precedence: a saved human answer > the run's committed override > the
  // AI default. Same order the Workbench panel uses.
  const answer = edit?.override || decision.override || decision.ai_default;
  const reason = edit ? edit.reasoning : (decision.override_reasoning ?? "");
  const confirmed = !!edit?.confirmed;
  const humanChanged = !!edit && !edit.is_revert && !confirmed;

  /** Returns false when the write did not land — see `onCommit`'s contract. */
  async function write(body: DecisionEditSubmit): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await onEdit(decision.id, body);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that change.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  const commit = (value: string, reasoning: string) =>
    write({ value, reasoning: reasoning || undefined });

  return (
    <DecisionRow
      decision={decision}
      effectiveValue={answer}
      effectiveReason={reason}
      open={open}
      onToggle={onToggle}
      anchorId={`decision-${decision.id}`}
      optionsLabel={canWrite ? "Your answer" : "Options"}
      statusChip={false}
      showAskIds={canWrite}
      askMarkers={false}
      compactDetail
      badges={
        <>
          {tags}
          {reactions.length > 0 && (
            <span
              className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-muted-foreground"
              title={`${reactions.length} comment${reactions.length === 1 ? "" : "s"}`}
            >
              <MessageSquare size={12} />
              {reactions.length}
            </span>
          )}
          {confirmed && (
            <span
              className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-400"
              title={`confirmed${edit?.decided_by_name ? ` by ${edit.decided_by_name}` : ""}`}
            >
              {edit?.decided_by_name ? `confirmed by ${edit.decided_by_name}` : "confirmed"}
            </span>
          )}
          {(humanChanged || (!confirmed && decision.status === "overridden")) && (
            <span
              className="shrink-0 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold text-sky-400"
              title={
                edit?.decided_by_name
                  ? `changed by ${edit.decided_by_name}`
                  : "changed by a reviewer"
              }
            >
              {edit?.decided_by_name
                ? `changed by ${edit.decided_by_name}`
                : "reviewer changed"}
            </span>
          )}
        </>
      }
      optionsSlot={
        canWrite ? (
          <AnswerChoice
            decision={decision}
            answer={answer}
            reason={reason}
            confirmed={confirmed}
            confirmedBy={edit?.decided_by_name}
            busy={busy}
            error={error}
            onConfirm={() => write({ value: answer, confirm: true })}
            onCommit={commit}
          />
        ) : undefined
      }
    >
      {!canWrite && (
        <div className="mt-3">
          <CannotWrite readOnlyMember={readOnlyMember}>Sign in to edit</CannotWrite>
        </div>
      )}

      {lineageSlot}

      {edit && (
        <DecisionHistory
          current={edit}
          history={edit.history}
          onRestore={canWrite ? (value, reasoning) => commit(value, reasoning) : undefined}
        />
      )}

      <DecisionReactions
        decisionId={decision.id}
        reactions={reactions}
        onSubmit={onReact}
        canWrite={canWrite}
        readOnlyMember={readOnlyMember}
        contested={decision.evidence_basis === "conflicting"}
      />
    </DecisionRow>
  );
}
