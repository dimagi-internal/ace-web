/**
 * ACE's phases, one level up — what an outsider can hold in their head.
 *
 * Ten phases is a lot for someone who doesn't know Dimagi's products; the
 * three that each stand up a product (CommCare apps, Connect, the chatbot)
 * read to them as one thing, "product setup" (Andrea's framing). The step
 * track labels these groups ABOVE the phases rather than replacing them, so
 * the presenter can still point at Phase 3.
 *
 * Phase names are the plugin's (they're dynamic). A phase this map doesn't
 * know is left ungrouped rather than guessed into a neighbour.
 */
export const PHASE_GROUPS: readonly { readonly label: string; readonly phases: readonly string[] }[] = [
  { label: "Design", phases: ["idea-to-design", "design", "scenarios-and-acceptance"] },
  { label: "Product setup", phases: ["commcare-setup", "connect-setup", "ocs-setup"] },
  { label: "Training & demo", phases: ["qa-and-training", "synthetic-data-and-workflows"] },
  {
    label: "Partner & launch",
    phases: ["solicitation-management", "execution-management", "closeout"],
  },
];

const GROUP_OF = new Map(
  PHASE_GROUPS.flatMap((g) => g.phases.map((p) => [p, g.label] as const)),
);

export function phaseGroupOf(phase: string): string | null {
  return GROUP_OF.get(phase) ?? null;
}

export interface GroupSpan {
  /** Null for a run of phases no group claims. */
  readonly label: string | null;
  /** Index of the first phase in the span. */
  readonly from: number;
  readonly count: number;
}

/** Consecutive phases that share a group, in order. */
export function groupSpans(phases: readonly string[]): GroupSpan[] {
  const out: GroupSpan[] = [];
  phases.forEach((phase, i) => {
    const label = phaseGroupOf(phase);
    const last = out.at(-1);
    if (last && last.label === label) {
      out[out.length - 1] = { ...last, count: last.count + 1 };
    } else {
      out.push({ label, from: i, count: 1 });
    }
  });
  return out;
}
