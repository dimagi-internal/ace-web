import { useEffect, useState } from "react";
import { MessageSquarePlus } from "lucide-react";

import type { DecisionReaction } from "@/api/oppSummary";
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
 * Identity: the name is REQUIRED and self-reported. The page has no
 * login and a partner cannot self-serve one, so the choices were a
 * required free-text name or anonymous comments — and an anonymous
 * comment defeats the store it lands in, whose value is telling a
 * reviewer where THEIR comment went and telling a future reader whose
 * judgement drove a change. The form says the name is recorded, and the
 * stored record says it is self-reported rather than pretending
 * otherwise. It is remembered locally so a partner working through
 * several rows types it once.
 */

const NAME_KEY = "ace.summary.reviewerName";
const EMAIL_KEY = "ace.summary.reviewerEmail";

function remembered(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function remember(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private browsing — the form still works, it just won't prefill */
  }
}

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
  prompt,
}: {
  decisionId: string;
  reactions: DecisionReaction[];
  onSubmit: (decisionId: string, body: ReactionSubmit) => Promise<void>;
  /** Row-specific invitation — a conflicting row deserves a sharper one. */
  prompt?: string;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName((v) => v || remembered(NAME_KEY));
    setEmail((v) => v || remembered(EMAIL_KEY));
  }, [open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(decisionId, {
        reviewer: name.trim(),
        reviewer_email: email.trim() || undefined,
        comment: comment.trim(),
      });
      remember(NAME_KEY, name.trim());
      remember(EMAIL_KEY, email.trim());
      setComment("");
      setOpen(false);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't record that.");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = name.trim().length >= 2 && comment.trim().length >= 3 && !busy;

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
          <div className="flex flex-wrap gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={80}
              required
              placeholder="Your name (required)"
              aria-label="Your name"
              className="min-w-[9rem] flex-1 rounded border border-border bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none"
            />
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              maxLength={254}
              type="email"
              placeholder="Email (optional)"
              aria-label="Your email, optional"
              className="min-w-[9rem] flex-1 rounded border border-border bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none"
            />
          </div>
          <p className="text-[11px] leading-[1.5] text-muted-foreground/70">
            Your name is stored with the comment so we can credit it and come
            back to you. Email is only used to reply.
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
