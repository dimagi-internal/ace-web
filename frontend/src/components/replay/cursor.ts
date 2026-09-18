import type { DemoEvent, DemoTimeline, LadderPhase, LadderStep } from "@/api/replay";

/**
 * The beat cursor — what the player is pointing at right now.
 *
 * Every event in the run is one beat, and each kind means something different
 * on screen. That is what makes the player steppable at sub-step granularity
 * without inventing a second data model:
 *
 *   phase_start — the phase lights up; we say what it is about to do
 *   step_start  — the skill is marked running
 *   step_end    — its artifacts, QA result and judge verdict land
 *
 * Arrow keys move the cursor one beat. Playback moves it on the clock. Both
 * end up in the same place, so a presenter can stop mid-run and step.
 */
export interface Beat {
  readonly index: number;
  readonly event: DemoEvent | null;
  readonly phase: string | null;
  readonly skill: string | null;
}

/** The beat the playhead has reached at `progress`. */
export function beatAt(timeline: DemoTimeline, progress: number): Beat {
  const events = timeline.events;
  if (events.length === 0) return { index: -1, phase: null, skill: null, event: null };

  const { wall_seconds: wall, timing_source: timing } = timeline;
  let index = -1;
  if (timing !== "ordinal" && wall && wall > 0) {
    const cutoff = progress * wall;
    for (let i = 0; i < events.length; i += 1) {
      const t = events[i].t;
      if (t === null || t <= cutoff) index = i;
      else break;
    }
  } else {
    index = Math.min(events.length - 1, Math.floor(progress * (events.length - 1)));
  }
  if (index < 0) return { index: -1, phase: null, skill: null, event: null };
  const event = events[index];
  return { index, event, phase: event.phase ?? null, skill: event.skill ?? null };
}

/** The progress value that lands the playhead exactly on `index`. */
export function progressForBeat(timeline: DemoTimeline, index: number): number {
  const events = timeline.events;
  if (events.length === 0) return 0;
  const clamped = Math.min(events.length - 1, Math.max(0, index));
  const { wall_seconds: wall, timing_source: timing } = timeline;
  if (timing !== "ordinal" && wall && wall > 0) {
    const t = events[clamped].t;
    if (t !== null) return Math.min(1, Math.max(0, t / wall));
    // No offset for this event — fall back to its sequence position.
  }
  return events.length > 1 ? clamped / (events.length - 1) : 1;
}

/** Index of the first beat belonging to a given skill's completion. */
export function beatForSkill(timeline: DemoTimeline, skill: string): number {
  return timeline.events.findIndex((e) => e.kind === "step_end" && e.skill === skill);
}

export interface Reveal {
  /** Skills whose step_end the cursor has passed — fully filled in. */
  readonly done: ReadonlySet<string>;
  /** Skills started but not yet finished at the cursor. */
  readonly running: ReadonlySet<string>;
  /** Phases the cursor has entered. */
  readonly phases: ReadonlySet<string>;
}

/** What the ladder should show as already having happened. */
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
