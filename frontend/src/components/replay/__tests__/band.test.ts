import { describe, expect, it } from "vitest";

import type { DemoEvent, DemoTimeline } from "@/api/replay";
import {
  bandSegments,
  bandTicks,
  revealedEvents,
  runElapsed,
  stepFailed,
} from "../band";

function evt(partial: Partial<DemoEvent> & Pick<DemoEvent, "seq" | "kind" | "phase">): DemoEvent {
  return {
    t: null,
    phase_display: partial.phase,
    ...partial,
  } as DemoEvent;
}

/** design: 0-1800s, commcare: 3000-7200s. Total wall 7200s. */
function measured(): DemoTimeline {
  return {
    timing_source: "measured",
    origin: "2026-07-22T13:41:00Z",
    wall_seconds: 7200,
    ladder: [],
    events: [
      evt({ seq: 0, kind: "phase_start", phase: "design", t: 0 }),
      evt({ seq: 1, kind: "step_start", phase: "design", t: 0, skill: "a" }),
      evt({ seq: 2, kind: "step_end", phase: "design", t: 1800, skill: "a", status: "complete" }),
      evt({ seq: 3, kind: "phase_start", phase: "commcare", t: 3000 }),
      evt({ seq: 4, kind: "step_start", phase: "commcare", t: 3000, skill: "b" }),
      evt({ seq: 5, kind: "step_end", phase: "commcare", t: 7200, skill: "b", status: "complete" }),
    ],
  };
}

function ordinal(): DemoTimeline {
  return {
    timing_source: "ordinal",
    origin: null,
    wall_seconds: null,
    ladder: [],
    events: [
      evt({ seq: 0, kind: "phase_start", phase: "design" }),
      evt({ seq: 1, kind: "step_start", phase: "design", skill: "a" }),
      evt({ seq: 2, kind: "step_end", phase: "design", skill: "a", status: "complete" }),
      evt({ seq: 3, kind: "step_start", phase: "design", skill: "b" }),
      evt({ seq: 4, kind: "step_end", phase: "design", skill: "b", status: "complete" }),
    ],
  };
}

describe("bandSegments", () => {
  it("gives each phase its real share of the run when timing is measured", () => {
    const [design, commcare] = bandSegments(measured());
    expect(design.start).toBeCloseTo(0);
    expect(design.width).toBeCloseTo(0.25); // 0 -> 1800 of 7200
    expect(commcare.start).toBeCloseTo(3000 / 7200);
    expect(commcare.width).toBeCloseTo((7200 - 3000) / 7200);
  });

  it("keeps a zero-length phase visible rather than collapsing it", () => {
    const timeline: DemoTimeline = {
      ...measured(),
      events: [evt({ seq: 0, kind: "step_end", phase: "solo", t: 100, skill: "a" })],
    };
    expect(bandSegments(timeline)[0].width).toBeGreaterThan(0);
  });

  it("spaces phases by step count when there is no timing to read", () => {
    const segments = bandSegments(ordinal());
    expect(segments).toHaveLength(1);
    expect(segments[0].width).toBeCloseTo(1);
  });

  it("lays ordinal segments end to end without gaps or overlap", () => {
    const timeline: DemoTimeline = {
      ...ordinal(),
      events: [
        evt({ seq: 0, kind: "step_end", phase: "one", skill: "a" }),
        evt({ seq: 1, kind: "step_end", phase: "two", skill: "b" }),
        evt({ seq: 2, kind: "step_end", phase: "two", skill: "c" }),
      ],
    };
    const segments = bandSegments(timeline);
    expect(segments[0].start).toBeCloseTo(0);
    expect(segments[0].start + segments[0].width).toBeCloseTo(segments[1].start);
    const last = segments.at(-1)!;
    expect(last.start + last.width).toBeCloseTo(1);
  });
});

describe("bandTicks", () => {
  it("places a tick at each step's real completion", () => {
    const ticks = bandTicks(measured());
    expect(ticks.map((t) => t.at)).toEqual([0.25, 1]);
  });

  it("spreads ticks evenly without timing", () => {
    const ticks = bandTicks(ordinal());
    expect(ticks.map((t) => t.at)).toEqual([0, 1]);
  });
});

describe("stepFailed", () => {
  it("flags a failing judge", () => {
    expect(stepFailed(evt({ seq: 0, kind: "step_end", phase: "p", judge: { passed: false } }))).toBe(true);
  });
  it("flags a failing QA verdict", () => {
    expect(
      stepFailed(evt({ seq: 0, kind: "step_end", phase: "p", qa_result: { verdict: "fail" } })),
    ).toBe(true);
  });
  it("flags an errored status", () => {
    expect(stepFailed(evt({ seq: 0, kind: "step_end", phase: "p", status: "error" }))).toBe(true);
  });
  it("leaves a clean step alone", () => {
    expect(
      stepFailed(
        evt({ seq: 0, kind: "step_end", phase: "p", status: "complete", judge: { passed: true } }),
      ),
    ).toBe(false);
  });
});

describe("runElapsed", () => {
  it("reads real run seconds off the playhead", () => {
    expect(runElapsed(measured(), 0.5)).toBe(3600);
  });

  it("returns null without measured timing, so no clock is drawn", () => {
    expect(runElapsed(ordinal(), 0.5)).toBeNull();
  });
});

describe("revealedEvents", () => {
  it("reveals by real time when measured", () => {
    const revealed = revealedEvents(measured(), 0.3); // 2160s
    expect(revealed.map((e) => e.seq)).toEqual([0, 1, 2]);
  });

  it("reveals by sequence when ordinal", () => {
    const revealed = revealedEvents(ordinal(), 0.5); // seq <= 2
    expect(revealed.map((e) => e.seq)).toEqual([0, 1, 2]);
  });

  it("reveals everything at the end", () => {
    expect(revealedEvents(measured(), 1)).toHaveLength(6);
    expect(revealedEvents(ordinal(), 1)).toHaveLength(5);
  });

  it("reveals nothing but the origin at the start", () => {
    expect(revealedEvents(measured(), 0).map((e) => e.seq)).toEqual([0, 1]);
  });
});

/** What a real finished run records: phase spans measured, step stamps absent.
 *  Step offsets are interpolated across the phase and flagged estimated. */
function phaseTimed(): DemoTimeline {
  return {
    timing_source: "phase",
    origin: "2026-07-22T19:41:00Z",
    wall_seconds: 5820,
    ladder: [],
    events: [
      evt({ seq: 0, kind: "phase_start", phase: "design", t: 0, t_estimated: false }),
      evt({ seq: 1, kind: "step_start", phase: "design", t: 870, t_estimated: true, skill: "a" }),
      evt({ seq: 2, kind: "step_end", phase: "design", t: 1740, t_estimated: true, skill: "a", status: "complete" }),
      evt({ seq: 3, kind: "phase_start", phase: "commcare", t: 2820, t_estimated: false }),
      evt({ seq: 4, kind: "step_start", phase: "commcare", t: 4320, t_estimated: true, skill: "b" }),
      evt({ seq: 5, kind: "step_end", phase: "commcare", t: 5820, t_estimated: true, skill: "b", status: "complete" }),
    ],
  };
}

describe("phase-level timing", () => {
  it("gives the run a real clock", () => {
    // 19:41 -> 21:18 is 1h37m, and half of it is half of that.
    expect(runElapsed(phaseTimed(), 0.5)).toBe(2910);
  });

  it("lays phases out by their measured share, not by step count", () => {
    const [design, commcare] = bandSegments(phaseTimed());
    expect(design.start).toBeCloseTo(0);
    expect(design.width).toBeCloseTo(1740 / 5820);
    expect(commcare.start).toBeCloseTo(2820 / 5820);
  });

  it("places ticks at the interpolated offsets", () => {
    expect(bandTicks(phaseTimed()).map((t) => t.at)).toEqual([1740 / 5820, 1]);
  });

  it("reveals by the clock rather than by sequence", () => {
    // 30% of 5820 = 1746s, so the first step's end (1740) has just passed.
    expect(revealedEvents(phaseTimed(), 0.3).map((e) => e.seq)).toEqual([0, 1, 2]);
  });

  it("marks interpolated step offsets estimated and phase starts measured", () => {
    const events = phaseTimed().events;
    const steps = events.filter((e) => e.kind !== "phase_start");
    expect(steps.every((e) => e.t_estimated === true)).toBe(true);
    expect(events.filter((e) => e.kind === "phase_start").every((e) => e.t_estimated === false)).toBe(true);
  });
});
