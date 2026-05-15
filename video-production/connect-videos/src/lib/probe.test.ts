import { describe, it, expect } from "vitest";
import { writeFileSync, unlinkSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { probeDurationSeconds } from "./probe";

describe("probeDurationSeconds", () => {
  it("returns null when ffprobe fails on a non-media file", () => {
    const fake = path.join(tmpdir(), `probe-test-${Date.now()}.bin`);
    writeFileSync(fake, "not-a-real-mp3");
    try {
      expect(probeDurationSeconds(fake)).toBeNull();
    } finally {
      if (existsSync(fake)) unlinkSync(fake);
    }
  });

  it("returns null when the file does not exist", () => {
    expect(probeDurationSeconds("/no/such/file.mp3")).toBeNull();
  });
});
