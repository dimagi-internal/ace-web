import { useState } from "react";
import { MessageSquarePlus } from "lucide-react";

import type { DecisionReaction } from "@/api/oppSummary";
import { ReviewerIdentityFields } from "@/components/opps/decisions/ReviewerIdentityFields";
import {
  MIN_NAME_CHARS,
  rememberIdentity,
  type ReviewerIdentity,
} from "@/components/opps/decisions/reviewerIdentity";
import { cn } from "@/lib/utils";

/**
 * The response affordance — the point of the whole review surface.
 *
 * #708 put 42 decision rows in front of a partner and gave them nothing
 * to do with any of them, which reproduces the failure the decisions log
 * exists to fix (skim, agree with everything) in a nicer shape. This is
 * the per-ROW reply: reacting to a specific call costs one sentence
 * instead of a document review.
 *
 * A comment is NOT an edit, and both exist on every row. An edit
 * asserts a value and changes what the next run builds from; a comment
 * is discussion — a question, a doubt, context we're missing — and lands
 * in the feedback ledger with the `Feedback-Ref` stamp downstream
 * changes cite. Making commenting the only option was the promotion gate
 * this design removed; making editing the only option would force
 * anyone with a *question* to assert an *answer*.
 *
 * Identity: the name is REQUIRED and self-reported for an anonymous
 * visitor, and never asked of a signed-in one. It is shared with the
 * answer editor on the same row (`identity` / `onIdentityChange`) and
 * remembered locally, so a partner working through several rows types it
 * once. The stored record says the name is self-reported rather than
 * pretending otherwise.
 */

function formatWhen(iso: string): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.valueOf())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export interface ReactionSubmit {
  reviewer: string;
  reviewer_email?: string;
  comment: string;
}

export function DecisionReactions({
  decisionId,
  reactions,
  onSubmit,
  identity,
  onIdentityChange,
  hideIdentityFields = false,
  prompt,
}: {
  decisionId: string;
  reactions: DecisionReaction[];
  onSubmit: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  /** Shared with the answer editor — one name typed once, per visit. */
  identity: ReviewerIdentity;
  onIdentityChange: (next: ReviewerIdentity) => void;
  /** Signed in ⇒ never anonymous: don't ask a member for their name. */
  hideIdentityFields?: boolean;
  /** Row-specific invitation — a conflicting row deserves a sharper one. */
  prompt?: string;
}) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(decisionId, {
        reviewer: identity.name.trim(),
        reviewer_email: identity.email.trim() || undefined,
        comment: comment.trim(),
      });
      rememberIdentity(identity);
      setComment("");
      setOpen(false);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that.");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit =
    (hideIdentityFields || identity.name.trim().length >= MIN_NAME_CHARS) &&
    comment.trim().length >= 3 &&
    !busy;

  return (
    <div className="mt-4 border-t border-border/70 pt-3">
      {reactions.length > 0 && (
        <ul className="mb-3 space-y-2.5">
          {reactions.map((r) => (
            <li key={r.feedback_ref} className="rounded border border-border bg-muted/30 p-3">
              <p className="whitespace-pre-wrap text-[13px] leading-[1.6] text-foreground">
                {r.comment}
              </p>
              <p className="mt-1.5 text-[11px] uppercase tracking-[0.12em] text-muted-foreground/70">
                {r.reviewer}
                {r.received_at && <span> · {formatWhen(r.received_at)}</span>}
              </p>
            </li>
          ))}
        </ul>
      )}

      {done && !open && (
        <p className="mb-2 text-[13px] text-emerald-400">
          Recorded — it goes to the team building this and shows up in the
          feedback ledger for this run.
        </p>
      )}

      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground underline-offset-4 hover:underline"
        >
          <MessageSquarePlus size={14} />
          {reactions.length > 0
            ? "Add your own"
            : (prompt ?? "Think we got this wrong? Tell us")}
        </button>
      ) : (
        <form onSubmit={submit} className="space-y-2.5">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={2000}
            rows={3}
            autoFocus
            placeholder="What would you have picked, and why?"
            aria-label="Your comment on this decision"
            className="w-full rounded border border-border bg-background px-3 py-2 text-[13px] leading-[1.6] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none"
          />
          {!hideIdentityFields && (
            <ReviewerIdentityFields
              identity={identity}
              onChange={onIdentityChange}
              note="Your name is stored with the comment so we can credit it and come back to you. Email is only used to reply."
            />
          )}
          {error && <p className="text-[13px] text-red-400">{error}</p>}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={!canSubmit}
              className={cn(
                "rounded px-3 py-1.5 text-[13px] font-medium transition",
                canSubmit
                  ? "bg-primary text-primary-foreground hover:opacity-90"
                  : "cursor-not-allowed bg-muted text-muted-foreground",
              )}
            >
              {busy ? "Sending…" : "Send"}
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setError(null);
              }}
              className="text-[13px] text-muted-foreground underline-offset-4 hover:underline"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
