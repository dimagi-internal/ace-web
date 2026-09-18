import { describe, expect, it } from "vitest";

import type { DemoEvent, DemoTimeline } from "@/api/replay";
import { beatAtIndex, beatForSkill, findLadderStep, revealAt, stepFailed } from "../cursor";

function evt(p: Partial<DemoEvent> & Pick<DemoEvent, "seq" | "kind" | "phase">): DemoEvent {
  return { t: null, phase_display: p.phase, ...p } as DemoEvent;
}

const TIMELINE: DemoTimeline = {
  timing_source: "ordinal",
  origin: null,
  wall_seconds: null,
  ladder: [
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
  ],
  events: [
    evt({ seq: 0, kind: "phase_start", phase: "design" }),
    evt({ seq: 1, kind: "step_start", phase: "design", skill: "a" }),
    evt({ seq: 2, kind: "step_end", phase: "design", skill: "a", status: "complete" }),
    evt({ seq: 3, kind: "step_start", phase: "design", skill: "b" }),
    evt({
      seq: 4, kind: "step_end", phase: "design", skill: "b", status: "judge-fail",
      judge: { passed: false },
    }),
  ],
};

describe("beatAtIndex", () => {
  it("returns the event at that step", () => {
    expect(beatAtIndex(TIMELINE, 3).skill).toBe("b");
    expect(beatAtIndex(TIMELINE, 0).event?.kind).toBe("phase_start");
  });
  it("clamps past the end rather than returning nothing", () => {
    expect(beatAtIndex(TIMELINE, 99).index).toBe(4);
  });
  it("has no beat before the start or for an empty run", () => {
    expect(beatAtIndex(TIMELINE, -1).index).toBe(-1);
    expect(beatAtIndex({ ...TIMELINE, events: [] }, 0).index).toBe(-1);
  });
});

describe("revealAt", () => {
  it("separates finished steps from the one in flight", () => {
    const r = revealAt(TIMELINE, 3);
    expect([...r.done]).toEqual(["a"]);
    expect([...r.running]).toEqual(["b"]);
  });
  it("moves a step from running to done when its end is reached", () => {
    const r = revealAt(TIMELINE, 4);
    expect(r.done.has("b")).toBe(true);
    expect(r.running.has("b")).toBe(false);
  });
  it("reveals nothing before the first step", () => {
    expect(revealAt(TIMELINE, -1).phases.size).toBe(0);
  });
});

describe("beatForSkill", () => {
  it("lands on the step where the skill finished", () => {
    expect(beatForSkill(TIMELINE, "a")).toBe(2);
    expect(beatForSkill(TIMELINE, "nope")).toBe(-1);
  });
});

describe("stepFailed", () => {
  it("flags a failing judge", () => {
    expect(stepFailed(TIMELINE.events[4])).toBe(true);
  });
  it("leaves a clean step alone", () => {
    expect(stepFailed(TIMELINE.events[2])).toBe(false);
  });
});

describe("findLadderStep", () => {
  it("locates a step by skill", () => {
    expect(findLadderStep(TIMELINE.ladder, "a")?.step.skill_display).toBe("A");
    expect(findLadderStep(TIMELINE.ladder, null)).toBeNull();
  });
});
