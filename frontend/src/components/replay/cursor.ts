import type {
  DemoEvent,
  DemoTimeline,
  LadderPhase,
  LadderStep,
  ReplayProduct,
} from "@/api/replay";
import type { Artifact, Step } from "@/api/types.ws";

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

// ─── What the run built, and when ────────────────────────────────────

/**
 * The beat at which a product appears. A product no beat places (its phase
 * recorded no steps — a fork's carried phases) appears at the final beat:
 * it exists by the end of the run, and nowhere earlier can honestly claim it.
 */
export function revealIndexOf(product: ReplayProduct, total: number): number {
  return product.reveal_seq ?? Math.max(0, total - 1);
}

/** Products brought into being at exactly this beat — the spotlight's cue. */
export function productsAtBeat(timeline: DemoTimeline, index: number): ReplayProduct[] {
  const total = timeline.events.length;
  return (timeline.products ?? []).filter((p) => revealIndexOf(p, total) === index);
}

/** Phases whose last step has finished by `beatIndex`. A decision with no
 *  skill of its own lands when its phase does. */
export function phasesFinishedAt(timeline: DemoTimeline, beatIndex: number): Set<string> {
  const lastEnd = new Map<string, number>();
  timeline.events.forEach((e, i) => {
    if (e.kind === "step_end") lastEnd.set(e.phase, i);
  });
  const out = new Set<string>();
  for (const [phase, i] of lastEnd) if (i <= beatIndex) out.add(phase);
  return out;
}

/**
 * The markdown documents a step wrote — the other thing, besides products,
 * worth popping up as a step finishes (an app's build summary, the chatbot's
 * QA transcript, an eval report). Files already shown as products are left
 * to the product pop-up rather than shown twice.
 */
export function stepDocuments(
  step: Step | undefined,
  alreadyShown: ReadonlySet<string> = new Set(),
): Artifact[] {
  if (!step) return [];
  return step.artifacts.filter(
    (a) => /\.(md|markdown)$/i.test(a.name || a.path) && !alreadyShown.has(a.drive_file_id),
  );
}

/**
 * The beats worth stopping on when the presenter wants to move fast: every
 * phase start, and every finish that revealed a product, failed, or belongs
 * to a notable skill (one that recorded decisions or wrote a document).
 * Ascending. The final beat is always included so Play ends on the finished
 * run.
 */
export function highlightBeats(
  timeline: DemoTimeline,
  notableSkills: ReadonlySet<string> = new Set(),
): number[] {
  const total = timeline.events.length;
  const revealing = new Set((timeline.products ?? []).map((p) => revealIndexOf(p, total)));
  const out: number[] = [];
  timeline.events.forEach((e, i) => {
    if (e.kind === "phase_start") out.push(i);
    else if (
      e.kind === "step_end" &&
      (revealing.has(i) || stepFailed(e) || (e.skill != null && notableSkills.has(e.skill)))
    ) {
      out.push(i);
    }
  });
  if (total > 0 && out[out.length - 1] !== total - 1) out.push(total - 1);
  return out;
}
