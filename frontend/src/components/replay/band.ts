import type { DemoEvent, DemoTimeline } from "@/api/replay";

export interface BandSegment {
  readonly phase: string;
  readonly label: string;
  /** Fraction of the band, 0..1. */
  readonly start: number;
  readonly width: number;
}

export interface BandTick {
  readonly at: number;
  readonly skill: string;
  readonly phase: string;
  readonly failed: boolean;
}

const FAILED = new Set(["qa-failed", "judge-fail", "error"]);

export function stepFailed(event: DemoEvent): boolean {
  if (event.status && FAILED.has(event.status)) return true;
  if (event.judge?.passed === false) return true;
  const verdict = event.qa_result?.verdict;
  return verdict === "fail" || event.qa_result?.passed === false;
}

/**
 * Lay the run out along the band.
 *
 * Whenever there is a clock — step-level or phase-level — each phase occupies
 * its real share of the run, which is the point: an audience sees at a glance
 * that one phase ate half the day. With no clock at all, phases are spaced by
 * step count and the caller suppresses the clock, so nobody reads proportions
 * that aren't there.
 */
export function bandSegments(timeline: DemoTimeline): BandSegment[] {
  const { events, wall_seconds: wall, timing_source: timing } = timeline;
  const order: string[] = [];
  const labels = new Map<string, string>();
  const spans = new Map<string, { from: number; to: number }>();
  const counts = new Map<string, number>();

  for (const event of events) {
    if (!order.includes(event.phase)) {
      order.push(event.phase);
      labels.set(event.phase, event.phase_display || event.phase);
    }
    if (event.kind === "step_end") {
      counts.set(event.phase, (counts.get(event.phase) ?? 0) + 1);
    }
    if (event.t !== null) {
      const current = spans.get(event.phase);
      spans.set(
        event.phase,
        current
          ? { from: Math.min(current.from, event.t), to: Math.max(current.to, event.t) }
          : { from: event.t, to: event.t },
      );
    }
  }

  if (timing !== "ordinal" && wall && wall > 0) {
    return order.map((phase) => {
      const span = spans.get(phase);
      const from = span ? span.from / wall : 0;
      const to = span ? span.to / wall : 0;
      return {
        phase,
        label: labels.get(phase) ?? phase,
        start: from,
        // A phase whose steps all share one timestamp still needs to be seen.
        width: Math.max(to - from, 0.006),
      };
    });
  }

  const totalSteps = order.reduce((sum, phase) => sum + (counts.get(phase) ?? 1), 0) || 1;
  let cursor = 0;
  return order.map((phase) => {
    const width = (counts.get(phase) ?? 1) / totalSteps;
    const segment = { phase, label: labels.get(phase) ?? phase, start: cursor, width };
    cursor += width;
    return segment;
  });
}

export function bandTicks(timeline: DemoTimeline): BandTick[] {
  const { events, wall_seconds: wall, timing_source: timing } = timeline;
  const ends = events.filter((e) => e.kind === "step_end");
  if (timing !== "ordinal" && wall && wall > 0) {
    return ends
      .filter((e) => e.t !== null)
      .map((e) => ({
        at: (e.t as number) / wall,
        skill: e.skill ?? "",
        phase: e.phase,
        failed: stepFailed(e),
      }));
  }
  return ends.map((e, index) => ({
    at: ends.length > 1 ? index / (ends.length - 1) : 0,
    skill: e.skill ?? "",
    phase: e.phase,
    failed: stepFailed(e),
  }));
}

/** How far through the run the playhead sits, in seconds of run time. */
/** How far through the run the playhead sits, in seconds of run time.
 *
 * Available in `phase` mode too: the run's start and end are measured even
 * when its individual steps are not. */
export function runElapsed(timeline: DemoTimeline, progress: number): number | null {
  if (timeline.timing_source === "ordinal" || !timeline.wall_seconds) return null;
  return progress * timeline.wall_seconds;
}

/** Events the playhead has already passed. */
export function revealedEvents(timeline: DemoTimeline, progress: number): DemoEvent[] {
  const { events, wall_seconds: wall, timing_source: timing } = timeline;
  if (timing !== "ordinal" && wall && wall > 0) {
    const cutoff = progress * wall;
    return events.filter((e) => e.t === null || e.t <= cutoff);
  }
  const cutoff = progress * Math.max(0, events.length - 1);
  return events.filter((e) => e.seq <= cutoff);
}
