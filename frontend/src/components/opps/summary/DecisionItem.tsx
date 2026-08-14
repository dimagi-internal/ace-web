import { useState } from "react";
import { MessageSquare } from "lucide-react";

import type {
  DecisionReaction,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionAnswerEditor } from "@/components/opps/decisions/DecisionAnswerEditor";
import { DecisionHistory } from "@/components/opps/decisions/DecisionHistory";
import { DecisionRow } from "@/components/opps/decisions/DecisionRow";
import { ReviewerIdentityFields } from "@/components/opps/decisions/ReviewerIdentityFields";
import {
  rememberIdentity,
  type ReviewerIdentity,
} from "@/components/opps/decisions/reviewerIdentity";
import {
  DecisionReactions,
  type ReactionSubmit,
} from "@/components/opps/summary/DecisionReactions";

export interface DecisionEditSubmit {
  value: string;
  reasoning?: string;
  reviewer?: string;
  reviewer_email?: string;
}

/**
 * One decision row on the public review surface: the question, the answer
 * in force, the editor that changes it, and the discussion under it.
 *
 * ## Why editing here is click-and-done, like the Workbench
 *
 * The Workbench commits a pill click as it happens. This surface shipped
 * with a confirm step on EVERY row, justified as "asking for a name
 * before someone can even click a pill would be the barrier this surface
 * exists to remove". That argument is about the FIRST edit of a session,
 * when nobody has told us who they are yet. It never justified a Save
 * button on the fortieth row: by then the name is known (typed once and
 * remembered in `reviewerIdentity`, or resolved from the session for a
 * signed-in member), so the barrier was removed at the start and
 * reintroduced on every row after it.
 *
 * So `commitMode` follows identity, not surface: `confirm` only while we
 * genuinely don't know who is editing, `immediate` the moment we do. A
 * signed-in member never sees a confirm step at all.
 *
 * Everything else IS the Workbench: the row itself is the shared
 * `DecisionRow`, at the Workbench's own type scale (`dense`), with the
 * Workbench's status chips and overridden tint. Jonathan compared the two
 * surfaces and settled it — *"the workbench is what I remember and what I
 * want to replicate for the decisions"* (2026-08-14) — so this page
 * replicates rather than reinterprets, and only the two FORCED
 * differences remain:
 *
 * 1. identity for an anonymous editor, which the Workbench resolves from
 *    the session and this surface cannot;
 * 2. `voice="partner"` — "override reason" is Workbench vocabulary a
 *    partner has never met. Field `aria-label`s stay identical.
 *
 * The extra blocks this surface adds (attribution badge, comment count,
 * the discussion thread) ride the shared row's `badges` / `children`
 * slots rather than forking it.
 */
export function DecisionItem({
  decision,
  open,
  onToggle,
  reactions,
  edit,
  identity,
  setIdentity,
  viewerIsMember,
  identityKnown,
  canSubmit,
  onReact,
  onEdit,
}: {
  decision: ReviewDecision;
  open: boolean;
  onToggle: () => void;
  reactions: DecisionReaction[];
  edit?: PublicDecisionEdit;
  identity: ReviewerIdentity;
  setIdentity: (next: ReviewerIdentity) => void;
  viewerIsMember: boolean;
  /** Do we already know who is editing? Drives confirm vs immediate. */
  identityKnown: boolean;
  /**
   * Is there a usable name RIGHT NOW — including one being typed into the
   * confirm block. Distinct from `identityKnown`, which only moves on a
   * successful write; a keystroke must enable Save without yanking the
   * confirm step (and the Save button) out from under the typist.
   */
  canSubmit: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Precedence: a saved human answer > the run's committed override > the
  // AI default. Same order the Workbench panel uses.
  const answer = edit?.override || decision.override || decision.ai_default;
  const reason = edit ? edit.reasoning : (decision.override_reasoning ?? "");
  const humanChanged = !!edit && !edit.is_revert;

  /** Returns false when the change did not save — see `onCommit`'s contract. */
  async function commit(value: string, reasoning: string): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await onEdit(decision.id, {
        value,
        reasoning: reasoning || undefined,
        ...(viewerIsMember
          ? {}
          : {
              reviewer: identity.name.trim(),
              reviewer_email: identity.email.trim() || undefined,
            }),
      });
      if (!viewerIsMember) rememberIdentity(identity);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that change.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <DecisionRow
      decision={decision}
      effectiveValue={answer}
      effectiveReason={reason}
      open={open}
      onToggle={onToggle}
      anchorId={`decision-${decision.id}`}
      optionsLabel="Pick option"
      badges={
        <>
          {reactions.length > 0 && (
            <span
              className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-muted-foreground"
              title={`${reactions.length} comment${reactions.length === 1 ? "" : "s"}`}
            >
              <MessageSquare size={12} />
              {reactions.length}
            </span>
          )}
          {(humanChanged || decision.status === "overridden") && (
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
        <DecisionAnswerEditor
          decision={decision}
          effectiveValue={answer}
          effectiveReason={reason}
          voice="partner"
          commitMode={identityKnown ? "immediate" : "confirm"}
          dense
          onCommit={commit}
          onRevert={
            answer !== decision.ai_default
              ? () => commit(decision.ai_default, "")
              : undefined
          }
          canSubmit={canSubmit}
          busy={busy}
          error={error}
          identitySlot={
            viewerIsMember || identityKnown ? null : (
              <ReviewerIdentityFields identity={identity} onChange={setIdentity} />
            )
          }
        />
      }
    >
      {edit && (
        <DecisionHistory
          current={edit}
          history={edit.history}
          onRestore={(value, reasoning) => commit(value, reasoning)}
        />
      )}

      <DecisionReactions
        decisionId={decision.id}
        reactions={reactions}
        onSubmit={onReact}
        identity={identity}
        onIdentityChange={setIdentity}
        hideIdentityFields={viewerIsMember}
        prompt={
          decision.evidence_basis === "conflicting"
            ? "Not sure enough to change it? Say what you'd want to know."
            : undefined
        }
      />
    </DecisionRow>
  );
}
