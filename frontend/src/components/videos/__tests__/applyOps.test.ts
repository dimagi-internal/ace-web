import { describe, expect, it } from "vitest";
import type { ProgramSpec, PendingChange } from "../types";
import { applyOps } from "../applyOps";

const baseSpec: ProgramSpec = {
  slug: "demo",
  name: "Demo",
  scene: { clips: ["@alpha"] },
  product: { beats: [{ asset: "@alpha", caption: "first" }] },
  problem: { big: "29%", caption: "old", source: "NDHS 2018" },
  impact: [
    { big: "$1", caption: "a" },
    { big: "$2", caption: "b" },
  ],
  narration: { by_beat: {} },
};

describe("applyOps", () => {
  it("returns spec unchanged for empty ops", () => {
    expect(applyOps(baseSpec, [])).toEqual(baseSpec);
  });

  it("applies set-narration", () => {
    const ops: PendingChange[] = [
      { op: "set-narration", beatId: "hook", text: "Hi" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.narration.by_beat.hook).toBe("Hi");
    expect(baseSpec.narration.by_beat).toEqual({}); // immutability
  });

  it("applies set-stat for problem", () => {
    const ops: PendingChange[] = [
      { op: "set-stat", path: "problem", big: "31%" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.problem?.big).toBe("31%");
    expect(out.problem?.caption).toBe("old"); // untouched
  });

  it("applies set-stat for impact[i]", () => {
    const ops: PendingChange[] = [
      { op: "set-stat", path: "impact[1]", big: "$5" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.impact?.[0].big).toBe("$1");
    expect(out.impact?.[1].big).toBe("$5");
  });

  it("applies set-clip-trim to product beat", () => {
    const ops: PendingChange[] = [
      { op: "set-clip-trim", kind: "product-beat", index: 0,
        start_seconds: 1.5, duration_seconds: 3.0 },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.product?.beats[0]).toMatchObject({
      asset: "@alpha", start_seconds: 1.5, duration_seconds: 3.0,
    });
  });

  it("applies set-clip-asset to scene clip (replaces string ref)", () => {
    const ops: PendingChange[] = [
      { op: "set-clip-asset", kind: "scene-clip", index: 0, alias: "beta" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.scene?.clips[0]).toBe("@beta");
  });

  it("applies multiple ops in order", () => {
    const ops: PendingChange[] = [
      { op: "set-narration", beatId: "hook", text: "v1" },
      { op: "set-narration", beatId: "hook", text: "v2" },
      { op: "set-stat", path: "problem", big: "31%" },
    ];
    const out = applyOps(baseSpec, ops);
    expect(out.narration.by_beat.hook).toBe("v2"); // last wins
    expect(out.problem?.big).toBe("31%");
  });
});
