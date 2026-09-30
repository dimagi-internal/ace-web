import { describe, expect, it } from "vitest";

import type { DemoEvent, DemoTimeline, ReplayProduct } from "@/api/replay";

import {
  phasesFinishedAt,
  productAsOf,
  productsAtBeat,
  productsPhotographedAt,
  revealIndexOf,
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

describe("screenshots in the replay", () => {
  const shot = (file_id: string, reveal_seq: number | null) => ({
    file_id, name: `${file_id}.png`, caption: null, mime_type: "image/png",
    captured_by: "cap", reveal_seq,
  });
  const app: ReplayProduct = { ...product("app", 4), previews: [shot("s1", 7), shot("s2", null)] };
  const timeline: DemoTimeline = { ...TIMELINE, products: [app] };
  const total = EVENTS.length;

  it("a product carries only the screenshots already taken", () => {
    expect(productAsOf(app, 4, total).previews).toEqual([]);
    expect(productAsOf(app, 7, total).previews?.map((p) => p.file_id)).toEqual(["s1"]);
    // Unplaced → the final beat, like an unplaced product.
    expect(productAsOf(app, total - 1, total)).toBe(app);
  });

  it("a beat that photographs an earlier product is its own cue", () => {
    expect(productsPhotographedAt(timeline, 7).map((p) => p.id)).toEqual(["app"]);
    expect(productsPhotographedAt(timeline, 4)).toEqual([]);
  });

});
