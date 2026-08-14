import { useMemo, useState } from "react";
import { ChevronRight, MessageSquare } from "lucide-react";

import type {
  DecisionReaction,
  OppSummaryPayload,
  PublicDecisionEdit,
  ReviewDecision,
} from "@/api/oppSummary";
import { DecisionAnswerEditor } from "@/components/opps/decisions/DecisionAnswerEditor";
import { DecisionDetailFields } from "@/components/opps/decisions/DecisionDetailFields";
import { DecisionHistory } from "@/components/opps/decisions/DecisionHistory";
import { EvidenceBadge } from "@/components/opps/decisions/EvidenceBadge";
import { ReviewerIdentityFields } from "@/components/opps/decisions/ReviewerIdentityFields";
import {
  MIN_NAME_CHARS,
  rememberIdentity,
  rememberedIdentity,
  type ReviewerIdentity,
} from "@/components/opps/decisions/reviewerIdentity";
import {
  DecisionReactions,
  type ReactionSubmit,
} from "@/components/opps/summary/DecisionReactions";
import { cn } from "@/lib/utils";

/**
 * The public face of the run's decisions log — read, change, or discuss.
 *
 * A 24-page PDD is a bad instrument for eliciting decisions: people skim
 * prose and agree with all of it. Every load-bearing default is already a
 * typed row (question, picked value, alternatives, reasoning, evidence
 * basis), so this renders those rows and gets a partner engaging with
 * specific calls instead of reading a design document end to end.
 *
 * Rows are **editable in place by anyone with the link** — no account, no
 * proposal state, no promotion step, and a Dimagi member's edit is the
 * same act as a partner's (Jonathan, 2026-08-14). The editor is the
 * Workbench's own `DecisionAnswerEditor` and the write lands in the
 * Workbench's own store; what differs is only how identity is resolved.
 *
 * ## Editing and commenting both exist, and are different acts
 *
 * An **edit** asserts a value: it changes what the next run builds from,
 * and lands in `inputs/decision-overrides.yaml`. A **comment** is
 * discussion — a question, a doubt, context we're missing — and lands in
 * the feedback ledger, carrying the `Feedback-Ref` stamp downstream
 * changes cite. Collapsing them either way costs something real:
 * comments-only was the promotion gate this design removed, and
 * edits-only would force anyone with a *question* to assert an *answer*.
 * So each row shows both, visually separated: a bordered "the answer"
 * block, and a "discussion" thread under it.
 *
 * Ordering is the argument. `conflicting` (ACE had to resolve sources
 * that disagreed) and rows a human already changed lead, expanded,
 * because those are the calls an outside reader is best placed to
 * correct.
 */
export interface DecisionEditSubmit {
  value: string;
  reasoning?: string;
  reviewer?: string;
  reviewer_email?: string;
}

function isFlagged(d: ReviewDecision, edit?: PublicDecisionEdit): boolean {
  return (
    d.evidence_basis === "conflicting" ||
    d.status === "overridden" ||
    (!!edit && !edit.is_revert)
  );
}

export function DecisionsReview({
  decisions,
  reactions,
  edits,
  viewerIsMember,
  onReact,
  onEdit,
}: {
  decisions: NonNullable<OppSummaryPayload["decisions"]>;
  /** Reactions already collected, keyed by decision id. */
  reactions: Record<string, DecisionReaction[]>;
  /** Human-set answers, keyed by decision id. */
  edits: Record<string, PublicDecisionEdit>;
  /** Signed-in viewers are never asked to type a name. */
  viewerIsMember: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
}) {
  const [showAll, setShowAll] = useState(false);
  const [identity, setIdentity] = useState<ReviewerIdentity>(() =>
    rememberedIdentity(),
  );
  const { counts, rows, total } = decisions;

  const changed = useMemo(
    () => rows.filter((d) => edits[d.id] && !edits[d.id].is_revert).length,
    [rows, edits],
  );
  const flagged = useMemo(
    () => rows.filter((d) => isFlagged(d, edits[d.id])),
    [rows, edits],
  );
  const groups = useMemo(() => {
    const byPhase = new Map<string, { label: string; ordinal: number; rows: ReviewDecision[] }>();
    for (const d of rows) {
      const key = d.phase_raw || d.phase;
      const g = byPhase.get(key);
      if (g) g.rows.push(d);
      else byPhase.set(key, { label: d.phase_label, ordinal: d.phase_ordinal, rows: [d] });
    }
    return [...byPhase.values()].sort((a, b) => a.ordinal - b.ordinal);
  }, [rows]);

  const itemProps = {
    reactions,
    edits,
    identity,
    setIdentity,
    viewerIsMember,
    onReact,
    onEdit,
  };

  return (
    <div>
      <p className="text-[0.975rem] leading-[1.7] text-muted-foreground">
        ACE made <span className="text-foreground">{total}</span> load-bearing calls building
        this run. Each one records what it picked, what else was on the table, and why —
        and <span className="text-foreground">you can change any of them here</span>. What
        you change is what the next run builds from.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        <Count n={counts.stated} label="stated in a source" />
        <Count n={counts.inferred} label="inferred beyond it" />
        <Count n={counts.conflicting} label="resolved a conflict" tone="amber" />
        <Count n={counts.overridden + changed} label="changed by a human" tone="sky" />
      </div>

      {flagged.length > 0 && (
        <div className="mt-7">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-foreground">
            Worth your eye first
          </h3>
          <p className="mt-1.5 text-sm leading-[1.6] text-muted-foreground">
            Where the source material disagreed with itself and ACE picked a side, or
            where someone has already changed the answer. If we picked wrong, this is the
            cheapest place to fix it.
          </p>
          <ul className="mt-3 divide-y divide-border border-y border-border">
            {flagged.map((d) => (
              <li key={d.id}>
                <DecisionItem decision={d} defaultOpen {...itemProps} />
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        onClick={() => setShowAll((v) => !v)}
        aria-expanded={showAll}
        className="group mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-foreground underline-offset-4 hover:underline"
      >
        <ChevronRight
          size={14}
          className={cn("transition-transform", showAll && "rotate-90")}
        />
        {showAll ? "Hide" : `Show all ${total}`} decisions
      </button>

      {showAll && (
        <div className="mt-5 space-y-7">
          {groups.map((g) => (
            <div key={g.label + g.ordinal}>
              <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                {g.label}
                <span className="ml-2 text-muted-foreground/60">{g.rows.length}</span>
              </h3>
              <ul className="mt-2 divide-y divide-border border-y border-border">
                {g.rows.map((d) => (
                  <li key={d.id}>
                    <DecisionItem decision={d} {...itemProps} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Count({
  n,
  label,
  tone,
}: {
  n: number;
  label: string;
  tone?: "amber" | "sky";
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span
        className={cn(
          "text-sm font-medium tabular-nums",
          n === 0
            ? "text-muted-foreground/50"
            : tone === "amber"
              ? "text-amber-400"
              : tone === "sky"
                ? "text-sky-400"
                : "text-foreground",
        )}
      >
        {n}
      </span>
      <span className={n === 0 ? "text-muted-foreground/50" : undefined}>{label}</span>
    </span>
  );
}

function DecisionItem({
  decision,
  defaultOpen = false,
  reactions,
  edits,
  identity,
  setIdentity,
  viewerIsMember,
  onReact,
  onEdit,
}: {
  decision: ReviewDecision;
  defaultOpen?: boolean;
  reactions: Record<string, DecisionReaction[]>;
  edits: Record<string, PublicDecisionEdit>;
  identity: ReviewerIdentity;
  setIdentity: (next: ReviewerIdentity) => void;
  viewerIsMember: boolean;
  onReact: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  onEdit: (decisionId: string, body: DecisionEditSubmit) => Promise<void>;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rowReactions = reactions[decision.id] ?? [];
  const edit = edits[decision.id];
  // Precedence: a saved human answer > the run's committed override > the
  // AI default. Same order the Workbench panel uses.
  const answer = edit?.override || decision.override || decision.ai_default;
  const reason = edit ? edit.reasoning : (decision.override_reasoning ?? "");
  const humanChanged = !!edit && !edit.is_revert;

  const canSubmit = viewerIsMember || identity.name.trim().length >= MIN_NAME_CHARS;

  async function commit(value: string, reasoning: string) {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that change.");
      throw err;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group flex w-full items-baseline gap-3 py-3 text-left hover:bg-muted/30"
      >
        <ChevronRight
          size={13}
          className={cn(
            "mt-1 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90 text-foreground",
          )}
        />
        <span className="flex-1 text-[0.975rem] leading-[1.5] text-foreground">
          {decision.question}
          <span className="mt-1 block text-sm text-muted-foreground">
            <span aria-hidden>→ </span>
            <span className="font-medium text-foreground/90">{answer}</span>
          </span>
        </span>
        {rowReactions.length > 0 && (
          <span
            className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-muted-foreground"
            title={`${rowReactions.length} comment${rowReactions.length === 1 ? "" : "s"}`}
          >
            <MessageSquare size={12} />
            {rowReactions.length}
          </span>
        )}
        {(humanChanged || decision.status === "overridden") && (
          <span
            className="shrink-0 rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-sky-400"
            title={
              edit?.decided_by_name
                ? `changed by ${edit.decided_by_name}`
                : "changed by a reviewer"
            }
          >
            {edit?.decided_by_name ? `changed by ${edit.decided_by_name}` : "reviewer changed"}
          </span>
        )}
        <EvidenceBadge basis={decision.evidence_basis} />
      </button>
      {open && (
        <div className="pb-5 pl-6 pr-1">
          <div className="grid grid-cols-[130px_1fr] gap-x-5 gap-y-2.5 text-[13px] leading-[1.6]">
            <DecisionDetailFields
              decision={decision}
              effectiveValue={answer}
              effectiveReason={reason}
              optionsLabel="Change the answer"
              optionsSlot={
                <DecisionAnswerEditor
                  decision={decision}
                  effectiveValue={answer}
                  effectiveReason={reason}
                  commitMode="confirm"
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
                    viewerIsMember ? null : (
                      <ReviewerIdentityFields
                        identity={identity}
                        onChange={setIdentity}
                      />
                    )
                  }
                />
              }
            />
          </div>

          {edit && (
            <DecisionHistory
              current={edit}
              history={edit.history}
              onRestore={(value, reasoning) => commit(value, reasoning)}
            />
          )}

          <DecisionReactions
            decisionId={decision.id}
            reactions={rowReactions}
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
        </div>
      )}
    </div>
  );
}
