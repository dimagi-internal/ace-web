import type { DemoEvent, DemoTimeline, LadderPhase, LadderStep } from "@/api/replay";

/**
 * The step cursor — which beat of the run the replay is showing.
 *
 * Replay is a STEP-THROUGH, not a clock. Real runs span many hours with long
 * idle gaps (one phase of hh-poverty-targeting/20260722-1341 holds 82% of its
 * elapsed time), so any time-proportional playback spends most of its length
 * showing nothing change. Every beat gets the same weight instead:
 *
 *   phase_start — the phase lights up
 *   step_start  — the skill is marked running
 *   step_end    — its artifacts, QA result and judge verdict land
 *
 * Next / Prev move one beat; Play advances one beat on a short delay. All of
 * them move the same integer, so manual stepping and auto-play never disagree.
 */
export interface Beat {
  readonly index: number;
  readonly event: DemoEvent | null;
  readonly phase: string | null;
  readonly skill: string | null;
}

export const NO_BEAT: Beat = { index: -1, event: null, phase: null, skill: null };

/** The beat at `index`, clamped into the run. */
export function beatAtIndex(timeline: DemoTimeline, index: number): Beat {
  const events = timeline.events;
  if (events.length === 0 || index < 0) return NO_BEAT;
  const i = Math.min(events.length - 1, index);
  const event = events[i];
  return { index: i, event, phase: event.phase ?? null, skill: event.skill ?? null };
}

export interface Reveal {
  /** Skills whose step_end the cursor has passed — fully filled in. */
  readonly done: ReadonlySet<string>;
  /** Skills started but not yet finished at the cursor. */
  readonly running: ReadonlySet<string>;
  /** Phases the cursor has entered. */
  readonly phases: ReadonlySet<string>;
}

export const EMPTY_REVEAL: Reveal = {
  done: new Set<string>(),
  running: new Set<string>(),
  phases: new Set<string>(),
};

/** What the Phases screen should show as already having happened. */
export function revealAt(timeline: DemoTimeline, beatIndex: number): Reveal {
  const done = new Set<string>();
  const running = new Set<string>();
  const phases = new Set<string>();
  timeline.events.slice(0, Math.max(0, beatIndex + 1)).forEach((e) => {
    if (e.phase) phases.add(e.phase);
    if (!e.skill) return;
    if (e.kind === "step_start") running.add(e.skill);
    if (e.kind === "step_end") {
      running.delete(e.skill);
      done.add(e.skill);
    }
  });
  return { done, running, phases };
}

/** Index of the beat where `skill` finished, or -1. */
export function beatForSkill(timeline: DemoTimeline, skill: string): number {
  return timeline.events.findIndex((e) => e.kind === "step_end" && e.skill === skill);
}

/** Did this finished step fail its own QA or judge? */
export function stepFailed(event: DemoEvent): boolean {
  if (event.status && ["qa-failed", "judge-fail", "error"].includes(event.status)) return true;
  if (event.judge?.passed === false) return true;
  return event.qa_result?.verdict === "fail" || event.qa_result?.passed === false;
}

/** Find a ladder step by skill name. */
export function findLadderStep(
  ladder: readonly LadderPhase[],
  skill: string | null,
): { phase: LadderPhase; step: LadderStep } | null {
  if (!skill) return null;
  for (const phase of ladder) {
    const step = phase.steps.find((s) => s.skill === skill);
    if (step) return { phase, step };
  }
  return null;
}
