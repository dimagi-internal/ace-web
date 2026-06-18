import { describe, it, expect } from "vitest";
import { freezeRangeFrames } from "./Walkthrough";

const FPS = 30;

describe("freezeRangeFrames (hold-last-frame on overflow)", () => {
  it("freezes when the beat runs longer than the selected range", () => {
    // 9.276s range, but the audio-aligner stretched the beat to 12s (360f).
    // The clip should play its 278-frame range then hold.
    const rangeFrames = freezeRangeFrames(9.276, FPS, 12 * FPS);
    expect(rangeFrames).toBe(Math.round(9.276 * FPS)); // 278
    expect(rangeFrames!).toBeLessThan(12 * FPS);
  });

  it("does NOT freeze when the range is at least as long as the beat", () => {
    // Beat on-screen == range: play the whole thing, no freeze.
    expect(freezeRangeFrames(10, FPS, 10 * FPS)).toBeNull();
    // Range longer than the beat: also no freeze (beat is the hard cap).
    expect(freezeRangeFrames(12, FPS, 10 * FPS)).toBeNull();
  });

  it("falls back to playing the whole beat when duration_seconds is absent", () => {
    expect(freezeRangeFrames(undefined, FPS, 10 * FPS)).toBeNull();
  });

  it("clamps a sub-frame range to at least one frame", () => {
    // A tiny positive range still yields a >=1 frame freeze point.
    expect(freezeRangeFrames(0.001, FPS, 5 * FPS)).toBe(1);
  });
});
