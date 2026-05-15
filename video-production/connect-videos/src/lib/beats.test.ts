import { describe, it, expect, vi } from "vitest";
import { resolveBeats } from "./beats";

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
