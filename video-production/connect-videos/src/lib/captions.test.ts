import { describe, it, expect } from "vitest";
import { estimateCaptionTimeline } from "./captions";

describe("estimateCaptionTimeline", () => {
  it("splits a multi-sentence script into one caption per sentence", () => {
    const out = estimateCaptionTimeline({
      script: "First sentence here. Second one is longer. Third.",
      durationSeconds: 10,
      fps: 30,
      startFrame: 0,
    });
    expect(out).toHaveLength(3);
    expect(out[0].text).toBe("First sentence here.");
  });

  it("distributes durations proportional to character length", () => {
    const out = estimateCaptionTimeline({
      script: "Short. A much much much much much longer sentence here.",
      durationSeconds: 6,
      fps: 30,
      startFrame: 0,
    });
    const a = out[0].endFrame - out[0].startFrame;
    const b = out[1].endFrame - out[1].startFrame;
    expect(b).toBeGreaterThan(a);
  });

  it("ends exactly at startFrame + durationSeconds * fps", () => {
    const out = estimateCaptionTimeline({
      script: "Sentence one. Sentence two.",
      durationSeconds: 4,
      fps: 30,
      startFrame: 60,
    });
    expect(out[out.length - 1].endFrame).toBe(60 + 4 * 30);
  });
});
