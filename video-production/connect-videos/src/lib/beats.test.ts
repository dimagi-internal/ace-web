import { describe, it, expect } from "vitest";
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

  it("throws if overridden beats no longer sum to total_seconds", () => {
    expect(() => resolveBeats(defaults, { scene: { seconds: 50 } }))
      .toThrowError(/sum/);
  });
});
