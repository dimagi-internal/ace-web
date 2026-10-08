import { useState } from "react";
import { MessageSquarePlus } from "lucide-react";

import type { DecisionReaction } from "@/api/oppSummary";
import { SignInToEdit } from "@/components/opps/summary/SignInToEdit";
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
 * Members only (2026-10-03): the commenter is the signed-in workspace
 * member, resolved server-side — there is no name field. Anyone else
 * reads the thread and gets "Sign in to comment" in place of the box.
 */

function formatWhen(iso: string): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.valueOf())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * The one sentence that separates the two acts on a row. A comment is
 * stored on the decision for the team and other reviewers; it does not
 * move the answer, and nothing is sent to anyone when it is posted, so
 * the copy promises neither.
 */
const NOT_AN_EDIT =
  "A comment doesn't change the answer — use Confirm or pick an option above for that. " +
  "It stays on this decision for the ACE team and other reviewers to read.";

export interface ReactionSubmit {
  comment: string;
}

export function DecisionReactions({
  decisionId,
  reactions,
  onSubmit,
  canWrite,
  contested = false,
}: {
  decisionId: string;
  reactions: DecisionReaction[];
  onSubmit: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  /** A signed-in workspace member. Anyone else reads, and is offered sign-in. */
  canWrite: boolean;
  /**
   * ACE's sources disagreed on this row. The box is then pitched at the
   * reviewer who is not ready to pick an answer: ask what would settle it.
   */
  contested?: boolean;
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
      await onSubmit(decisionId, { comment: comment.trim() });
      setComment("");
      setOpen(false);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that.");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = comment.trim().length >= 3 && !busy;

  // Say what the box DOES before anyone types in it. The old copy ("Not
  // sure enough to change it? Say what you'd want to know.") named the
  // act only by contrast with the editor above it, a reviewer could not
  // tell whether sending it changed the answer, and the placeholder then
  // asked the opposite question ("What would you have picked?").
  const opener = contested
    ? "Not ready to decide? Ask what you'd need to know"
    : "Ask a question or raise a concern";
  const placeholder = contested
    ? "What would you need to know before choosing? e.g. who relies on this, or which source is right"
    : "What is unclear or worrying about this answer?";

  return (
    <div className="mt-4 border-t border-border/70 pt-3">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        Questions and concerns
      </p>

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
          Saved on this decision. The answer above is unchanged.
        </p>
      )}

      {!canWrite ? (
        <SignInToEdit>Sign in to comment</SignInToEdit>
      ) : !open ? (
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground underline-offset-4 hover:underline"
          >
            <MessageSquarePlus size={14} />
            {reactions.length > 0 ? "Add a question or concern" : opener}
          </button>
          <p className="text-[12px] leading-[1.5] text-muted-foreground">
            {NOT_AN_EDIT}
          </p>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-2.5">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={2000}
            rows={3}
            autoFocus
            placeholder={placeholder}
            aria-label="Your comment on this decision"
            aria-describedby={`reaction-help-${decisionId}`}
            className="w-full rounded border border-border bg-background px-3 py-2 text-[13px] leading-[1.6] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none"
          />
          <p id={`reaction-help-${decisionId}`} className="text-[12px] leading-[1.5] text-muted-foreground">
            {NOT_AN_EDIT}
          </p>
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
              {busy ? "Posting…" : "Post comment"}
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
