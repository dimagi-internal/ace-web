import type {
  DecisionHistoryEntry,
  DecisionLineage,
  DecisionOrigin,
  LineageStep,
} from "@/api/lineage";

/**
 * Words for decision lineage, in one place, for both readers:
 *
 * - a MEMBER reads run ids ("decided by ACE in run 20260925-1536 (25 Sep),
 *   carried unchanged");
 * - an outside reader (`plain`) reads versions and dates ("decided by ACE in
 *   the 25 Sep 2026 version, carried over unchanged") — no run plumbing.
 *
 * Every origin says WHO decided and WHERE (run + date). A clone is the same
 * run copied into another workspace, never "an earlier run": it is described
 * only as "copied into this workspace on <date>".
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-25" → "25 Sep 2026"; "" stays "". Never shifts across time zones. */
export function formatDay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "";
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

/** "2026-09-25" → "25 Sep" — the short form badges use. */
export function shortDay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "";
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}`;
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
    case "cloned": {
      // A clone is the same run, copied — not a run that came after it.
      const on = step.copied_date ? ` on ${formatDay(step.copied_date)}` : "";
      if (plain) return `copied${on} from`;
      const into =
        step.position === 0 || !step.workspace ? "this workspace" : step.workspace;
      return `copied into ${into}${on} from`;
    }
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

/**
 * The filter buckets. "decided" reads as new (decided in this run — a clone
 * and its source are one run); "reaffirmed" reads as carried (the value came
 * forward). Every kind lands in exactly one bucket, so the counts add up.
 */
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
  if (origin.kind === "decided") return "new";
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

/**
 * Did a decision's value stay the same from `prev` to `entry`? The one
 * comparison behind the history's "(unchanged)" marker, so the marker and
 * the decision to show the history at all can never disagree. A missing
 * value on either side is not "the same".
 */
export function sameValue(
  prev: DecisionHistoryEntry | undefined,
  entry: DecisionHistoryEntry,
): boolean {
  return (
    prev?.value != null &&
    entry.value != null &&
    prev.value.trim().toLowerCase() === entry.value.trim().toLowerCase()
  );
}

/**
 * Did the value ever change across the runs a decision was found in? A
 * cloned run carries every decision over verbatim — "How this decision
 * evolved" over two identical entries reads as a change that never
 * happened, so the history is drawn only when this is true.
 */
export function valueEverChanged(entries: readonly DecisionHistoryEntry[]): boolean {
  const found = entries.filter((e) => e.found);
  return found.some((e, i) => i > 0 && !sameValue(found[i - 1], e));
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
  if (origin.kind === "human") {
    const who = origin.by || "a person";
    const when = formatDay(origin.at);
    return {
      label: `set by ${who}${when ? ` on ${when}` : ""}`,
      tone: "sky",
      title: "A person ruled on this — an override or a human decision",
    };
  }
  const head = lineage.chain[0];
  const inPos =
    origin.in_position ?? (origin.kind === "decided" ? origin.from_position : 0) ?? 0;
  const inStep = lineage.chain[inPos];
  const fromStep = origin.from_position != null ? lineage.chain[origin.from_position] : undefined;

  /** "this run (4 Oct)" / "run 20260925-1536 (25 Sep)" — or, plain, a version. */
  const ref = (step: LineageStep | undefined, runId: string | null | undefined): string => {
    if (plain || !runId) {
      if (step?.position === 0) return "this version";
      return step?.date ? `the ${formatDay(step.date)} version` : "an earlier version";
    }
    const day = shortDay(step?.date);
    const name = step?.position === 0 ? "this run" : `run ${runId}`;
    return day ? `${name} (${day})` : name;
  };
  /** The full name for a tooltip: workspace, run id and day. */
  const full = (step: LineageStep | undefined, runId: string | null | undefined): string => {
    if (plain || !runId) return ref(step, runId);
    const ws = step?.workspace ? `${step.workspace} / ` : "";
    const day = formatDay(step?.date);
    return `${ws}${runId}${day ? ` (${day})` : ""}`;
  };
  const inRun = origin.in_run ?? (inPos === 0 ? head?.run_id : origin.from_run);
  const copied = head?.via === "cloned" ? head : undefined;
  const copyNote = copied
    ? ` This run is a copy of it${copied.copied_date ? `, made on ${formatDay(copied.copied_date)}` : ""} — copying is not a decision.`
    : "";

  switch (origin.kind) {
    case "new":
      if (!hasAncestors(lineage)) return null;
      return {
        label: `decided by ACE in ${ref(head, head?.run_id)}`,
        tone: "violet",
        title: "No earlier run has this decision: ACE decided it here",
      };
    case "decided":
      return {
        label: `decided by ACE in ${ref(inStep, inRun)}`,
        tone: "neutral",
        title: `ACE decided this in ${full(inStep, inRun)}.${copyNote}`,
      };
    case "carried":
      return {
        label: plain
          ? `decided by ACE in ${ref(fromStep, origin.from_run)}, carried over unchanged`
          : `decided by ACE in ${ref(fromStep, origin.from_run)}, carried unchanged`,
        tone: "neutral",
        title: `ACE decided this in ${full(fromStep, origin.from_run)}; every run since kept the same answer`,
      };
    case "reaffirmed":
      return {
        label: plain
          ? `re-checked in ${ref(inStep, inRun)}, unchanged`
          : `re-decided in ${ref(inStep, inRun)}, same answer as ${ref(fromStep, origin.from_run)}`,
        tone: "emerald",
        title: `A re-run in ${full(inStep, inRun)} decided this again and reached the same answer as ${full(fromStep, origin.from_run)}`,
      };
    case "changed": {
      const was = origin.previous_value ? ` Was: ${origin.previous_value}` : "";
      if (origin.on_copy) {
        const day = (plain ? formatDay : shortDay)(copied?.copied_date);
        return {
          label: plain
            ? "changed by ACE when this copy was made"
            : `changed by ACE when copied into this workspace${day ? ` (${day})` : ""}`,
          tone: "amber",
          title: `Copying ${full(fromStep, origin.from_run)} into this workspace changed this answer.${was}`,
        };
      }
      return {
        label: plain
          ? `changed by ACE in ${ref(inStep, inRun)}`
          : `changed by ACE in ${ref(inStep, inRun)}, was different in ${ref(fromStep, origin.from_run)}`,
        tone: "amber",
        title: `ACE decided this differently in ${full(inStep, inRun)} than in ${full(fromStep, origin.from_run)}.${was}`,
      };
    }
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
