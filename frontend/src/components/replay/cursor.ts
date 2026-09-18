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

/**
 * Where each beat sits along the run, 0..1 — the playhead's stopping points.
 *
 * Playback walks these at a STEADY pace rather than sweeping the clock
 * linearly, and the difference is the whole readability of the act. On a real
 * run the phase spans are wildly uneven: on hh-poverty-targeting/20260722-1341
 * one phase holds 82% of the elapsed time, so a linear sweep spends five
 * sixths of the demo crawling through a single phase while nothing visible
 * changes. Equal time per beat gives every step its moment.
 *
 * The BAND stays proportional — that is the evidence, and it still shows that
 * one phase ate the day. Only the pacing is redistributed, and the clock still
 * reads the real run time wherever the playhead lands.
 */
export function beatStops(timeline: DemoTimeline): number[] {
  return timeline.events.map((_, i) => progressForBeat(timeline, i));
}

/** Uniform playback position (0..1) → position along the run (0..1). */
export function paceToProgress(stops: readonly number[], t: number): number {
  if (stops.length === 0) return 0;
  if (stops.length === 1) return stops[0];
  const scaled = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(scaled));
  const frac = scaled - i;
  return stops[i] + (stops[i + 1] - stops[i]) * frac;
}

/** The inverse: a scrub on the band → the uniform position that lands there. */
export function progressToPace(stops: readonly number[], progress: number): number {
  if (stops.length < 2) return 0;
  const p = Math.min(1, Math.max(0, progress));
  for (let i = 0; i < stops.length - 1; i += 1) {
    const lo = stops[i];
    const hi = stops[i + 1];
    if (p <= hi) {
      const frac = hi === lo ? 0 : (p - lo) / (hi - lo);
      return (i + Math.min(1, Math.max(0, frac))) / (stops.length - 1);
    }
  }
  return 1;
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
