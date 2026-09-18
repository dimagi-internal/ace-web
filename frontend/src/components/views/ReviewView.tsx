import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";

import { type FeedbackPayload, type FeedbackRecord, fetchFeedback } from "@/api/feedback";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import {
  type Disposition,
  type LedgerItem,
  type Outcome,
  outcomeCounts,
  outcomeOf,
  parseLedger,
} from "@/components/views/ledgerParse";
import { cn } from "@/lib/utils";

/**
 * What outside reviewers said about this opp, and what it changed.
 *
 * ACE grades its own work, and sometimes it is wrong in ways only a domain
 * expert catches — one comment here overturned an assessment ACE's own eval
 * had scored 9.4. This view is where that shows: the reviewer's words
 * unedited, next to the issues, decisions and open questions they produced.
 *
 * The "what it changed" half is the plugin's, rendered as it published it.
 * ace-web does not recompute the join (it greps GitHub for `Feedback-Ref`
 * stamps); a second implementation would need a credential and would drift
 * from the one people actually run.
 */
export function ReviewView({
  oppSlug,
  workspaceSlug,
}: {
  oppSlug: string;
  workspaceSlug: string;
}) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "loaded"; payload: FeedbackPayload }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchFeedback(workspaceSlug, oppSlug)
      .then((payload) => !cancelled && setState({ kind: "loaded", payload }))
      .catch((e: unknown) =>
        !cancelled &&
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        }),
      );
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, oppSlug]);

  if (state.kind === "loading") {
    return <Centered>Loading reviews…</Centered>;
  }
  if (state.kind === "error") {
    return <Centered className="text-destructive">{state.message}</Centered>;
  }
  if (state.payload.records.length === 0) {
    return (
      <Centered>
        <div className="max-w-[54ch] text-center">
          <p className="text-foreground">Nobody outside ACE has reviewed this opp yet.</p>
          <p className="mt-2">
            When someone does, their comments land here in their own words, next to
            the issues and decisions they produced.
          </p>
        </div>
      </Centered>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="flex max-w-4xl flex-col gap-8">
        {state.payload.records.map((record) => (
          <ReviewRecord key={record.slug} record={record} />
        ))}
      </div>
    </div>
  );
}

function ReviewRecord({ record }: { record: FeedbackRecord }) {
  const [showComments, setShowComments] = useState(false);
  const parsed = useMemo(() => parseLedger(record.ledger_body), [record.ledger_body]);
  const counts = useMemo(() => (parsed ? outcomeCounts(parsed) : null), [parsed]);

  return (
    <article>
      <header className="border-b pb-5">
        <h2 className="text-lg font-semibold text-foreground">
          What an outside expert changed
        </h2>
        <p className="mt-1.5 max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
          <span className="text-foreground">{record.reviewer}</span> reviewed{" "}
          {record.artifact_url ? (
            <a
              href={record.artifact_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              this program&rsquo;s design
            </a>
          ) : (
            "this program\u2019s design"
          )}
          {record.received_at && ` on ${record.received_at}`} and left{" "}
          {record.tally?.comments ?? record.item_count} comments. Each one is below,
          in their words, with what it changed.
        </p>

        {counts ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {counts.ace > 0 && (
              <Stat
                outcome="ace"
                n={counts.ace}
                label="fixed in ACE itself"
                note="Every future program gets these fixes."
              />
            )}
            {counts.program > 0 && (
              <Stat
                outcome="program"
                n={counts.program}
                label="changed this program"
                note="Design decisions for this program only."
              />
            )}
            {counts.person > 0 && (
              <Stat
                outcome="person"
                n={counts.person}
                label="waiting on a person"
                note="A call ACE shouldn't make on its own."
              />
            )}
          </div>
        ) : record.ledger_body ? null : (
          <p className="mt-3 text-sm text-muted-foreground">
            What changed hasn&rsquo;t been worked out for this review yet, so only the
            comments are shown.
          </p>
        )}
        {counts && (
          <p className="mt-3 text-xs text-muted-foreground">
            Some comments did more than one thing, so these add up to more than{" "}
            {record.tally?.comments ?? record.item_count}.
          </p>
        )}
      </header>

      {record.ledger_body ? (
        parsed ? (
          <ol className="mt-5 flex flex-col gap-6">
            {parsed.map((item) => (
              <LedgerItemRow key={item.id || item.anchor} item={item} />
            ))}
          </ol>
        ) : (
          // Unrecognised shape — the markdown is always correct, just dense.
          <div className="prose prose-sm dark:prose-invert mt-4 max-w-none">
            <MarkdownRenderer content={record.ledger_body} />
          </div>
        )
      ) : (
        <ul className="mt-4 flex flex-col gap-4">
          {record.items.map((item) => (
            <li key={item.id}>
              <div className="text-xs text-muted-foreground">{item.anchor}</div>
              <blockquote className="mt-1 border-l-2 pl-3 text-sm text-foreground">
                {item.verbatim}
              </blockquote>
            </li>
          ))}
        </ul>
      )}

      <footer className="mt-4 flex flex-wrap gap-4 text-xs text-muted-foreground">
        {record.ledger_body && !parsed && record.items.length > 0 && (
          <button
            type="button"
            onClick={() => setShowComments((v) => !v)}
            className="underline underline-offset-2 hover:text-foreground"
          >
            {showComments ? "Hide" : "Show"} the original comments
          </button>
        )}
        {record.ledger_url && (
          <a
            href={record.ledger_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground"
          >
            Ledger in Drive <ExternalLink className="size-3" />
          </a>
        )}
        {record.record_url && (
          <a
            href={record.record_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground"
          >
            Original record <ExternalLink className="size-3" />
          </a>
        )}
      </footer>

      {showComments && (
        <ul className="mt-4 flex flex-col gap-4 border-t pt-4">
          {record.items.map((item) => (
            <li key={item.id}>
              <div className="text-xs text-muted-foreground">{item.anchor}</div>
              <blockquote className="mt-1 border-l-2 pl-3 text-sm text-foreground">
                {item.verbatim}
              </blockquote>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function LedgerItemRow({ item }: { item: LedgerItem }) {
  return (
    <li className="border-t pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-sm font-semibold text-foreground">
        {item.anchor}
      </h3>
      {item.quote && (
        <blockquote className="mt-2 whitespace-pre-line border-l-2 border-muted-foreground/40 pl-3 text-sm italic text-muted-foreground">
          {item.quote}
        </blockquote>
      )}
      {item.dispositions.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {item.dispositions.map((d, i) => (
            <DispositionRow key={i} d={d} />
          ))}
        </ul>
      )}
    </li>
  );
}

function DispositionRow({ d }: { d: Disposition }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
      <OutcomeBadge outcome={outcomeOf(d)} fallback={d.status} />
      {d.ref &&
        (d.href ? (
          <a
            href={d.href}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-foreground underline underline-offset-2 hover:text-primary"
          >
            {d.ref}
          </a>
        ) : (
          <span className="font-medium text-foreground">{d.ref}</span>
        ))}
      <span className="min-w-0 flex-1 basis-full text-muted-foreground sm:basis-auto">
        {d.text}
      </span>
    </li>
  );
}

const OUTCOME: Record<Outcome, { label: string; tone: string }> = {
  ace: {
    label: "Fixed in ACE",
    tone: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  },
  program: {
    label: "Changed this program",
    tone: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-400",
  },
  person: {
    label: "Needs a decision",
    tone: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  },
  other: { label: "", tone: "border-border bg-muted text-muted-foreground" },
};

/** Says WHAT changed. The ledger's own badge said SHIPPED for a fix to ACE and
 *  a one-off program decision alike, which buried the self-improvement story. */
function OutcomeBadge({ outcome, fallback }: { outcome: Outcome; fallback: string }) {
  const o = OUTCOME[outcome];
  return (
    <span
      className={cn(
        "shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold",
        o.tone,
      )}
    >
      {o.label || fallback}
    </span>
  );
}

function Stat({
  outcome,
  n,
  label,
  note,
}: {
  outcome: Outcome;
  n: number;
  label: string;
  note: string;
}) {
  return (
    <div className={cn("rounded-md border px-3 py-2.5", OUTCOME[outcome].tone)}>
      <div className="text-2xl font-semibold leading-none">{n}</div>
      <div className="mt-1 text-sm font-medium">{label}</div>
      <div className="mt-0.5 text-xs opacity-80">{note}</div>
    </div>
  );
}

function Centered({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-full items-center justify-center p-8 text-sm text-muted-foreground",
        className,
      )}
    >
      {children}
    </div>
  );
}
