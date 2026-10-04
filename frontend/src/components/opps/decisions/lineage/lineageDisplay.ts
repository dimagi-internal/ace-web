import type {
  DecisionHistoryEntry,
  DecisionLineage,
  DecisionOrigin,
  LineageStep,
} from "@/api/lineage";

/**
 * Words for decision lineage, in one place, for both readers:
 *
 * - a MEMBER reads run ids ("carried from dimagi-team / 20260925-1536 unchanged");
 * - an outside reader (`plain`) reads versions and dates ("carried over
 *   unchanged from the 25 Sep 2026 version") — no run plumbing.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-25" → "25 Sep 2026"; "" stays "". Never shifts across time zones. */
export function formatDay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "";
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

/** The name a chain step reads under. */
export function stepLabel(step: LineageStep, head: LineageStep | undefined, plain: boolean): string {
  if (plain || !step.run_id) {
    if (step.position === 0) return "This version";
    return step.date ? `the ${formatDay(step.date)} version` : "an earlier version";
  }
  // Name the workspace (and the opp, if it differs) only when the step is
  // not where this run lives — a clone's source.
  const otherWs = !!head && !!step.workspace && step.workspace !== head.workspace;
  const otherOpp = !!head && !!step.opp && step.opp !== head.opp;
  const prefix = `${otherWs ? `${step.workspace} / ` : ""}${otherOpp ? `${step.opp} / ` : ""}`;
  return `${prefix}${step.run_id}${step.position === 0 ? " (this run)" : ""}`;
}

/**
 * How `step` was made from the step after it (older), as the connective
 * the strip draws between them.
 */
export function viaPhrase(step: LineageStep, plain: boolean): string {
  const stage = step.stage;
  switch (step.via) {
    case "cloned":
      return plain ? "a copy of" : "cloned from";
    case "forked":
      if (plain) return stage ? `redone from the ${stage} stage, building on` : "building on";
      return stage ? `forked at ${stage} from` : "forked from";
    case "seeded":
      if (plain) return stage ? `redone from the ${stage} stage, building on` : "building on";
      return stage ? `seeded at ${stage} from` : "seeded from";
    default:
      return "";
  }
}

/** The filter buckets — "reaffirmed" reads as carried (the value came forward). */
export type LineageFilter = "all" | "carried" | "new" | "changed" | "human";

export interface EditLike {
  decided_by_name?: string;
  decided_at?: string;
  is_revert?: boolean;
  confirmed?: boolean;
}

/**
 * A human edit saved since the run (`inputs/decision-overrides.yaml`) beats
 * whatever the run's log says: the row's value is now a person's.
 */
function humanEdit(edit: EditLike | undefined): boolean {
  return !!edit && !edit.is_revert && !edit.confirmed;
}

export function filterBucket(origin: DecisionOrigin | undefined, edit?: EditLike): LineageFilter {
  if (humanEdit(edit)) return "human";
  if (!origin) return "new";
  if (origin.kind === "reaffirmed") return "carried";
  return origin.kind;
}

export function filterCounts(
  ids: readonly string[],
  lineage: DecisionLineage,
  edits: Record<string, EditLike> = {},
): Record<Exclude<LineageFilter, "all">, number> {
  const out = { carried: 0, new: 0, changed: 0, human: 0 };
  for (const id of ids) out[filterBucket(lineage.origins[id], edits[id]) as keyof typeof out] += 1;
  return out;
}

export function hasAncestors(lineage: DecisionLineage | null | undefined): boolean {
  return !!lineage && lineage.chain.length > 1;
}

export interface Badge {
  label: string;
  tone: "neutral" | "sky" | "amber" | "emerald" | "violet";
  title: string;
}

/**
 * The per-decision origin badge, or null when there is nothing worth
 * saying ("new" on a run with no earlier runs would sit on every row).
 */
export function originBadge(
  origin: DecisionOrigin | undefined,
  lineage: DecisionLineage,
  plain: boolean,
  edit?: EditLike,
): Badge | null {
  if (humanEdit(edit)) {
    const who = edit?.decided_by_name || "a person";
    const when = formatDay(edit?.decided_at);
    return {
      label: `set by ${who}${when ? ` on ${when}` : ""}`,
      tone: "sky",
      title: "A person changed this answer after the run",
    };
  }
  if (!origin) return null;
  const from = origin.from_position != null ? lineage.chain[origin.from_position] : undefined;
  const head = lineage.chain[0];
  const fromName = plain || !origin.from_run
    ? (from?.date ? `the ${formatDay(from.date)} version` : "an earlier version")
    : from && head && from.workspace && from.workspace !== head.workspace
      ? `${from.workspace} / ${origin.from_run}`
      : origin.from_run;
  switch (origin.kind) {
    case "human": {
      const who = origin.by || "a person";
      const when = formatDay(origin.at);
      return {
        label: `set by ${who}${when ? ` on ${when}` : ""}`,
        tone: "sky",
        title: "A person ruled on this — an override or a human decision",
      };
    }
    case "new":
      if (!hasAncestors(lineage)) return null;
      return {
        label: plain ? "new in this version" : "new in this run",
        tone: "violet",
        title: "No earlier run has this decision",
      };
    case "carried":
      return {
        label: plain ? `carried over unchanged from ${fromName}` : `carried from ${fromName} unchanged`,
        tone: "neutral",
        title: "Copied forward from an earlier run with the same value",
      };
    case "reaffirmed":
      return {
        label: plain ? "re-affirmed in this version" : `re-affirmed (same as ${fromName})`,
        tone: "emerald",
        title: "This run decided it again and reached the same value",
      };
    case "changed":
      return {
        label: plain ? "changed in this version" : `carried from ${fromName}, changed here`,
        tone: "amber",
        title: origin.previous_value
          ? `Was: ${origin.previous_value}`
          : "An earlier run had a different value",
      };
    default:
      return null;
  }
}

/** A history entry's run, for members: its id, prefixed when in another workspace. */
export function entryLabel(entry: DecisionHistoryEntry, headWorkspace: string | null): string {
  const prefix = headWorkspace && entry.workspace !== headWorkspace ? `${entry.workspace} / ` : "";
  return `${prefix}${entry.run_id}`;
}

/** Where a linked history entry opens: the run's Workbench. */
export function entryHref(entry: DecisionHistoryEntry): string | null {
  if (!entry.linked) return null;
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return `${base}/w/${encodeURIComponent(entry.workspace)}/opps/${encodeURIComponent(
    entry.opp,
  )}/runs/${encodeURIComponent(entry.run_id)}`;
}
