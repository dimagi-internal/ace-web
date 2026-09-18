import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";

import { type FeedbackPayload, type FeedbackRecord, fetchFeedback } from "@/api/feedback";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { type Disposition, type LedgerItem, parseLedger } from "@/components/views/ledgerParse";
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

  return (
    <article>
      <header className="border-b pb-3">
        <h2 className="text-lg font-semibold text-foreground">{record.reviewer}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Reviewed {record.artifact_url ? (
            <a
              href={record.artifact_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              {record.artifact || "the design document"}
            </a>
          ) : (
            record.artifact || "the design document"
          )}
          {record.received_at && ` on ${record.received_at}`}
          {record.against_run && `, against run ${record.against_run}`}.
          {record.responding_run && (
            <> Answered in run {record.responding_run}.</>
          )}
        </p>

        {record.tally ? (
          <p className="mt-3 text-sm">
            <Count n={record.tally.comments} noun="comment" />
            {" — "}
            <span className="text-foreground">{record.tally.shipped} shipped</span>
            {record.tally.needs_human > 0 && (
              <span className="text-muted-foreground">
                , {record.tally.needs_human} still{" "}
                {record.tally.needs_human === 1 ? "needs" : "need"} a person
              </span>
            )}
            {record.tally.unrouted > 0 && (
              <span className="text-destructive">
                , {record.tally.unrouted} unrouted
              </span>
            )}
          </p>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            <Count n={record.item_count} noun="comment" />
            {record.ledger_body
              ? ""
              : " — the ledger for this review hasn't been rendered yet, so what changed isn't shown."}
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
      <StatusChip status={d.status} />
      {d.kind && <span className="text-xs text-muted-foreground">{d.kind}</span>}
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

/** SHIPPED reads green, anything unresolved reads as unfinished. Unrouted —
 *  nobody actioned it — is the one that should look wrong. */
function StatusChip({ status }: { status: string }) {
  const s = status.toLowerCase();
  const tone = s.includes("ship")
    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
    : s.includes("unrouted")
      ? "border-destructive/40 bg-destructive/10 text-destructive"
      : "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400";
  return (
    <span
      className={cn(
        "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold tracking-wide",
        tone,
      )}
    >
      {status}
    </span>
  );
}

function Count({ n, noun }: { n: number; noun: string }) {
  return (
    <span className="text-foreground">
      {n} {noun}
      {n === 1 ? "" : "s"}
    </span>
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
