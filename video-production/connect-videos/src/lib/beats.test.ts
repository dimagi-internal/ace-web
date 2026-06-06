import { describe, it, expect, vi } from "vitest";
import { resolveBeats, filterDefaultsForSpec } from "./beats";

const defaults = {
  fps: 30,
  total_seconds: 60,
  beats: [
    { id: "hook",   kind: "intro_hook" as const,    seconds: 4 },
    { id: "cycle",  kind: "intro_cycle" as const,   seconds: 8 },
    { id: "scene",  kind: "body_scene" as const,    seconds: 40 },
    { id: "cta",    kind: "outro_cta" as const,     seconds: 8 },
  ],
};

describe("resolveBeats", () => {
  it("returns beats with start/end frames computed from defaults", () => {
    const resolved = resolveBeats(defaults, {});
    expect(resolved.fps).toBe(30);
    expect(resolved.totalFrames).toBe(60 * 30);
    expect(resolved.beats[0]).toMatchObject({ id: "hook", startFrame: 0, durationFrames: 120 });
    expect(resolved.beats[1]).toMatchObject({ id: "cycle", startFrame: 120, durationFrames: 240 });
    expect(resolved.beats[3]).toMatchObject({ id: "cta", startFrame: 1560, durationFrames: 240 });
  });

  it("applies per-beat overrides and rebalances if total still matches", () => {
    const resolved = resolveBeats(defaults, { scene: { seconds: 35 }, hook: { seconds: 9 } });
    const scene = resolved.beats.find((b) => b.id === "scene")!;
    const hook = resolved.beats.find((b) => b.id === "hook")!;
    expect(scene.durationFrames).toBe(35 * 30);
    expect(hook.durationFrames).toBe(9 * 30);
  });

  it("accepts overridden beats that deviate from total_seconds and uses the new sum", () => {
    // Before the audio-alignment pass this threw; now it's a soft signal
    // because legitimate audio-alignment in render.ts intentionally
    // extends beats beyond the default total. See beats.ts comment.
    const resolved = resolveBeats(defaults, { scene: { seconds: 50 } });
    // Total frames reflect the new sum (4 + 8 + 50 + 8 = 70 seconds).
    expect(resolved.totalFrames).toBe(70 * 30);
    const scene = resolved.beats.find((b) => b.id === "scene")!;
    expect(scene.durationFrames).toBe(50 * 30);
  });

  it("warns (but does not throw) on wildly-off override sums", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      // 100s scene means the sum is 120 vs default 60 — diff > 30s.
      resolveBeats(defaults, { scene: { seconds: 100 } });
      expect(warn).toHaveBeenCalledWith(expect.stringMatching(/sum to/));
    } finally {
      warn.mockRestore();
    }
  });
});

describe("filterDefaultsForSpec (explainer mode — optional stat beats)", () => {
  // Mirror of the global 8-beat timeline in programs/_defaults.yaml.
  const fullDefaults = {
    fps: 30,
    total_seconds: 60,
    beats: [
      { id: "hook", kind: "intro_hook" as const, seconds: 4 },
      { id: "cycle", kind: "intro_cycle" as const, seconds: 8 },
      { id: "handoff", kind: "intro_handoff" as const, seconds: 3 },
      { id: "scene", kind: "body_scene" as const, seconds: 7 },
      { id: "problem", kind: "body_problem_stat" as const, seconds: 10 },
      { id: "product", kind: "body_product_beats" as const, seconds: 12 },
      { id: "impact", kind: "body_impact_stats" as const, seconds: 8 },
      { id: "cta", kind: "outro_cta" as const, seconds: 8 },
    ],
  };

  const kinds = (d: { beats: { kind: string }[] }) => d.beats.map((b) => b.kind);

  it("(a) keeps the full 8-beat timeline when spec has problem + impact", () => {
    const out = filterDefaultsForSpec(fullDefaults, { problem: { big: "1", caption: "c" }, impact: [{ big: "1", caption: "x" }, { big: "2", caption: "y" }] });
    expect(out.beats).toHaveLength(8);
    expect(kinds(out)).toContain("body_problem_stat");
    expect(kinds(out)).toContain("body_impact_stats");
    expect(out.total_seconds).toBe(60);
  });

  it("(b) drops body_problem_stat when spec omits problem; total reduced by its seconds", () => {
    const out = filterDefaultsForSpec(fullDefaults, { impact: [{ big: "1", caption: "x" }, { big: "2", caption: "y" }] });
    expect(out.beats).toHaveLength(7);
    expect(kinds(out)).not.toContain("body_problem_stat");
    expect(kinds(out)).toContain("body_impact_stats");
    expect(out.total_seconds).toBe(60 - 10);
  });

  it("(c) drops body_impact_stats when spec omits impact; total reduced by its seconds", () => {
    const out = filterDefaultsForSpec(fullDefaults, { problem: { big: "1", caption: "c" } });
    expect(out.beats).toHaveLength(7);
    expect(kinds(out)).not.toContain("body_impact_stats");
    expect(kinds(out)).toContain("body_problem_stat");
    expect(out.total_seconds).toBe(60 - 8);
  });

  it("(d) drops both stat beats when spec omits problem + impact (6 beats)", () => {
    const out = filterDefaultsForSpec(fullDefaults, {});
    expect(out.beats).toHaveLength(6);
    expect(kinds(out)).not.toContain("body_problem_stat");
    expect(kinds(out)).not.toContain("body_impact_stats");
    expect(out.total_seconds).toBe(60 - 10 - 8);
  });

  it("the filtered defaults satisfy resolveBeats' sum invariant (no warning)", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const out = filterDefaultsForSpec(fullDefaults, {});
      const resolved = resolveBeats(out, {});
      expect(resolved.totalFrames).toBe((60 - 10 - 8) * 30);
      expect(warn).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });
});
