import { describe, it, expect, vi } from "vitest";
import { resolveBeats, filterDefaultsForSpec, effectiveBeatsForSpec } from "./beats";

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

  it("resolves a walkthrough-arc beats list (intro_title + body_walkthrough×N + outro_card)", () => {
    // The walkthrough arc is just another beats list — resolveBeats is
    // arc-agnostic, so the new kinds resolve to frames the same way.
    const walkthrough = {
      fps: 30,
      total_seconds: 31,
      beats: [
        { id: "title", kind: "intro_title" as const, seconds: 4 },
        { id: "s1", kind: "body_walkthrough" as const, seconds: 10 },
        { id: "s2", kind: "body_walkthrough" as const, seconds: 12 },
        { id: "outro", kind: "outro_card" as const, seconds: 5 },
      ],
    };
    const resolved = resolveBeats(walkthrough, {});
    expect(resolved.totalFrames).toBe(31 * 30);
    expect(resolved.beats[0]).toMatchObject({ id: "title", kind: "intro_title", startFrame: 0, durationFrames: 120 });
    expect(resolved.beats[1]).toMatchObject({ id: "s1", kind: "body_walkthrough", startFrame: 120, durationFrames: 300 });
    expect(resolved.beats[3]).toMatchObject({ id: "outro", kind: "outro_card", durationFrames: 150 });
  });
});

describe("filterDefaultsForSpec (explainer mode — optional stat beats)", () => {
  // Mirror of the global 8-beat timeline in programs/global_style.yaml.
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

describe("filterDefaultsForSpec (program-designer AI cut — body_ai_build)", () => {
  // The global timeline with the optional ai_build beat present (mirrors
  // programs/global_style.yaml after the program-designer change). Total
  // 67s = the 60s base + the 7s ai_build beat between handoff and scene.
  const defaultsWithAiBuild = {
    fps: 30,
    total_seconds: 67,
    beats: [
      { id: "hook", kind: "intro_hook" as const, seconds: 4 },
      { id: "cycle", kind: "intro_cycle" as const, seconds: 8 },
      { id: "handoff", kind: "intro_handoff" as const, seconds: 3 },
      { id: "ai_build", kind: "body_ai_build" as const, seconds: 7 },
      { id: "scene", kind: "body_scene" as const, seconds: 7 },
      { id: "problem", kind: "body_problem_stat" as const, seconds: 10 },
      { id: "product", kind: "body_product_beats" as const, seconds: 12 },
      { id: "impact", kind: "body_impact_stats" as const, seconds: 8 },
      { id: "cta", kind: "outro_cta" as const, seconds: 8 },
    ],
  };
  const kinds = (d: { beats: { kind: string }[] }) => d.beats.map((b) => b.kind);
  const aiBuild = { headline: "h", components: ["a", "b"] };
  const impact = [{ big: "1", caption: "x" }, { big: "2", caption: "y" }];

  it("keeps body_ai_build only when ai_build block present AND active_cut is 'ai'", () => {
    const out = filterDefaultsForSpec(defaultsWithAiBuild, {
      ai_build: aiBuild,
      active_cut: "ai",
      impact,
    });
    expect(kinds(out)).toContain("body_ai_build");
    // problem dropped (absent), impact kept, ai_build kept.
    expect(kinds(out)).not.toContain("body_problem_stat");
    // 67 - 10 (problem) = 57s — the AI cut duration.
    expect(out.total_seconds).toBe(57);
  });

  it("drops body_ai_build in the standard cut (ai_build present, active_cut 'standard')", () => {
    const out = filterDefaultsForSpec(defaultsWithAiBuild, {
      ai_build: aiBuild,
      active_cut: "standard",
      impact,
    });
    expect(kinds(out)).not.toContain("body_ai_build");
    // 67 - 7 (ai_build) - 10 (problem) = 50s — the standard cut.
    expect(out.total_seconds).toBe(50);
  });

  it("drops body_ai_build when active_cut is missing (defaults to non-AI)", () => {
    const out = filterDefaultsForSpec(defaultsWithAiBuild, { ai_build: aiBuild, impact });
    expect(kinds(out)).not.toContain("body_ai_build");
  });

  it("drops body_ai_build when the ai_build block is absent even if active_cut is 'ai'", () => {
    const out = filterDefaultsForSpec(defaultsWithAiBuild, { active_cut: "ai", impact });
    expect(kinds(out)).not.toContain("body_ai_build");
  });

  it("leaves other templates (no ai_build) byte-for-byte: full mbw-like spec drops only ai_build", () => {
    // A full spec with problem + impact but no ai_build (every pre-existing
    // template) must keep its original 8 beats and 60s — the ai_build beat
    // is the only thing removed from the 9-beat global timeline.
    const out = filterDefaultsForSpec(defaultsWithAiBuild, {
      problem: { big: "1", caption: "c" },
      impact,
    });
    expect(kinds(out)).not.toContain("body_ai_build");
    expect(out.beats).toHaveLength(8);
    expect(out.total_seconds).toBe(60);
  });
});

describe("effectiveBeatsForSpec — structure belongs to the spec", () => {
  const base = {
    fps: 30,
    total_seconds: 60,
    beats: [
      { id: "hook", kind: "intro_hook" as const, seconds: 4 },
      { id: "cycle", kind: "intro_cycle" as const, seconds: 8 },
      { id: "problem", kind: "body_problem_stat" as const, seconds: 10 },
    ],
  };

  it("uses the spec's own beats verbatim when present (no optional-beat filtering)", () => {
    // Spec defines a custom 2-beat timeline and carries NO problem block —
    // under the legacy path the problem beat would be filtered out, but an
    // explicit beats list is authoritative and used as-is.
    const out = effectiveBeatsForSpec(base, {
      beats: [
        { id: "hook", kind: "intro_hook", seconds: 5 },
        { id: "cta", kind: "outro_cta", seconds: 6 },
      ],
    });
    expect(out.beats.map((b) => b.id)).toEqual(["hook", "cta"]);
    expect(out.beats[0].seconds).toBe(5);
    expect(out.total_seconds).toBe(11);
    expect(out.fps).toBe(30);
  });

  it("falls back to filterDefaultsForSpec when the spec has no beats", () => {
    // No explicit beats + no problem block → legacy path drops body_problem_stat.
    const out = effectiveBeatsForSpec(base, {});
    expect(out.beats.map((b) => b.id)).toEqual(["hook", "cycle"]);
    expect(out.total_seconds).toBe(12);
  });

  it("treats an empty beats array as absent (fallback)", () => {
    const out = effectiveBeatsForSpec(base, { beats: [], problem: { big: "1", caption: "c" } });
    // problem present → kept by the fallback filter
    expect(out.beats.map((b) => b.id)).toEqual(["hook", "cycle", "problem"]);
  });
});
