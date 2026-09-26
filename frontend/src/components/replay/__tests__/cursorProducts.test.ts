import { describe, expect, it } from "vitest";

import type { DemoEvent, DemoTimeline, ReplayProduct } from "@/api/replay";

import {
  highlightBeats,
  phasesFinishedAt,
  productsAtBeat,
  revealIndexOf,
  stepDocuments,
} from "../cursor";
import { groupSpans, phaseGroupOf } from "../phaseGroups";

function evt(p: Partial<DemoEvent> & Pick<DemoEvent, "seq" | "kind" | "phase">): DemoEvent {
  return { t: null, phase_display: p.phase, ...p } as DemoEvent;
}

function product(id: string, reveal_seq: number | null): ReplayProduct {
  return {
    id, phase: "p", key: id, kind: "document", title: id, subtitle: null, url: null,
    file_id: null, facts: [], producer: null, chatbot: null, reveal_seq,
  };
}

const EVENTS: DemoEvent[] = [
  evt({ seq: 0, kind: "phase_start", phase: "design" }),
  evt({ seq: 1, kind: "step_start", phase: "design", skill: "a" }),
  evt({ seq: 2, kind: "step_end", phase: "design", skill: "a", status: "complete" }),
  evt({ seq: 3, kind: "step_start", phase: "design", skill: "b" }),
  evt({ seq: 4, kind: "step_end", phase: "design", skill: "b", status: "complete" }),
  evt({ seq: 5, kind: "phase_start", phase: "build" }),
  evt({ seq: 6, kind: "step_start", phase: "build", skill: "c" }),
  evt({ seq: 7, kind: "step_end", phase: "build", skill: "c", status: "judge-fail",
        judge: { passed: false } }),
  evt({ seq: 8, kind: "step_start", phase: "build", skill: "d" }),
  evt({ seq: 9, kind: "step_end", phase: "build", skill: "d", status: "complete" }),
];

const TIMELINE: DemoTimeline = {
  timing_source: "ordinal",
  origin: null,
  wall_seconds: null,
  ladder: [],
  events: EVENTS,
  products: [product("pdd", 2), product("carried", null)],
};

describe("products in the replay", () => {
  it("appear at their beat; an unplaced one at the final beat", () => {
    expect(revealIndexOf(TIMELINE.products![0], EVENTS.length)).toBe(2);
    expect(revealIndexOf(TIMELINE.products![1], EVENTS.length)).toBe(9);
  });

  it("are announced only on exactly their beat", () => {
    expect(productsAtBeat(TIMELINE, 2).map((p) => p.id)).toEqual(["pdd"]);
    expect(productsAtBeat(TIMELINE, 3)).toEqual([]);
    expect(productsAtBeat(TIMELINE, 9).map((p) => p.id)).toEqual(["carried"]);
  });
});

describe("phasesFinishedAt", () => {
  it("counts a phase finished once its last step has", () => {
    expect([...phasesFinishedAt(TIMELINE, 3)]).toEqual([]);
    expect([...phasesFinishedAt(TIMELINE, 4)]).toEqual(["design"]);
    expect([...phasesFinishedAt(TIMELINE, 9)].sort()).toEqual(["build", "design"]);
  });
});

describe("highlightBeats", () => {
  it("keeps phase starts, product reveals, failures and the last beat", () => {
    expect(highlightBeats(TIMELINE)).toEqual([0, 2, 5, 7, 9]);
  });

  it("adds finishes that recorded decisions", () => {
    expect(highlightBeats(TIMELINE, new Set(["b"]))).toEqual([0, 2, 4, 5, 7, 9]);
  });
});

describe("phase groups", () => {
  it("groups ACE's phases one level up and leaves unknown ones alone", () => {
    expect(phaseGroupOf("connect-setup")).toBe("Product setup");
    expect(phaseGroupOf("something-new")).toBeNull();
    expect(
      groupSpans(["idea-to-design", "scenarios-and-acceptance", "commcare-setup", "connect-setup",
                  "ocs-setup", "something-new", "closeout"]),
    ).toEqual([
      { label: "Design", from: 0, count: 2 },
      { label: "Product setup", from: 2, count: 3 },
      { label: null, from: 5, count: 1 },
      { label: "Partner & launch", from: 6, count: 1 },
    ]);
  });
});

describe("stepDocuments", () => {
  const art = (name: string, id: string) => ({
    name, drive_file_id: id, drive_web_link: "", mime_type: "", size_bytes: null, path: `x/${name}`,
  });
  const step = {
    artifacts: [art("summary.md", "a"), art("verdict.yaml", "b"), art("pdd.md", "c")],
  } as unknown as import("@/api/types.ws").Step;

  it("pops up a step's markdown, not its YAML, and not what a product already shows", () => {
    expect(stepDocuments(step).map((a) => a.name)).toEqual(["summary.md", "pdd.md"]);
    expect(stepDocuments(step, new Set(["c"])).map((a) => a.name)).toEqual(["summary.md"]);
    expect(stepDocuments(undefined)).toEqual([]);
  });
});
