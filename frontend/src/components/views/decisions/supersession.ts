import type { Decision } from "@/api/types.ws";

/**
 * Live choices vs. history in a run's decisions log.
 *
 * A row carrying `superseded_by` is history, not a choice the run stands
 * behind: a later row corrected it in-run (ace#1421), or a fork retired it
 * because the fork re-runs its phase (ace#2582 / ace-web#848). The public
 * summary drops such rows server-side; the Phases panel keeps them reachable
 * as earlier versions folded under the live row that replaced them.
 *
 * `earlierBy` maps a LIVE row id to the rows it replaced, nearest first (the
 * row it directly replaced, then that row's predecessor, …). A chain whose end
 * is not a live row in this log — a fork that retired a phase it has not
 * re-run yet, or a dangling id — lands in `retired`: still history, still
 * shown, just with no live row to sit under.
 */
export interface SupersessionSplit {
  live: Decision[];
  earlierBy: Map<string, Decision[]>;
  retired: Decision[];
}

export const isSuperseded = (d: Decision): boolean => Boolean(d.superseded_by);

export function liveDecisions(decisions: readonly Decision[]): Decision[] {
  return decisions.filter((d) => !isSuperseded(d));
}

export function splitSuperseded(decisions: readonly Decision[]): SupersessionSplit {
  const live = liveDecisions(decisions);
  const liveIds = new Set(live.map((d) => d.id));
  const byId = new Map<string, Decision>();
  for (const d of decisions) if (!byId.has(d.id)) byId.set(d.id, d);

  const withDepth = new Map<string, { row: Decision; depth: number }[]>();
  const retired: Decision[] = [];
  for (const d of decisions) {
    if (!isSuperseded(d)) continue;
    // Follow the chain to the live row at its end; a cycle or a dangling id
    // means there is no live successor.
    let target = d.superseded_by ?? "";
    let depth = 1;
    const seen = new Set<string>([d.id]);
    while (target && !liveIds.has(target)) {
      const next = byId.get(target);
      if (!next || seen.has(target) || !next.superseded_by) {
        target = "";
        break;
      }
      seen.add(target);
      target = next.superseded_by;
      depth += 1;
    }
    if (target && liveIds.has(target)) {
      const arr = withDepth.get(target) ?? [];
      arr.push({ row: d, depth });
      withDepth.set(target, arr);
    } else {
      retired.push(d);
    }
  }

  const earlierBy = new Map<string, Decision[]>();
  for (const [id, rows] of withDepth) {
    earlierBy.set(
      id,
      rows
        .map((r, i) => ({ ...r, i }))
        .sort((a, b) => a.depth - b.depth || a.i - b.i)
        .map((r) => r.row),
    );
  }
  return { live, earlierBy, retired };
}
