import { useEffect, useRef, useState } from "react";

import { listTurnEvents, type TurnEvent } from "@/canopy/api";

/**
 * Watch one turn's output live, in ace-web.
 *
 * This exists because a run on the CLOUD runner has no canopy Session to open
 * in the chat view — an email/scheduled turn drives none, and the cloud box has
 * no emdash for the sessions feed to report. What it does have is the event
 * ledger every runner writes (`cloud_runner.py` emits `status` / `assistant` /
 * `tool_start` / `tool_end` for every turn; an inbound-email turn measured 184
 * events), so that ledger is the live view for exactly the runs the chat view
 * cannot reach.
 *
 * Polls incrementally by `seq`. The server caps a response at 500 rows, so
 * re-fetching from zero would both truncate a long run and grow more expensive
 * the longer it ran — `after` keeps each poll the size of what actually
 * happened since the last one.
 */
export function TurnWatch({ base, turnId, live }: {
  base: string;
  turnId: string;
  /** Stop polling once the turn is finished — a done turn's ledger is frozen. */
  live: boolean;
}) {
  const [events, setEvents] = useState<TurnEvent[]>([]);
  const [failed, setFailed] = useState(false);
  const seqRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const pull = () => {
      listTurnEvents(base, turnId, seqRef.current)
        .then((batch) => {
          if (cancelled || batch.length === 0) return;
          seqRef.current = batch[batch.length - 1]!.seq;
          setEvents((prev) => [...prev, ...batch]);
          setFailed(false);
        })
        .catch(() => { if (!cancelled) setFailed(true); });
    };
    pull();
    if (!live) return () => { cancelled = true; };
    const t = window.setInterval(pull, 4000);
    return () => { cancelled = true; window.clearInterval(t); };
  }, [base, turnId, live]);

  if (failed && events.length === 0) {
    return <p className="text-sm text-destructive">Couldn&rsquo;t load this run&rsquo;s output.</p>;
  }
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="turn-watch-empty">
        {live ? "Waiting for the runner to say something…" : "This run produced no output."}
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-2" data-testid="turn-watch">
      {events.map((e) => (
        <li key={e.seq} data-testid={`turn-event-${e.kind}`}>
          {renderEvent(e)}
        </li>
      ))}
    </ol>
  );
}

/** One event. Assistant text is the substance; tool calls are the skeleton, so
 *  they render compactly rather than competing with it. */
function renderEvent(e: TurnEvent) {
  const p = e.payload ?? {};
  if (e.kind === "assistant") {
    const text = typeof p.text === "string" ? p.text : "";
    if (!text.trim()) return null;
    return (
      <div className="rounded-md bg-muted px-3 py-2 text-sm whitespace-pre-wrap">{text}</div>
    );
  }
  if (e.kind === "tool_start" || e.kind === "tool_end") {
    const name = typeof p.name === "string" ? p.name : "tool";
    // The command is the useful half of a Bash call and the noisy half of
    // everything else, so it is truncated rather than dropped.
    const detail = typeof p.command === "string" ? p.command
      : typeof p.text === "string" ? p.text : "";
    return (
      <div className="flex items-baseline gap-2 px-3 text-xs text-muted-foreground">
        <span aria-hidden="true">{e.kind === "tool_end" ? "✓" : "▸"}</span>
        <span className="font-medium">{name}</span>
        {detail && <span className="truncate">{detail.replace(/\s+/g, " ").slice(0, 140)}</span>}
      </div>
    );
  }
  if (e.kind === "status") {
    const text = typeof p.text === "string" ? p.text
      : typeof p.status === "string" ? p.status : "";
    if (!text) return null;
    return <div className="px-3 text-xs italic text-muted-foreground">{text}</div>;
  }
  return null;
}
