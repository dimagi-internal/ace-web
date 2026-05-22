import type { Decision, PhaseInfo } from "@/api/types.ws";
import type { EditOp } from "./decisionsReducer";

interface Args {
  decisions: readonly Decision[];
  edits: readonly EditOp[];
  phases: readonly PhaseInfo[];
}

/** Default fork point = lowest phase ordinal across all edited rows.
 * Returns null when no edits or no edits map to known phases. */
export function computeForkPoint({ decisions, edits, phases }: Args): string | null {
  if (edits.length === 0) return null;

  const decisionById = new Map(decisions.map((d) => [d.id, d]));
  const ordinalByPhase = new Map(phases.map((p) => [p.name, p.ordinal]));

  let bestOrd: number | null = null;
  let bestName: string | null = null;

  for (const edit of edits) {
    const decision = decisionById.get(edit.row_id);
    if (!decision) continue;
    const ord = ordinalByPhase.get(decision.phase);
    if (ord === undefined) continue;
    if (bestOrd === null || ord < bestOrd) {
      bestOrd = ord;
      bestName = decision.phase;
    }
  }

  return bestName;
}
