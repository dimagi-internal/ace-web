import { describe, expect, it } from "vitest";

import type { DemoEvent, DemoTimeline, LadderPhase } from "@/api/replay";
import {
  beatAt,
  beatStops,
  findLadderStep,
  paceToProgress,
  progressForBeat,
  progressToPace,
  revealAt,
} from "../cursor";

function evt(p: Partial<DemoEvent> & Pick<DemoEvent, "seq" | "kind" | "phase">): DemoEvent {
  return { t: null, phase_display: p.phase, ...p } as DemoEvent;
}

const LADDER: LadderPhase[] = [
  {
    phase: "design",
    phase_display: "Design",
    ordinal: 1,
    steps: [
      {
        skill: "a", skill_display: "A", ordinal: 1, status: "complete", ran: true,
        judge: null, qa_result: null, artifacts: [],
      },
    ],
  },
];

function timeline(): DemoTimeline {
  return {
    timing_source: "measured",
    origin: "2026-07-22T13:41:00Z",
    wall_seconds: 1000,
    ladder: LADDER,
    events: [
      evt({ seq: 0, kind: "phase_start", phase: "design", t: 0 }),
      evt({ seq: 1, kind: "step_start", phase: "design", t: 0, skill: "a" }),
      evt({ seq: 2, kind: "step_end", phase: "design", t: 400, skill: "a" }),
      evt({ seq: 3, kind: "step_start", phase: "design", t: 400, skill: "b" }),
      evt({ seq: 4, kind: "step_end", phase: "design", t: 1000, skill: "b" }),
    ],
  };
}

describe("beatAt", () => {
  it("lands on the last beat the playhead has passed", () => {
    expect(beatAt(timeline(), 0.5).index).toBe(3); // 500s: past 400, before 1000
    expect(beatAt(timeline(), 1).index).toBe(4);
  });

  it("reports the phase and skill the cursor is inside", () => {
    const beat = beatAt(timeline(), 0.5);
    expect(beat.phase).toBe("design");
    expect(beat.skill).toBe("b");
  });

  it("starts on the run's first beat rather than a dead frame", () => {
    expect(beatAt(timeline(), 0).index).toBeGreaterThanOrEqual(0);
  });

  it("falls back to sequence when the run has no clock", () => {
    const t = { ...timeline(), timing_source: "ordinal" as const, wall_seconds: null };
    expect(beatAt(t, 0.5).index).toBe(2);
  });

  it("has no beat for a run with no events", () => {
    expect(beatAt({ ...timeline(), events: [] }, 0.5).index).toBe(-1);
  });
});

describe("progressForBeat", () => {
  it("round-trips with beatAt", () => {
    const t = timeline();
    for (const index of [0, 2, 4]) {
      expect(beatAt(t, progressForBeat(t, index)).index).toBeGreaterThanOrEqual(index);
    }
  });

  it("clamps out-of-range indexes", () => {
    const t = timeline();
    expect(progressForBeat(t, -5)).toBe(0);
    expect(progressForBeat(t, 99)).toBe(1);
  });
});

describe("revealAt", () => {
  it("separates finished steps from the one in flight", () => {
    const reveal = revealAt(timeline(), 3); // a finished, b started
    expect([...reveal.done]).toEqual(["a"]);
    expect([...reveal.running]).toEqual(["b"]);
  });

  it("moves a step from running to done when its end passes", () => {
    const reveal = revealAt(timeline(), 4);
    expect(reveal.done.has("b")).toBe(true);
    expect(reveal.running.has("b")).toBe(false);
  });

  it("reveals nothing before the first beat", () => {
    const reveal = revealAt(timeline(), -1);
    expect(reveal.done.size).toBe(0);
    expect(reveal.phases.size).toBe(0);
  });
});

describe("findLadderStep", () => {
  it("locates a step by skill", () => {
    expect(findLadderStep(LADDER, "a")?.step.skill_display).toBe("A");
  });
  it("returns null for an unknown skill", () => {
    expect(findLadderStep(LADDER, "nope")).toBeNull();
    expect(findLadderStep(LADDER, null)).toBeNull();
  });
});

describe("beat pacing", () => {
  // A run whose phases are wildly uneven — the real shape. One span holds
  // most of the elapsed time, so a linear sweep would crawl through it.
  const STOPS = [0, 0.02, 0.04, 0.9, 1];

  it("gives every beat the same share of screen time", () => {
    // Four equal segments across five stops: each quarter of playback
    // advances exactly one beat, however long that beat really took.
    expect(paceToProgress(STOPS, 0)).toBeCloseTo(0);
    expect(paceToProgress(STOPS, 0.25)).toBeCloseTo(0.02);
    expect(paceToProgress(STOPS, 0.5)).toBeCloseTo(0.04);
    expect(paceToProgress(STOPS, 0.75)).toBeCloseTo(0.9);
    expect(paceToProgress(STOPS, 1)).toBeCloseTo(1);
  });

  it("glides between beats rather than jumping", () => {
    const mid = paceToProgress(STOPS, 0.625); // halfway from beat 2 to beat 3
    expect(mid).toBeGreaterThan(0.04);
    expect(mid).toBeLessThan(0.9);
    expect(mid).toBeCloseTo((0.04 + 0.9) / 2, 5);
  });

  it("round-trips a scrub on the band back into playback space", () => {
    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      expect(progressToPace(STOPS, paceToProgress(STOPS, t))).toBeCloseTo(t, 5);
    }
  });

  it("clamps out-of-range input at both ends", () => {
    expect(paceToProgress(STOPS, -1)).toBeCloseTo(0);
    expect(paceToProgress(STOPS, 2)).toBeCloseTo(1);
    expect(progressToPace(STOPS, -1)).toBe(0);
    expect(progressToPace(STOPS, 2)).toBe(1);
  });

  it("degrades safely for a run with one beat or none", () => {
    expect(paceToProgress([], 0.5)).toBe(0);
    expect(paceToProgress([0.3], 0.5)).toBe(0.3);
    expect(progressToPace([0.3], 0.5)).toBe(0);
  });

  it("handles repeated stops without dividing by zero", () => {
    // Several beats can share an instant (a phase_start and the step_start
    // beneath it), which makes two stops identical.
    const dup = [0, 0.5, 0.5, 1];
    expect(Number.isFinite(progressToPace(dup, 0.5))).toBe(true);
    expect(Number.isFinite(paceToProgress(dup, 0.5))).toBe(true);
  });

  it("reads the stops straight off the timeline's beats", () => {
    const t = timeline();
    const s = beatStops(t);
    expect(s).toHaveLength(t.events.length);
    expect(s[0]).toBe(0);
    expect(s.at(-1)).toBe(1);
  });
});
