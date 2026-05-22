import { useMemo } from "react";

import type { Decision } from "@/api/types.ws";
import type { EditOp } from "./decisionsReducer";
import { useSkillProducts } from "./useSkillProducts";

interface Args {
  decisions: readonly Decision[];
  edits: readonly EditOp[];
  skillProducts: Record<string, string[]>;
}

/** Pure: given edits, decisions, and the manifest map, return the unique
 * set of artifact paths the forked re-run will regenerate. Returns [] when
 * no edits, or when none of the edited rows' producer skills are known.
 *
 * The crosswalk keys off `decision.skill` (the producer-skill slug, e.g.
 * "idea-to-pdd"). Don't confuse with `decision.source`, which is a
 * free-text human description of where the question came from. */
export function computeAffectedDocs({ decisions, edits, skillProducts }: Args): string[] {
  if (edits.length === 0) return [];

  const decisionById = new Map(decisions.map((d) => [d.id, d]));
  const seen = new Set<string>();

  for (const edit of edits) {
    const decision = decisionById.get(edit.row_id);
    if (!decision) continue;
    const paths = skillProducts[decision.skill] ?? [];
    for (const p of paths) seen.add(p);
  }

  return Array.from(seen);
}

/** Hook wrapper: pulls the skill-products map and computes affected docs. */
export function useAffectedDocs(args: {
  decisions: readonly Decision[];
  edits: readonly EditOp[];
}): string[] {
  const skillProducts = useSkillProducts();
  return useMemo(() => {
    if (skillProducts === null) return [];
    return computeAffectedDocs({
      decisions: args.decisions,
      edits: args.edits,
      skillProducts,
    });
  }, [args.decisions, args.edits, skillProducts]);
}
