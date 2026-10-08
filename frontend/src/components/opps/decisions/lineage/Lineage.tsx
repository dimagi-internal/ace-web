import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { ArrowLeft, GitBranch } from "lucide-react";

import {
  getDecisionLineage,
  type DecisionHistoryEntry,
  type DecisionLineage,
} from "@/api/lineage";
import { cn } from "@/lib/utils";

import {
  type Badge,
  type EditLike,
  type LineageFilter,
  entryHref,
  entryLabel,
  filterBucket,
  filterCounts,
  formatDay,
  hasAncestors,
  originBadge,
  sameValue,
  stepLabel,
  valueEverChanged,
  viaPhrase,
} from "./lineageDisplay";

/**
 * Decision lineage on screen: which decisions this run carried in, from
 * where, and how each one changed over time.
 *
 * - `LineageStrip` — this run ← the run it came from ← …, each linked (when
 *   the viewer may open it) and dated, with how each hop was made.
 * - `LineageFilterBar` — carried / new / changed / set by a person, counted.
 * - `OriginBadge` — one per decision row.
 * - `DecisionLineageHistory` — expandable, the value across the runs.
 *
 * Data: `GET …/runs/{run}/lineage` (`useDecisionLineage`), joined to rows by
 * id. Everything degrades to rendering nothing — lineage is context, never a
 * reason a page fails to load.
 */

export function useDecisionLineage(
  workspace: string,
  slug: string,
  runId: string | null | undefined,
  scope: "lineage" | "opp" = "lineage",
): DecisionLineage | null {
  const runKey = `${workspace}/${slug}/${runId ?? ""}`;
  // Keyed by run: a scope switch keeps showing the current lineage until the
  // wider one lands; a different run never shows the previous run's.
  const [state, setState] = useState<{ key: string; lineage: DecisionLineage } | null>(null);
  useEffect(() => {
    if (!workspace || !slug || !runId) return;
    let cancelled = false;
    getDecisionLineage(workspace, slug, runId, scope)
      .then((l) => {
        if (!cancelled) setState({ key: runKey, lineage: l });
      })
      .catch(() => {
        // Context, not content: a failed lineage read leaves the page as it was.
      });
    return () => {
      cancelled = true;
    };
  }, [workspace, slug, runId, scope, runKey]);
  return state && state.key === runKey ? state.lineage : null;
}

// ─── Context (Workbench panels sit deep inside PhaseView) ──────────

export interface LineageContextValue {
  lineage: DecisionLineage | null;
  filter: LineageFilter;
  setFilter: (f: LineageFilter) => void;
  plain: boolean;
}

const LineageContext = createContext<LineageContextValue>({
  lineage: null,
  filter: "all",
  setFilter: () => {},
  plain: false,
});

export const LineageProvider = LineageContext.Provider;

export function useLineageContext(): LineageContextValue {
  return useContext(LineageContext);
}

/** Does a row pass the current filter? Everything passes with no lineage. */
export function passesFilter(
  ctx: Pick<LineageContextValue, "lineage" | "filter">,
  id: string,
  edit?: EditLike,
): boolean {
  if (!ctx.lineage || ctx.filter === "all") return true;
  return filterBucket(ctx.lineage.origins[id], edit) === ctx.filter;
}

// ─── Strip ──────────────────────────────────────────────────────────

export function LineageStrip({
  lineage,
  plain,
  className,
  linkTo = "workbench",
  onScopeChange,
}: {
  lineage: DecisionLineage | null;
  plain: boolean;
  className?: string;
  /** Which page a linked step opens. */
  linkTo?: "workbench" | "summary";
  /**
   * Members: switch each decision's history between the runs this one was
   * built from (`lineage`) and every run of the opportunity (`opp`).
   */
  onScopeChange?: (scope: "lineage" | "opp") => void;
}) {
  if (!lineage || !hasAncestors(lineage)) return null;
  const head = lineage.chain[0];
  const canWiden = !!onScopeChange && lineage.viewer.is_member;
  return (
    <nav
      aria-label="Where this run came from"
      className={cn(
        "flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] leading-snug text-muted-foreground",
        className,
      )}
    >
      <GitBranch aria-hidden className="h-3.5 w-3.5 shrink-0" />
      {lineage.chain.map((step, i) => {
        const href = linkTo === "summary" ? step.summary_url : step.workbench_url;
        const label = stepLabel(step, head, plain);
        const date = formatDay(step.date);
        return (
          <span key={step.position} className="inline-flex flex-wrap items-center gap-x-2">
            {i > 0 && (
              <span className="inline-flex items-center gap-1 text-muted-foreground/80">
                <ArrowLeft aria-hidden className="h-3 w-3" />
                {viaPhrase(lineage.chain[i - 1], plain)}
              </span>
            )}
            <span className="inline-flex items-baseline gap-1">
              {href ? (
                <a
                  href={href}
                  className="font-medium text-foreground underline-offset-4 hover:underline"
                >
                  {label}
                </a>
              ) : (
                <span
                  className={cn(i === 0 ? "font-medium text-foreground" : "text-foreground/90")}
                  title={
                    !plain && i > 0 && !step.readable
                      ? "This run could not be read"
                      : !plain && i > 0 && !href
                        ? "In a workspace you are not a member of"
                        : undefined
                  }
                >
                  {label}
                </span>
              )}
              {date && !(plain && i > 0) && <span className="tabular-nums">· {date}</span>}
            </span>
          </span>
        );
      })}
      {canWiden && (
        <button
          type="button"
          onClick={() => onScopeChange?.(lineage.scope === "opp" ? "lineage" : "opp")}
          className="ml-1 text-[11px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
          title="Which runs each decision's history compares against"
        >
          {lineage.scope === "opp"
            ? "History: every run of this opportunity"
            : "History: the runs this one was built from"}
        </button>
      )}
    </nav>
  );
}

// ─── Filter ─────────────────────────────────────────────────────────

const FILTER_LABELS: Record<Exclude<LineageFilter, "all">, string> = {
  carried: "Carried",
  new: "New",
  changed: "Changed",
  human: "Set by a person",
};

export function LineageFilterBar({
  lineage,
  ids,
  edits,
  filter,
  onChange,
  className,
}: {
  lineage: DecisionLineage | null;
  /** The live row ids the filter counts over. */
  ids: readonly string[];
  edits?: Record<string, EditLike>;
  filter: LineageFilter;
  onChange: (f: LineageFilter) => void;
  className?: string;
}) {
  const counts = useMemo(
    () => (lineage ? filterCounts(ids, lineage, edits) : null),
    [lineage, ids, edits],
  );
  if (!lineage || !counts || !hasAncestors(lineage)) return null;
  const chip = (key: LineageFilter, label: string, n: number) => (
    <button
      key={key}
      type="button"
      aria-pressed={filter === key}
      disabled={key !== "all" && n === 0}
      onClick={() => onChange(filter === key ? "all" : key)}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors disabled:cursor-default disabled:opacity-40",
        filter === key
          ? "border-foreground/40 bg-accent/60 text-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {label} <span className="tabular-nums">{n}</span>
    </button>
  );
  return (
    <div
      role="group"
      aria-label="Filter decisions by where they came from"
      className={cn("flex flex-wrap items-center gap-2", className)}
    >
      {chip("all", "All", ids.length)}
      {(Object.keys(FILTER_LABELS) as (keyof typeof FILTER_LABELS)[]).map((k) =>
        chip(k, FILTER_LABELS[k], counts[k]),
      )}
    </div>
  );
}

// ─── Badge ──────────────────────────────────────────────────────────

const TONES: Record<Badge["tone"], string> = {
  neutral: "border-border bg-muted/40 text-muted-foreground",
  sky: "border-sky-500/40 bg-sky-500/10 text-sky-400",
  amber: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  emerald: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  violet: "border-violet-500/40 bg-violet-500/10 text-violet-400",
};

export function OriginBadge({
  lineage,
  id,
  plain,
  edit,
}: {
  lineage: DecisionLineage | null;
  id: string;
  plain: boolean;
  edit?: EditLike;
}) {
  if (!lineage) return null;
  const badge = originBadge(lineage.origins[id], lineage, plain, edit);
  if (!badge) return null;
  return (
    <span
      className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px]", TONES[badge.tone])}
      title={badge.title}
    >
      {badge.label}
    </span>
  );
}

// ─── History ────────────────────────────────────────────────────────

export function DecisionLineageHistory({
  lineage,
  id,
}: {
  lineage: DecisionLineage | null;
  id: string;
}) {
  const entries = lineage?.histories[id];
  if (!lineage || !entries || entries.length === 0 || !hasAncestors(lineage)) return null;
  const headWs = lineage.chain[0]?.workspace ?? null;
  const earlier = entries.slice(0, -1);
  const anyEarlier = earlier.some((e) => e.found);
  // Carried over verbatim (a clone, or a re-run that kept its answer): no
  // history to tell. The row's origin badge already says "unchanged". A
  // decision with no earlier match still says so — that is information.
  if (anyEarlier && !valueEverChanged(entries)) return null;
  return (
    <details className="mt-3 text-[12px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground hover:text-foreground">
        How this decision evolved
        <span className="ml-1 font-normal text-muted-foreground/70">
          {anyEarlier
            ? `(${entries.filter((e) => e.found).length} runs)`
            : "(no earlier match)"}
        </span>
      </summary>
      <ol className="mt-2 space-y-2 border-l border-border pl-3">
        {entries.map((e, i) => (
          <HistoryItem
            key={`${e.workspace}/${e.run_id}`}
            entry={e}
            headWs={headWs}
            isCurrent={i === entries.length - 1}
            currentId={id}
            prev={entries.slice(0, i).reverse().find((x) => x.found)}
          />
        ))}
      </ol>
      {!anyEarlier && (
        <p className="mt-2 text-muted-foreground">
          No earlier run has a decision this one could be matched to — by id, by an
          earlier id, or by a retired id. It is treated as new rather than guessed at.
        </p>
      )}
    </details>
  );
}

function HistoryItem({
  entry,
  headWs,
  isCurrent,
  currentId,
  prev,
}: {
  entry: DecisionHistoryEntry;
  headWs: string | null;
  isCurrent: boolean;
  currentId: string;
  prev?: DecisionHistoryEntry;
}) {
  const href = isCurrent ? null : entryHref(entry);
  const label = entryLabel(entry, headWs);
  const value = entry.plain_value || entry.value || "";
  const same = sameValue(prev, entry);
  const human = entry.status === "overridden" || entry.status === "human-decided";
  return (
    <li className={cn(!entry.found && "text-muted-foreground/70")}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="tabular-nums text-muted-foreground">{formatDay(entry.date)}</span>
        {href ? (
          <a href={href} className="font-mono text-[11px] text-foreground underline-offset-4 hover:underline">
            {label}
          </a>
        ) : (
          <span className="font-mono text-[11px] text-foreground/90">{label}</span>
        )}
        {isCurrent && <span className="text-muted-foreground">(this run)</span>}
        {!entry.in_lineage && (
          <span className="text-muted-foreground" title="Another run of this opportunity, not one this run was built from">
            · other run
          </span>
        )}
      </div>
      {!entry.found ? (
        <p className="mt-0.5">{entry.readable ? "Not in this run." : "Could not be read."}</p>
      ) : (
        <div className="mt-0.5 space-y-0.5">
          <p className="text-foreground [overflow-wrap:anywhere]">
            {value || "—"}
            {prev && same && <span className="ml-1 text-muted-foreground">(unchanged)</span>}
          </p>
          {entry.row_id && entry.row_id !== currentId && (
            <p className="text-muted-foreground">
              recorded as <span className="font-mono text-[11px]">{entry.row_id}</span>
              {entry.superseded ? " (already replaced in that run)" : ""}
            </p>
          )}
          {human ? (
            <p className="text-sky-400">
              set by {entry.by || "a person"}
              {entry.at ? ` on ${formatDay(entry.at)}` : ""}
            </p>
          ) : (
            <p className="text-muted-foreground">set by ACE</p>
          )}
          {/* A reason repeated verbatim from the run before adds nothing. */}
          {entry.reason && entry.reason !== prev?.reason && (
            <p className="line-clamp-3 text-muted-foreground [overflow-wrap:anywhere]" title={entry.reason}>
              {entry.reason}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
