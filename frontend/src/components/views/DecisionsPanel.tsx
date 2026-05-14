import { useMemo, useState } from "react";
import { ChevronRight, HelpCircle, MessageSquareWarning } from "lucide-react";

import type { Decision } from "@/api/types.ws";
import { cn } from "@/lib/utils";

interface Props {
  /** The phase whose decisions we want to show — match `Decision.phase`. */
  phase: string;
  /** All decisions on the run — we filter to this phase. */
  decisions: Decision[];
}

/**
 * Per-phase rollup of the decisions log.
 *
 * The decisions log (ACE PRs #160–#164) is a per-run YAML file at the
 * run-folder root. Each row is a load-bearing question + the default
 * the orchestrator picked + the alternatives it considered + a status
 * (applied / overridden / open). Rows carry a ``phase`` tag so we can
 * group them per phase here.
 *
 * Default rendering: collapsed list of question titles with a status
 * badge; click a row to reveal default, options considered, source,
 * notes. The "open" status is the most actionable — they appear in
 * amber and are expanded by default.
 */
// Status order surfaces the most actionable rows first:
//   open       — needs a human decision; default is just a guess
//   overridden — human said "no" to the default; usually rare and worth reading
//   applied    — default was kept; usually fine to glance past
const STATUS_RANK: Record<Decision["status"], number> = {
  open: 0,
  overridden: 1,
  applied: 2,
};

export function DecisionsPanel({ phase, decisions }: Props) {
  const phaseRows = useMemo(
    () =>
      decisions
        .filter((d) => d.phase === phase)
        // Stable sort: status first, then preserve YAML order within status.
        .map((d, i) => ({ d, i }))
        .sort((a, b) => {
          const r = STATUS_RANK[a.d.status] - STATUS_RANK[b.d.status];
          return r !== 0 ? r : a.i - b.i;
        })
        .map((x) => x.d),
    [decisions, phase],
  );

  if (phaseRows.length === 0) return null;

  const open = phaseRows.filter((d) => d.status === "open").length;
  const overridden = phaseRows.filter((d) => d.status === "overridden").length;

  return <DecisionsPanelInner phaseRows={phaseRows} open={open} overridden={overridden} />;
}

function DecisionsPanelInner({
  phaseRows,
  open,
  overridden,
}: {
  phaseRows: Decision[];
  open: number;
  overridden: number;
}) {
  // Section starts collapsed. Earlier versions auto-opened the whole
  // panel and every "open" row inside it, which made the phase-detail
  // view land on a wall of decision text before the user had a chance
  // to scan the skills list. Master-toggle here, individual rows
  // collapse separately in DecisionRow.
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="mt-3 rounded-lg border border-border bg-card/30">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center gap-2.5 px-4 py-2.5 text-left",
          expanded ? "border-b border-border/70" : "",
        )}
      >
        <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
          <HelpCircle className="h-3 w-3" />
          Decisions
        </span>
        <span className="text-xs font-medium text-foreground">{phaseRows.length}</span>
        <span className="ml-auto flex items-center gap-2 text-[11px]">
          {open > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-amber-500">
              <MessageSquareWarning className="h-3 w-3" />
              {open} open
            </span>
          )}
          {overridden > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-sky-400">
              {overridden} overridden
            </span>
          )}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            expanded ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {expanded && (
        <ul className="divide-y divide-border/60">
          {phaseRows.map((d) => (
            <li key={d.id}>
              <DecisionRow decision={d} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function DecisionRow({ decision }: { decision: Decision }) {
  // Start collapsed regardless of status. We used to auto-expand "open"
  // rows on the theory that they're the most actionable, but it meant
  // the panel was already mostly-expanded on first paint and the user
  // had no chance to scan titles before reading bodies. Everything
  // starts compact; user clicks a row to drill in.
  const [open, setOpen] = useState(false);
  const tone =
    decision.status === "open"
      ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
      : decision.status === "overridden"
        ? "border-sky-500/40 bg-sky-500/10 text-sky-400"
        : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-2 text-left text-xs hover:bg-accent/40"
      >
        <span className="font-mono text-[10px] text-muted-foreground/70">{decision.id}</span>
        <span className="flex-1 truncate text-foreground">{decision.question}</span>
        <span className="hidden truncate text-[11px] text-muted-foreground sm:block sm:max-w-[260px]">
          → <span className="font-medium text-foreground">{decision.default}</span>
        </span>
        <span
          className={cn(
            "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            tone,
          )}
        >
          {decision.status}
        </span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open ? "rotate-90 text-foreground" : "",
          )}
        />
      </button>
      {open && (
        <div className="animate-in fade-in slide-in-from-top-1 grid grid-cols-[120px_1fr] gap-x-4 gap-y-2 border-t border-border/40 bg-background/30 px-4 pb-3 pt-3 text-[11px] duration-150">
          <DetailRow label="Default" value={<span className="font-medium text-foreground">{decision.default}</span>} />
          {decision.options_considered.length > 0 && (
            <DetailRow
              label="Options considered"
              value={
                <span className="flex flex-wrap gap-1.5">
                  {decision.options_considered.map((opt) => (
                    <span
                      key={opt}
                      className={cn(
                        "rounded border px-1.5 py-0.5",
                        opt === decision.default
                          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                          : "border-border bg-muted/30 text-muted-foreground",
                      )}
                    >
                      {opt}
                    </span>
                  ))}
                </span>
              }
            />
          )}
          {decision.source && (
            <DetailRow
              label="Source"
              value={<span className="text-muted-foreground">{decision.source}</span>}
            />
          )}
          <DetailRow
            label="Raised by"
            value={
              <span className="font-mono text-[10px] text-muted-foreground/80">{decision.skill}</span>
            }
          />
          {decision.notes && (
            <DetailRow
              label="Notes"
              value={<span className="whitespace-pre-line text-muted-foreground">{decision.notes}</span>}
            />
          )}
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </div>
      <div className="min-w-0">{value}</div>
    </>
  );
}
