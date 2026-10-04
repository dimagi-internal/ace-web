import { ArrowRight } from "lucide-react";

import { signInHref } from "@/components/opps/summary/SignInToEdit";

/**
 * The first thing an outside reader sees on the Overview: what this page
 * is, why they have it, what we need from them, how to answer, and who
 * reads the answer.
 *
 * ACE's run-surface audit of spark-facilitator/20261001-2208 scored the
 * page 5.6/10 against a pass band of 7, and its top finding was that the
 * page never said any of this — not that an AI drafted it, not what the
 * reader was expected to do, not where a reply goes. The page is
 * forwarded to people with no Dimagi account and no context, so it has to
 * carry its own.
 *
 * Members (Dimagi staff in this workspace) get nothing: they already know,
 * and the block would push the content down on every visit.
 *
 * Plain English, and the platform is "Connect" — never the retired long
 * name (ACE `skills/_terminology.md`).
 */
export function SummaryOrientation({
  isMember,
  confirmOutstanding,
  confirmTotal,
  answerOutstanding = 0,
  answerTotal = 0,
  hasDecisions,
  onOpenDecisions,
}: {
  isMember: boolean;
  /** Recommended confirmations still waiting — `askCounts(...).confirm`. */
  confirmOutstanding: number;
  confirmTotal: number;
  /** Questions that must be answered before a stage — `askCounts(...).answer`. */
  answerOutstanding?: number;
  answerTotal?: number;
  /** Whether there is a Decisions tab to send the reader to. */
  hasDecisions: boolean;
  onOpenDecisions: () => void;
}) {
  if (isMember) return null;

  // Both kinds of ask count (ACE spec 2026-10-04): the confirmations and the
  // questions that must be answered before a stage.
  const parts: string[] = [];
  if (answerOutstanding > 0) {
    parts.push(
      `answer the ${answerOutstanding} ${
        answerOutstanding === 1 ? "question" : "questions"
      } marked “Answer before …”`,
    );
  }
  if (confirmOutstanding > 0) {
    parts.push(
      `confirm the ${confirmOutstanding} ${
        confirmOutstanding === 1 ? "decision" : "decisions"
      } marked “Confirm before launch”`,
    );
  }
  const ask =
    parts.length > 0
      ? `Please ${parts.join(", and ")}. Comments on any other decision are welcome too.`
      : confirmTotal + answerTotal > 0
        ? "Everything we asked you to confirm or answer has been answered. Comments on any decision are still welcome."
        : "Tell us about anything in the design or the decisions that looks wrong.";

  return (
    <section
      aria-label="About this page"
      className="rounded-md border border-border bg-card/40 px-4 py-4 text-[0.95rem] leading-[1.7] text-muted-foreground sm:px-5"
    >
      <p className="text-foreground">
        ACE, Dimagi’s AI program engine, drafted this program and this page.
        Dimagi staff review it. You have this link because we would like your
        review before the program launches.
      </p>

      <dl className="mt-3 space-y-2">
        <div>
          <dt className="inline font-medium text-foreground">What we need from you: </dt>
          <dd className="inline">
            {ask}
            {hasDecisions && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={onOpenDecisions}
                  className="group inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-4"
                >
                  Go to the decisions
                  <ArrowRight
                    size={13}
                    aria-hidden
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </button>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt className="inline font-medium text-foreground">How to respond: </dt>
          <dd className="inline">
            <a
              href={signInHref()}
              className="font-medium text-foreground underline underline-offset-4"
            >
              Sign in
            </a>{" "}
            to confirm, change or comment on a decision, or reply to the email
            that sent you this link.
          </dd>
        </div>
        <div>
          <dt className="inline font-medium text-foreground">Who sees your reply: </dt>
          <dd className="inline">
            Dimagi’s team reads every reply, and ACE uses them to shape the next
            version.
          </dd>
        </div>
        <div>
          <dt className="inline font-medium text-foreground">Terms used here: </dt>
          <dd className="inline">
            <span className="text-foreground">LLO</span> — the implementing
            organisation that runs the program locally.{" "}
            <span className="text-foreground">FLW</span> — a field worker, the
            person who visits communities and records each visit in the app.{" "}
            <span className="text-foreground">Connect</span> — Dimagi’s platform
            that checks each recorded visit and pays for it.
          </dd>
        </div>
      </dl>
    </section>
  );
}
