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

describe("applyOps — structural + content ops (template editor)", () => {
  // A spec carrying its own beats timeline + the optional blocks.
  const withBeats: ProgramSpec = {
    ...baseSpec,
    ai_build: { headline: "H", components: ["a", "b"], subhead: "s" },
    active_cut: "ai",
    scene: { clips: ["@alpha"], lower_third: "old lt" },
    beats: [
      { id: "hook", kind: "intro_hook", seconds: 4 },
      { id: "ai_build", kind: "body_ai_build", seconds: 7 },
      { id: "scene", kind: "body_scene", seconds: 7 },
      { id: "product", kind: "body_product_beats", seconds: 12 },
      { id: "cta", kind: "outro_cta", seconds: 8 },
    ],
  };

  it("set-ai-build merges fields", () => {
    const out = applyOps(withBeats, [
      { op: "set-ai-build", headline: "New", components: ["x", "y", "z"] },
    ]);
    expect(out.ai_build?.headline).toBe("New");
    expect(out.ai_build?.components).toEqual(["x", "y", "z"]);
    expect(out.ai_build?.subhead).toBe("s"); // untouched
  });

  it("set-caption sets a product-beat caption (promotes string slot)", () => {
    const out = applyOps(withBeats, [{ op: "set-caption", index: 0, caption: "Learn" }]);
    const slot = out.product!.beats[0];
    expect(typeof slot === "object" && slot.caption).toBe("Learn");
  });

  it("set-lower-third updates scene.lower_third; empty clears", () => {
    expect(applyOps(withBeats, [{ op: "set-lower-third", text: "new" }]).scene?.lower_third).toBe("new");
    expect(applyOps(withBeats, [{ op: "set-lower-third", text: "" }]).scene?.lower_third).toBeUndefined();
  });

  it("remove-beat drops the block + the beat entry", () => {
    const out = applyOps(withBeats, [{ op: "remove-beat", beatId: "ai_build" }]);
    expect(out.ai_build).toBeUndefined();
    expect(out.beats?.map((b) => b.id)).toEqual(["hook", "scene", "product", "cta"]);
  });

  it("add-beat inserts the block + beat at the canonical position", () => {
    // Start without problem; add it — it should land between scene and product.
    const out = applyOps(withBeats, [{ op: "add-beat", beatId: "problem" }]);
    expect(out.problem).toBeTruthy();
    expect(out.beats?.map((b) => b.id)).toEqual([
      "hook", "ai_build", "scene", "problem", "product", "cta",
    ]);
  });

  it("add then remove of the same beat coalesce to a single buffer slot", () => {
    // (coalescing is handled by opCoalesceKey, exercised via the reducer; here
    // we just confirm applyOps composes them in order: net = removed.)
    const out = applyOps(withBeats, [
      { op: "remove-beat", beatId: "ai_build" },
      { op: "add-beat", beatId: "ai_build" },
    ]);
    expect(out.ai_build).toBeTruthy(); // re-added with defaults
    expect(out.beats?.some((b) => b.id === "ai_build")).toBe(true);
  });

  it("set-beat-order reorders spec.beats to the given id order", () => {
    const out = applyOps(withBeats, [
      { op: "set-beat-order", order: ["cta", "hook", "scene", "ai_build", "product"] },
    ]);
    expect(out.beats?.map((b) => b.id)).toEqual(["cta", "hook", "scene", "ai_build", "product"]);
  });

  it("set-beat-order appends any beats missing from the order list (no silent drop)", () => {
    const out = applyOps(withBeats, [{ op: "set-beat-order", order: ["scene", "hook"] }]);
    // scene + hook first (named), then the rest in original order.
    expect(out.beats?.map((b) => b.id)).toEqual(["scene", "hook", "ai_build", "product", "cta"]);
  });
});
