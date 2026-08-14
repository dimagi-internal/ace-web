import { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";

import type { OppSummaryPayload, ReviewDecision } from "@/api/oppSummary";
import { DecisionDetailFields } from "@/components/opps/decisions/DecisionDetailFields";
import { EvidenceBadge } from "@/components/opps/decisions/EvidenceBadge";
import { cn } from "@/lib/utils";

/**
 * The public, read-only face of the run's decisions log.
 *
 * A 24-page PDD is a bad instrument for eliciting decisions — people skim
 * prose and agree with all of it. Every load-bearing default is already a
 * typed row (question, picked value, alternatives, reasoning, evidence
 * basis), so this renders those rows and gets a partner reacting to
 * specific calls instead of reading a design document end to end.
 *
 * Same rows, same field set, same evidence vocabulary as the Workbench —
 * the row anatomy comes from the shared `DecisionDetailFields`. What's
 * stripped: gates, step controls, editing, and per-phase panels. This is
 * a review surface, not a console.
 *
 * Ordering is the whole argument. `conflicting` (ACE had to resolve
 * sources that disagreed) and `overridden` (a human already changed it)
 * lead, expanded, because those are the calls an outside reader is best
 * placed to correct. Everything else sits behind one disclosure.
 */
function isFlagged(d: ReviewDecision): boolean {
  return d.evidence_basis === "conflicting" || d.status === "overridden";
}

export function DecisionsReview({
  decisions,
}: {
  decisions: NonNullable<OppSummaryPayload["decisions"]>;
}) {
  const [showAll, setShowAll] = useState(false);
  const { counts, rows, total } = decisions;

  const flagged = useMemo(() => rows.filter(isFlagged), [rows]);
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

  return (
    <div>
      <p className="text-[0.975rem] leading-[1.7] text-muted-foreground">
        ACE made <span className="text-foreground">{total}</span> load-bearing calls building
        this run. Each one records what it picked, what else was on the table, and why.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        <Count n={counts.stated} label="stated in a source" />
        <Count n={counts.inferred} label="inferred beyond it" />
        <Count n={counts.conflicting} label="resolved a conflict" tone="amber" />
        <Count n={counts.overridden} label="changed by a reviewer" tone="sky" />
      </div>

      {flagged.length > 0 && (
        <div className="mt-7">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-foreground">
            Worth your eye first
          </h3>
          <p className="mt-1.5 text-sm leading-[1.6] text-muted-foreground">
            {counts.conflicting > 0 && counts.overridden > 0
              ? "Where the source material disagreed with itself, or a reviewer has already changed the answer."
              : counts.conflicting > 0
                ? "The source material disagreed with itself here and ACE picked a side. If we picked wrong, this is the cheapest place to say so."
                : "A reviewer has already changed the answer here."}
          </p>
          <ul className="mt-3 divide-y divide-border border-y border-border">
            {flagged.map((d) => (
              <li key={d.id}>
                <DecisionItem decision={d} defaultOpen />
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
                    <DecisionItem decision={d} />
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
}: {
  decision: ReviewDecision;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const answer = decision.override || decision.ai_default;

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
        {decision.status === "overridden" && (
          <span className="shrink-0 rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-sky-400">
            reviewer changed
          </span>
        )}
        <EvidenceBadge basis={decision.evidence_basis} />
      </button>
      {open && (
        <div className="grid grid-cols-[130px_1fr] gap-x-5 gap-y-2.5 pb-5 pl-6 pr-1 text-[13px] leading-[1.6]">
          <DecisionDetailFields
            decision={decision}
            effectiveValue={answer}
            effectiveReason={decision.override_reasoning}
          />
        </div>
      )}
    </div>
  );
}
