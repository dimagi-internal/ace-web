import { useState } from "react";
import { CheckCircle2, MessageSquare } from "lucide-react";

import type {
  DecisionReaction,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionAnswerEditor } from "@/components/opps/decisions/DecisionAnswerEditor";
import { DecisionHistory } from "@/components/opps/decisions/DecisionHistory";
import { DecisionRow } from "@/components/opps/decisions/DecisionRow";
import { decisionDisplay } from "@/components/opps/decisions/decisionDisplay";
import {
  DecisionReactions,
  type ReactionSubmit,
} from "@/components/opps/summary/DecisionReactions";
import { SignInToEdit } from "@/components/opps/summary/SignInToEdit";

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
  onReact,
  onEdit,
  tags,
}: {
  decision: ReviewDecision;
  open: boolean;
  onToggle: () => void;
  reactions: DecisionReaction[];
  edit?: PublicDecisionEdit;
  /** A signed-in member of this workspace. */
  canWrite: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
  /** Extra header chips from the caller (e.g. "internal"). */
  tags?: React.ReactNode;
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
      optionsLabel={canWrite ? "Confirm or change" : "Options"}
      statusChip={false}
      showAskIds={canWrite}
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
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              {confirmed ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 size={14} aria-hidden />
                  Confirmed{edit?.decided_by_name ? ` by ${edit.decided_by_name}` : ""}
                </span>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void write({ value: answer, confirm: true })}
                  className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label={`Confirm: ${decisionDisplay(decision, answer).value || answer}`}
                >
                  {busy ? "Saving…" : "Confirm"}
                </button>
              )}
              <span className="text-muted-foreground">or change it — pick another option:</span>
            </div>
            <DecisionAnswerEditor
              decision={decision}
              effectiveValue={answer}
              effectiveReason={reason}
              voice="partner"
              dense
              onCommit={commit}
              onRevert={
                answer !== decision.ai_default ? () => commit(decision.ai_default, "") : undefined
              }
              busy={busy}
              error={error}
            />
          </div>
        ) : undefined
      }
    >
      {!canWrite && (
        <div className="mt-3">
          <SignInToEdit />
        </div>
      )}

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
        prompt={
          decision.evidence_basis === "conflicting"
            ? "Not sure enough to change it? Say what you'd want to know."
            : undefined
        }
      />
    </DecisionRow>
  );
}
