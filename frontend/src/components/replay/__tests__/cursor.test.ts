import { describe, expect, it } from "vitest";

import type { DemoEvent, DemoTimeline, LadderPhase } from "@/api/replay";
import { beatAt, findLadderStep, progressForBeat, revealAt } from "../cursor";

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
