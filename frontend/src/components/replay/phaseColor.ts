/**
 * Phase → colour, stable across every act.
 *
 * The spectrum is information: a run has up to ten phases and they have to be
 * told apart at a glance on the time band, so a single accent wouldn't do the
 * job. Ten hues, one per phase, walking the wheel. Assignment is by order of first appearance in the run, so the same
 * phase keeps its colour on the band, in the ledger and in the event log.
 */
const SPECTRUM = [
  "var(--demo-phase-1)",
  "var(--demo-phase-2)",
  "var(--demo-phase-3)",
  "var(--demo-phase-4)",
  "var(--demo-phase-5)",
  "var(--demo-phase-6)",
  "var(--demo-phase-7)",
  "var(--demo-phase-8)",
  "var(--demo-phase-9)",
  "var(--demo-phase-10)",
] as const;

export function buildPhasePalette(phases: readonly string[]): Map<string, string> {
  const palette = new Map<string, string>();
  phases.forEach((phase, index) => {
    if (!palette.has(phase)) {
      palette.set(phase, SPECTRUM[palette.size % SPECTRUM.length]);
    }
    void index;
  });
  return palette;
}

export function phaseColor(palette: Map<string, string>, phase: string | null | undefined): string {
  if (!phase) return "var(--demo-dim)";
  return palette.get(phase) ?? "var(--demo-dim)";
}
